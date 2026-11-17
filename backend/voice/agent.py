"""
The voice agent ("the mind"), voicefirst.md steps 2-3 + "Fixes before Step 4".

ONE Groq call per turn decides (retried once on a transient Groq error); tools:
navigate, answer_question, search_places, get_weather, list_my_trips, open_trip, cant_help. Read-only.

transcript + memory + current state -> Groq (function calling) -> our code checks the call and runs the tool
(voice/pages.py, voice/tools/lookups.py, tour_guide_service.voice_answer) -> (reply_text, ui_actions, note).
The model never touches data and never supplies a trip ID: trips are looked up by the session's user.
"Where is X" answers with city/state and keeps the map actions pending; "haan"/"yes" runs them (no LLM call).
Logs carry the action, timings and error codes only, never the user's words or the reply.

Memory: Redis voice:mem:{user_id}:{conversation_id}, last 10 turns (user + assistant), 30-minute
TTL refreshed each turn, deleted on end_session. Pending map actions: voice:pending:{user}:{conversation}, 2 min.
"""
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from voice import pages
from voice.lang import detect_lang

logger = logging.getLogger("voice")

MEMORY_TURNS = 10
MEMORY_TTL_SECONDS = 30 * 60
PENDING_TTL_SECONDS = 120
LLM_TIMEOUT_SECONDS = 8
FALLBACK_REPLY = "Abhi samajh nahi paaya, phir se boliye."

# Garbled words have no reliable language, so "unclear" is always said in Hinglish (fixes-before-step4 item 6).
UNCLEAR_REPLY = {"hi": "Samajh nahi aaya, phir se boliye.", "en": "Samajh nahi aaya, phir se boliye."}
DECLINE_REPLY = {"hi": "Main sirf aapki trip mein madad kar sakta hoon.", "en": "I can only help with your trip."}
OK_NO_REPLY = {"hi": "Theek hai.", "en": "Okay."}
ANSWER_FAILED = {"hi": "Abhi jawab nahi mil paaya, thodi der mein phir poochhiye.",
                 "en": "I couldn't get an answer right now, please ask again in a moment."}

SYSTEM_PROMPT = """You are VoyageAI's voice assistant inside a travel app for Indian users.

How to reply:
- Reply in the language the user spoke: Hinglish in Roman script, Hindi, or English.
- Your reply is spoken aloud: at most 2 short sentences, no lists, no emojis.

Call exactly one tool when it fits:
- navigate: open a page. "Plan a new trip" / "nayi trip banani hai" -> navigate to plan_trip at once,
  do not ask for details. "Itinerary kholo" without a day -> navigate to itinerary, do not ask which day.
- get_weather: ANY weather question (baarish, rain, mausam, temperature, garmi, thand, kal ka mausam).
  Never use answer_question for weather.
- search_places: a NAMED place.
  * "X kahan hai" / "where is X" -> show=false (we tell them where it is and offer the map).
  * "X dikhao" / "show me X" / "X map pe dikhao" -> show=true (open the map).
  * query = the place's usual written name, fixing speech-to-text spelling: "4 minar" -> "Charminar",
    "taaj mahal" -> "Taj Mahal". If the last reply offered a choice ("A ya B?"), the answer is the place.
  General "ghoomne ki jagah dikhao" / things to do -> navigate to explore instead.
- answer_question: other travel questions (timings, tickets, prices, food, culture, transport, tips).
  Do NOT answer these from memory. Set facts=true for timings, opening hours, prices, entry fees.
  ("Where can I eat" / "khana kahan milega" nearby -> navigate to food instead.)
- list_my_trips: which trips the user has ("meri trips kaun si hain"); past trips only for purani / past.
- open_trip: open a specific trip by name, destination, month, or next/current/last ("Goa wali trip kholo",
  "agli trip kholo"). If you asked "which one?" and the user answers with a month, call open_trip again.
- cant_help: reason="off_topic" for clear non-travel requests (jokes, cricket, coding, politics);
  reason="unclear" when the words are garbled, nonsense or can't be understood. Don't guess what garbled
  words meant.
- If the request is understandable but unclear (e.g. "woh wala kholo"), ask ONE short question.
- update_trip_draft: the user wants to create a trip by voice and gives details ("Goa jaana hai, 15 se 18
  December, do log", "trip banao Jaipur ke liye"), or answers a question about the trip being planned, or
  corrects a detail ("nahi, budget 50 hazaar kar do"). Pass ONLY values the user said:
  dates as YYYY-MM-DD from today's date ("15 December" = the next 15 December; "agle Friday"); "3 din ke liye"
  -> days=3; people as integers ("do log" -> adults=2, "koi bachcha nahi" -> children=0); budget in rupees as a
  number ("50 hazaar" -> 50000, "1.5 lakh" -> 150000); origin_city for "Delhi se". start_new=true only when the
  user starts a different new trip while one is being planned. Never ask for details yourself: our code asks.
  A destination alone counts as a detail ("plan a trip to Manali" -> update_trip_draft).
  "Nayi trip banani hai" / "plan a new trip" with NO details at all -> navigate to plan_trip.
- cancel_trip_draft: the user wants to stop planning this trip ("cancel karo", "trip mat banao").
- Never invent pages, routes, trips, places or facts.

Current state:
- Today (India): {today}
- User is on page: {screen}
- Open trip: {trip_line}
- Trip being planned by voice: {draft_line}"""


def _nullable(t: str) -> List[str]:
    # Groq validates tool arguments strictly and the model often sends null for "not given".
    return [t, "null"]


NAVIGATE_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "navigate",
        "description": "Open a page of the app. Pages: " + "; ".join(f"{p}: {m}" for p, m in pages.MEANINGS.items()) + ".",
        "parameters": {
            "type": "object",
            "properties": {
                "page": {"type": "string", "enum": pages.PAGES},
                "day": {"type": _nullable("integer"), "minimum": pages.MIN_DAY, "maximum": pages.MAX_DAY,
                        "description": "Only for itinerary: which day to open."},
            },
            "required": ["page"],
        },
    },
}
ANSWER_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "answer_question",
        "description": "Answer a travel question (timings, tickets, prices, food, culture, transport, tips) with the "
                       "tour guide. Not for weather (use get_weather) and not for where a place is (use search_places).",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The user's question, cleaned up, in their language."},
                "place": {"type": _nullable("string"), "description": "The place it is about, if any."},
                "facts": {"type": _nullable("boolean"),
                          "description": "true if it asks for timings, opening hours, prices, entry fees or ticket costs."},
            },
            "required": ["question"],
        },
    },
}
SEARCH_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "search_places",
        "description": "A named place in India. show=false for 'X kahan hai / where is X' (tell where it is, offer the map); "
                       "show=true for 'X dikhao / show me X' (open the map).",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The place's usual written name, e.g. 'Hawa Mahal Jaipur'; "
                                                            "fix speech-to-text spelling ('4 minar' -> 'Charminar')."},
                "show": {"type": "boolean", "description": "true = open the map now; false = say where it is and ask."},
            },
            "required": ["query", "show"],
        },
    },
}
WEATHER_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Real weather forecast (rain chance, temperature) for a place and day, up to 16 days ahead. "
                       "Without a place, the open trip's destination is used.",
        "parameters": {
            "type": "object",
            "properties": {
                "place": {"type": _nullable("string"), "description": "City or place, e.g. 'Jaipur'."},
                "day": {"type": _nullable("string"),
                        "description": "today | tomorrow | day_after_tomorrow | a date YYYY-MM-DD. Kal = tomorrow, parso = day_after_tomorrow."},
            },
        },
    },
}
LIST_TRIPS_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "list_my_trips",
        "description": "Say which trips the user has and open My trips.",
        "parameters": {
            "type": "object",
            "properties": {"include_past": {"type": _nullable("boolean"), "description": "true only if the user asks for past/old (purani) trips."}},
        },
    },
}
OPEN_TRIP_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "open_trip",
        "description": "Open one of the user's own trips, found by name/destination, month, or which (next/current/last).",
        "parameters": {
            "type": "object",
            "properties": {
                "name_or_destination": {"type": _nullable("string"), "description": "Trip name or destination, e.g. 'Goa'."},
                "month": {"type": _nullable("string"), "description": "Month of the trip start, e.g. 'December' or '12'."},
                "which": {"type": _nullable("string"), "enum": ["next", "current", "last", None]},
            },
        },
    },
}
CANT_HELP_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "cant_help",
        "description": "The request can't be handled: off_topic (clear non-travel request) or unclear (garbled / nonsense words).",
        "parameters": {
            "type": "object",
            "properties": {"reason": {"type": "string", "enum": ["off_topic", "unclear"]}},
            "required": ["reason"],
        },
    },
}
UPDATE_DRAFT_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "update_trip_draft",
        "description": "Create a trip by voice: save the trip details the user said (any subset). Our code checks them, "
                       "decides what is still missing and asks for it.",
        "parameters": {
            "type": "object",
            "properties": {
                "destination": {"type": _nullable("string"), "description": "Where to go, e.g. 'Jaipur'."},
                "origin_city": {"type": _nullable("string"), "description": "Starting city, e.g. 'Delhi'."},
                "start_date": {"type": _nullable("string"), "description": "YYYY-MM-DD."},
                "end_date": {"type": _nullable("string"), "description": "YYYY-MM-DD (last day of the trip)."},
                "days": {"type": _nullable("integer"), "description": "Trip length in days, if said instead of an end date."},
                "adults": {"type": _nullable("integer")},
                "children": {"type": _nullable("integer")},
                "budget_inr": {"type": _nullable("number"), "description": "Total budget in rupees."},
                "start_new": {"type": _nullable("boolean"), "description": "true only for a different new trip while one is being planned."},
            },
        },
    },
}
CANCEL_DRAFT_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "cancel_trip_draft",
        "description": "Stop planning the trip being created by voice; nothing is saved.",
        "parameters": {"type": "object", "properties": {}},
    },
}
TOOLS = [NAVIGATE_TOOL, ANSWER_TOOL, SEARCH_TOOL, WEATHER_TOOL, LIST_TRIPS_TOOL, OPEN_TRIP_TOOL, CANT_HELP_TOOL,
         UPDATE_DRAFT_TOOL, CANCEL_DRAFT_TOOL]
TOOL_NAMES = {t["function"]["name"] for t in TOOLS}


@dataclass
class TripInfo:
    title: str
    start_date: Optional[str]
    end_date: Optional[str]
    id: Optional[str] = None   # set by ws._resolve_trip only after the ownership check


@dataclass
class AgentResult:
    reply_text: str
    ui_actions: List[Dict[str, Any]] = field(default_factory=list)
    # navigate:<page> | map_focus | where | answer | weather | decline | unclear | list_trips | open_trip | reply | error
    action: str = "reply"
    llm_ms: int = 0                   # the deciding Groq call(s)
    tool_ms: int = 0                  # the tool (answer: cost guard + Gemini/Groq; look-ups: Google/DB/Open-Meteo)
    error_code: Optional[str] = None  # logs, and sent to the app (reply.error_code) so a failure shows its reason
    error_detail: Optional[str] = None  # short reason: status/code or "<Exc>: <message>", max 200 chars
    note: Optional[str] = None        # small on-screen text, never spoken (e.g. "Details badal sakti hain.")
    pending_actions: List[Dict[str, Any]] = field(default_factory=list)
    pending_confirmation: Optional[Dict[str, Any]] = None   # {id, summary}: the app shows the Confirm card
    step: Optional[str] = None                              # trip draft: ask | confirm_date | ready (logs)
    missing_count: Optional[int] = None                     # trip draft: missing fields (logs)
    google_calls: Optional[int] = None                      # Google requests made by a look-up tool (logs)


def template_language(stt_language: Optional[str], text: Optional[str] = None) -> str:
    """Template language from the user's words (item 8); Whisper's tag only when there are no words."""
    if text is not None:
        return detect_lang(text, stt_language)
    lang = (stt_language or "").strip().lower()
    return "en" if lang == "en" else "hi"


def build_system_prompt(screen: Optional[str], trip: Optional[TripInfo], today: Optional[str] = None,
                        draft_line: str = "none") -> str:
    trip_line = (f"{trip.title} ({trip.start_date or '?'} to {trip.end_date or '?'})" if trip else "none")
    if today is None:
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone(timedelta(hours=5, minutes=30)))
        today = f"{now.strftime('%A %d %B %Y')} ({now.date().isoformat()})"
    return SYSTEM_PROMPT.format(screen=(screen or "unknown")[:120], trip_line=trip_line, today=today, draft_line=draft_line)


def _draft_line(d) -> str:
    """The draft for the prompt: field names and values the user gave (in the prompt only, never logged)."""
    if d is None:
        return "none"
    have = {k: v for k, v in {
        "destination": (d.destination or {}).get("name"), "origin_city": (d.origin_city or {}).get("name"),
        "start_date": d.start_date, "end_date": d.end_date, "days": d.days, "adults": d.adults,
        "children": d.children, "budget_inr": d.budget_inr}.items() if v is not None}
    return f"have {json.dumps(have)}; still missing {d.missing_fields()} (our code asks for them)"


def trim_sentences(text: str, limit: int = 2) -> str:
    """Spoken replies stay short: keep the first `limit` sentences."""
    text = re.sub(r"\s+", " ", (text or "").strip())
    parts = re.split(r"(?<=[.!?।])\s+", text)
    return " ".join(parts[:limit]).strip()


def is_garbled(text: str) -> bool:
    """No real words at all (noise, a single letter, only symbols): no LLM call needed."""
    letters = re.findall(r"[^\W\d_]", text or "", re.UNICODE)
    return len(letters) < 2


_YES = {"haan", "haa", "ha", "han", "haanji", "ji", "yes", "yeah", "yep", "sure", "ok", "okay", "theek", "thik", "hai",
        "dikhao", "dikha", "do", "show", "please", "zaroor", "bilkul", "kholo", "it", "me", "on", "map", "the", "par", "pe"}
_YES_CORE = {"haan", "haa", "ha", "han", "haanji", "yes", "yeah", "yep", "sure", "ok", "okay", "zaroor", "bilkul", "theek", "thik",
             "dikhao", "show"}
_NO = {"nahi", "nahin", "na", "no", "nope", "mat", "rehne", "rahne", "do", "dijiye", "ji", "thanks", "thank", "you", "zarurat"}
_NO_CORE = {"nahi", "nahin", "na", "no", "nope", "mat", "rehne", "rahne", "cancel"}
_NO.update({"cancel", "karo", "kar", "trip", "banao", "galat", "wrong"})
_YES.update({"sahi", "correct", "right", "confirm", "proceed", "kar", "banao", "haanji", "bilkul"})
_YES_CORE.update({"sahi", "correct", "right", "confirm", "proceed"})


def yes_or_no(text: str) -> Optional[str]:
    words = re.findall(r"[a-z]+", (text or "").lower())
    if not words or len(words) > 5:
        return None
    if set(words) <= _YES and set(words) & _YES_CORE:
        return "yes"
    if set(words) <= _NO and set(words) & _NO_CORE:
        return "no"
    return None


# ---------------- memory (Redis)

def _mem_key(user_id: str, conversation_id: str) -> str:
    return f"voice:mem:{user_id}:{conversation_id}"


def load_memory(redis_conn, user_id: str, conversation_id: str) -> List[Dict[str, str]]:
    try:
        raw = redis_conn.get(_mem_key(user_id, conversation_id))
        if not raw:
            return []
        data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
        return [m for m in data if isinstance(m, dict) and m.get("role") in ("user", "assistant")]
    except Exception as err:
        # The turn continues without memory; say why instead of silently dropping context.
        logger.warning("[VOICE AGENT] memory load failed: %s: %s", type(err).__name__, str(err)[:200])
        return []


def save_turn(redis_conn, user_id: str, conversation_id: str, user_text: str, reply_text: str) -> None:
    try:
        history = load_memory(redis_conn, user_id, conversation_id)
        history += [{"role": "user", "content": user_text}, {"role": "assistant", "content": reply_text}]
        history = history[-MEMORY_TURNS * 2:]
        redis_conn.setex(_mem_key(user_id, conversation_id), MEMORY_TTL_SECONDS, json.dumps(history))
    except Exception as err:
        logger.warning("[VOICE AGENT] memory save failed: %s: %s", type(err).__name__, str(err)[:200])


def clear_memory(redis_conn, user_id: str, conversation_id: Optional[str] = None) -> None:
    """end_session: the conversation's memory (or all of the user's voice memory) is deleted."""
    try:
        if conversation_id:
            redis_conn.delete(_mem_key(user_id, conversation_id))
            redis_conn.delete(_pending_key(user_id, conversation_id))
            redis_conn.delete(f"voice:draft:{user_id}:{conversation_id}")    # step 4: the trip draft
            redis_conn.delete(f"voice:confirm:{user_id}:{conversation_id}")  # step 4: the pending confirmation
        else:
            for prefix in ("voice:mem", "voice:pending", "voice:draft", "voice:confirm"):
                for key in redis_conn.scan_iter(f"{prefix}:{user_id}:*"):
                    redis_conn.delete(key)
    except Exception as err:
        logger.warning("[VOICE AGENT] memory clear failed: %s: %s", type(err).__name__, str(err)[:200])


def _pending_key(user_id: str, conversation_id: str) -> str:
    return f"voice:pending:{user_id}:{conversation_id}"


def save_pending(redis_conn, user_id: str, conversation_id: str, actions: List[Dict[str, Any]]) -> None:
    try:
        redis_conn.setex(_pending_key(user_id, conversation_id), PENDING_TTL_SECONDS, json.dumps(actions))
    except Exception as err:
        logger.warning("[VOICE AGENT] pending save failed: %s: %s", type(err).__name__, str(err)[:200])


def pop_pending(redis_conn, user_id: str, conversation_id: str) -> List[Dict[str, Any]]:
    try:
        key = _pending_key(user_id, conversation_id)
        raw = redis_conn.get(key)
        if raw:
            redis_conn.delete(key)
            data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
            return [a for a in data if isinstance(a, dict) and a.get("type") in ("map_focus", "navigate")]
    except Exception as err:
        logger.warning("[VOICE AGENT] pending pop failed: %s: %s", type(err).__name__, str(err)[:200])
    return []


# ---------------- the turn

def _navigate(args: Dict[str, Any], lang: str, has_trip: bool) -> AgentResult:
    page = args.get("page")
    day = args.get("day")
    route, err = pages.resolve(page, day, has_trip)
    if err is None:
        return AgentResult(pages.confirm_text(page, day, lang),
                           ui_actions=[{"type": "navigate", "to": route}], action=f"navigate:{page}")
    if err == "no_trip":
        return AgentResult(pages.NO_TRIP_REPLY[lang], ui_actions=[{"type": "navigate", "to": pages.ROUTES["my_trips"]}],
                           action="navigate:my_trips", error_code="no_trip")
    return AgentResult(pages.WHICH_PAGE_REPLY[lang], action="reply", error_code=err)


def _from_tool(r) -> AgentResult:
    return AgentResult(r.reply_text, ui_actions=list(r.ui_actions), action=r.action, error_code=r.error_code,
                       pending_actions=list(getattr(r, "pending_actions", []) or []),
                       google_calls=getattr(r, "google_calls", None))


def _norm_text(s: str) -> str:
    return re.sub(r"[^a-z ]", "", (s or "").lower()).strip()


# ---------------- create a trip by voice (step 4)

READY_REPLY = {"hi": "Sab details review page par hain. Check karke Proceed dabaiye, ya haan boliye.",
               "en": "All details are on the review page. Check them and tap Proceed, or say yes."}
CONFIRMED_REPLY = {"hi": "Trip bana raha hoon.", "en": "Creating your trip."}
NOTHING_TO_CONFIRM = {"hi": "Abhi confirm karne ke liye kuch nahi hai.", "en": "There's nothing to confirm right now."}
CANCELLED_REPLY = {"hi": "Theek hai, trip nahi banayi. Kuch save nahi hua.", "en": "Okay, no trip was created. Nothing was saved."}
REPLACED_NOTE = {"hi": "Pichli trip ka draft hata diya.", "en": "I dropped the previous trip draft."}
DATE_AGAIN = {"hi": "Theek hai, kab se kab tak jaana hai?", "en": "Okay, from which date to which date?"}


def _draft_today():
    from trip_lifecycle import today_ist
    return today_ist()


def draft_next(redis_conn, user_id: str, conversation_id: str, d, lang: str, prefix: str = "") -> AgentResult:
    """What to say next for a draft. CODE decides: ask (<= 2 missing fields) / read the dates back / ready."""
    from voice import draft as D, pending as P
    step = d.next_step()
    missing = d.missing_fields()
    if step == "ask":
        d.awaiting = None
        D.save(redis_conn, user_id, conversation_id, d)
        text = f"{prefix} {D.question_for(missing, lang, days_known=bool(d.days))}".strip()
        return AgentResult(text, action="trip_draft", step="ask", missing_count=len(missing))
    if step == "confirm_date":
        d.awaiting = "date"
        D.save(redis_conn, user_id, conversation_id, d)
        return AgentResult(f"{prefix} {D.readback(d, lang)}".strip(), action="trip_draft", step="confirm_date", missing_count=0)
    # ready: open the review page with the draft; one pending confirmation (replaces any older one)
    d.awaiting = None
    D.save(redis_conn, user_id, conversation_id, d)
    pc = P.save(redis_conn, user_id, conversation_id, "create_trip", D.summary(d, lang))
    return AgentResult(f"{prefix} {READY_REPLY[lang]}".strip(),
                       ui_actions=[{"type": "open_review", "prefill": D.prefill(d)}],
                       action="trip_draft", step="ready", missing_count=0,
                       pending_confirmation={"id": pc["id"], "summary": pc["summary"]})


def update_draft(redis_conn, user_id: str, conversation_id: str, args: Dict[str, Any], lang: str) -> AgentResult:
    from voice import draft as D, pending as P
    d = D.load(redis_conn, user_id, conversation_id)
    prefix = ""
    if d is not None and args.get("start_new") is True:
        d = None
        prefix = REPLACED_NOTE[lang]
    had_pending = P.get(redis_conn, user_id, conversation_id) is not None
    if had_pending:
        P.clear(redis_conn, user_id, conversation_id)   # details changed: the summary must be confirmed again
    d = d or D.TripDraftState()
    res = D.apply_update(d, {k: v for k, v in args.items() if k != "start_new"}, lang, _draft_today())
    if res.problems:
        D.save(redis_conn, user_id, conversation_id, res.draft)
        r = AgentResult(" ".join(res.problems[:2]), action="trip_draft", step="ask",
                        missing_count=len(res.draft.missing_fields()), error_code="refused_value")
        return r
    if "destination" in res.changed and not prefix:
        name = (res.draft.destination or {}).get("name", "")
        length = f", {res.draft.days} din" if res.draft.days and lang != "en" else (f", {res.draft.days} days" if res.draft.days else "")
        prefix = f"{name}{length}."
    return draft_next(redis_conn, user_id, conversation_id, res.draft, lang, prefix)


def confirm_trip(redis_conn, user_id: str, conversation_id: str, lang: str, pending_id: Optional[str] = None) -> AgentResult:
    """
    The ONE confirm action, for voice "haan" and the Confirm button alike. Takes the pending confirmation once
    (a second confirm finds nothing) and tells the app to press Proceed on the review page: the wizard then
    saves the page's values through its own path (trips:create -> create_trip_for_user). Voice never creates
    a trip from its own copy of the draft.
    """
    from voice import draft as D, pending as P
    pc = P.take(redis_conn, user_id, conversation_id, pending_id)
    if not pc or pc.get("tool") != "create_trip":
        return AgentResult(NOTHING_TO_CONFIRM[lang], action="trip_confirm_none", error_code="no_pending")
    D.delete(redis_conn, user_id, conversation_id)
    return AgentResult(CONFIRMED_REPLY[lang], ui_actions=[{"type": "submit_review"}], action="trip_confirm", step="confirmed")


def cancel_trip(redis_conn, user_id: str, conversation_id: str, lang: str) -> AgentResult:
    from voice import draft as D, pending as P
    P.clear(redis_conn, user_id, conversation_id)
    D.delete(redis_conn, user_id, conversation_id)
    return AgentResult(CANCELLED_REPLY[lang], action="trip_cancel", step="cancelled")


def _decide(tool_calls: List[Dict[str, Any]], content: Optional[str], lang: str, has_trip: bool,
            user_id: Optional[str] = None, trip: Optional[TripInfo] = None,
            conversation_id: Optional[str] = None, redis_conn=None) -> AgentResult:
    """Check the model's choice and run the tool. user_id comes from the session, never from the model."""
    call = next((c for c in tool_calls if c.get("name") in TOOL_NAMES), None)
    if call is None:
        if tool_calls:  # a tool we don't offer
            names = ",".join(str(tc.get("name")) for tc in tool_calls)[:100]
            return AgentResult(pages.WHICH_PAGE_REPLY[lang], action="reply", error_code="unknown_tool",
                               error_detail=f"model called a tool we don't offer: {names}")
        text = trim_sentences(content or "")
        # The model sometimes says the fixed lines as text instead of calling cant_help.
        if _norm_text(text) in {_norm_text(v) for v in DECLINE_REPLY.values()} or "sirf aapki trip" in text.lower():
            return AgentResult(DECLINE_REPLY[lang], action="decline")
        if _norm_text(text) in {_norm_text(v) for v in UNCLEAR_REPLY.values()}:
            return AgentResult(UNCLEAR_REPLY[lang], action="unclear")
        return AgentResult(text or pages.WHICH_PAGE_REPLY[lang], action="reply")

    name, args = call["name"], call.get("arguments") or {}
    if not isinstance(args, dict):
        return AgentResult(FALLBACK_REPLY, action="error", error_code="bad_tool_args",
                           error_detail=f"tool {name}: arguments were not an object")
    if name == "navigate":
        return _navigate(args, lang, has_trip)
    if name == "cant_help":
        if args.get("reason") == "unclear":
            return AgentResult(UNCLEAR_REPLY[lang], action="unclear")
        return AgentResult(DECLINE_REPLY[lang], action="decline")

    if name in ("update_trip_draft", "cancel_trip_draft"):
        if not user_id or not conversation_id or redis_conn is None:
            return AgentResult(FALLBACK_REPLY, action="error", error_code="no_user",
                               error_detail=f"trip draft needs a signed-in user, a conversation id and Redis "
                                            f"(user={bool(user_id)} conversation={bool(conversation_id)} "
                                            f"redis={redis_conn is not None})")
        if name == "cancel_trip_draft":
            return cancel_trip(redis_conn, user_id, conversation_id, lang)
        return update_draft(redis_conn, user_id, conversation_id, args, lang)

    from voice.tools import lookups
    if name == "search_places":
        return _from_tool(lookups.search_place(str(args.get("query") or ""), lang, show=args.get("show") is not False))
    if name == "get_weather":
        return _from_tool(lookups.get_weather(args.get("place"), args.get("day"), lang, user_id=user_id,
                                              trip_id=trip.id if trip else None))
    if not user_id:
        return AgentResult(FALLBACK_REPLY, action="error", error_code="no_user",
                           error_detail=f"tool {name} needs a signed-in user; the voice socket had no user id")
    if name == "list_my_trips":
        return _from_tool(lookups.list_my_trips(user_id, lang, include_past=args.get("include_past") is True))
    if name == "open_trip":
        return _from_tool(lookups.open_trip(user_id, lang, name_or_destination=args.get("name_or_destination"),
                                            month=args.get("month"), which=args.get("which")))
    # answer_question
    from tour_guide_service import voice_answer
    ans = voice_answer(str(args.get("question") or "")[:500], lang, user_id=user_id,
                       trip_id=trip.id if trip else None, place=args.get("place"),
                       facts=args.get("facts") if isinstance(args.get("facts"), bool) else None)
    if ans["status"] == "ok":
        code = None if ans["source"] == "gemini_grounded" else f"answered_by_{ans['source']}:{ans.get('fallback_code')}"
        return AgentResult(ans["spoken"], action="answer", error_code=code, note=ans.get("note"))
    if ans["status"] == "declined":
        return AgentResult(ans["spoken"], action="decline", error_code="cost_guard")
    if ans["status"] == "no_facts":
        return AgentResult(ans["spoken"], action="answer", error_code=f"no_facts:{ans.get('fallback_code')}")
    return AgentResult(ANSWER_FAILED[lang], action="answer", error_code=f"answer_failed:{ans.get('fallback_code')}",
                       error_detail=f"answer tool failed: status={ans.get('status')} code={ans.get('fallback_code')}")


def run_agent(transcript: str, stt_language: Optional[str], *, user_id: str, conversation_id: str,
              screen: Optional[str], trip: Optional[TripInfo], redis_conn=None) -> AgentResult:
    """Blocking (HTTP): call from a threadpool. Never raises."""
    from groq_client import GroqError, GroqRateLimited, GroqTransient, groq_chat_tools

    lang = template_language(stt_language, transcript)
    if redis_conn is None:
        from redis_client import redis_conn as _r
        redis_conn = _r

    started = time.perf_counter()
    llm_done: Optional[float] = None
    used_llm = False
    from voice import draft as D, pending as P
    confirm_pending = P.get(redis_conn, user_id, conversation_id)
    draft_state = D.load(redis_conn, user_id, conversation_id)
    said = yes_or_no(transcript)
    pending = pop_pending(redis_conn, user_id, conversation_id)
    answer_to_pending = said if pending else None
    result: Optional[AgentResult] = None

    if confirm_pending and said == "yes":
        # "haan" to the Confirm card: same action as the Confirm button.
        result = confirm_trip(redis_conn, user_id, conversation_id, lang)
    elif confirm_pending and said == "no":
        result = cancel_trip(redis_conn, user_id, conversation_id, lang)
    elif draft_state is not None and draft_state.awaiting == "date" and said == "yes":
        draft_state.dates_confirmed = True     # set only here, by code, after the read-back
        result = draft_next(redis_conn, user_id, conversation_id, draft_state, lang)
    elif draft_state is not None and draft_state.awaiting == "date" and said == "no":
        draft_state.start_date = draft_state.end_date = None
        draft_state.days = None
        draft_state.dates_confirmed = False
        draft_state.awaiting = None
        D.save(redis_conn, user_id, conversation_id, draft_state)
        result = AgentResult(DATE_AGAIN[lang], action="trip_draft", step="ask",
                             missing_count=len(draft_state.missing_fields()))
    elif draft_state is not None and said == "no" and _norm_text(transcript).startswith("cancel"):
        result = cancel_trip(redis_conn, user_id, conversation_id, lang)

    if result is not None:
        pass
    elif answer_to_pending == "yes":
        # "Taj Mahal kahan hai?" -> "... Map par dikhaun?" -> "haan": run the kept map actions, no LLM call.
        name = next((a.get("name") for a in pending if a.get("type") == "map_focus"), "")
        result = AgentResult({"hi": f"{name}: map par dikha diya.", "en": f"Showing {name} on the map."}[lang],
                             ui_actions=pending, action="map_focus")
    elif answer_to_pending == "no":
        result = AgentResult(OK_NO_REPLY[lang], action="reply")
    elif is_garbled(transcript):
        result = AgentResult(UNCLEAR_REPLY[lang], action="unclear", error_code="no_words")
    else:
        messages: List[Dict[str, Any]] = [{"role": "system", "content": build_system_prompt(
            screen, trip, draft_line=_draft_line(draft_state))}]
        messages += load_memory(redis_conn, user_id, conversation_id)
        messages.append({"role": "user", "content": transcript})
        used_llm = True
        try:
            try:
                answer = groq_chat_tools(messages, TOOLS, tool_choice="auto", temperature=0.2,
                                         timeout=LLM_TIMEOUT_SECONDS, reasoning_effort="low")
            except GroqTransient:
                # e.g. 400 tool_use_failed: the model's tool call didn't validate. One retry.
                answer = groq_chat_tools(messages, TOOLS, tool_choice="auto", temperature=0.2,
                                         timeout=LLM_TIMEOUT_SECONDS, reasoning_effort="low")
            llm_done = time.perf_counter()
            result = _decide(answer["tool_calls"], answer["content"], lang, has_trip=trip is not None,
                             user_id=user_id, trip=trip, conversation_id=conversation_id, redis_conn=redis_conn)
            if confirm_pending and not result.action.startswith("trip_"):
                P.clear(redis_conn, user_id, conversation_id)   # a new topic cancels the pending confirmation
        # Groq errors carry status + provider code only (never the message, which can quote the user).
        except GroqRateLimited as err:
            logger.warning("[VOICE AGENT] Groq rate limit: %s", err)
            result = AgentResult(FALLBACK_REPLY, action="error", error_code="rate_limited",
                                 error_detail=str(err)[:200])
        except GroqTransient as err:
            logger.warning("[VOICE AGENT] Groq failed twice: %s", err)
            result = AgentResult(FALLBACK_REPLY, action="error", error_code="groq_transient_twice",
                                 error_detail=str(err)[:200])
        except GroqError as err:
            logger.warning("[VOICE AGENT] Groq error: %s", err)
            result = AgentResult(FALLBACK_REPLY, action="error", error_code="groq_error",
                                 error_detail=str(err)[:200])
        except Exception as err:
            # Unexpected (a bug, or a tool/lookup failing): the full traceback goes to the server log.
            logger.exception("[VOICE AGENT] turn crashed in the agent")
            result = AgentResult(FALLBACK_REPLY, action="error", error_code=type(err).__name__,
                                 error_detail=f"{type(err).__name__}: {str(err)[:200]}")
    ended = time.perf_counter()
    result.llm_ms = int(((llm_done or ended) - started) * 1000) if used_llm else 0
    result.tool_ms = int((ended - llm_done) * 1000) if llm_done else (0 if used_llm else int((ended - started) * 1000))

    if result.pending_actions:
        save_pending(redis_conn, user_id, conversation_id, result.pending_actions)
    if result.action != "error":
        save_turn(redis_conn, user_id, conversation_id, transcript, result.reply_text)
    logger.info("[VOICE AGENT] action=%s%s%s llm_ms=%s tool_ms=%s%s%s%s", result.action,
                f" step={result.step}" if result.step else "",
                f" missing={result.missing_count}" if result.missing_count is not None else "",
                result.llm_ms, result.tool_ms, f" code={result.error_code}" if result.error_code else "",
                f" detail={result.error_detail}" if result.error_detail else "",
                f" google_calls={result.google_calls}" if result.google_calls is not None else "")
    return result
