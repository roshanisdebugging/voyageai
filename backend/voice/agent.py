"""
The voice agent ("the mind"), voicefirst.md steps 2-3. ONE Groq call per turn decides; tools:
navigate (step 2), answer_question, search_places, list_my_trips, open_trip (step 3, read-only).

transcript + memory + current state -> Groq (function calling) -> our code checks the call and runs the
tool (voice/pages.py, voice/tools/lookups.py, tour_guide_service.voice_answer) -> (reply_text, ui_actions).
The model never touches data and never supplies a trip ID: trips are looked up by the session's user.
Logs carry the action, timings and error codes only, never the user's words or the reply.

Memory: Redis voice:mem:{user_id}:{conversation_id}, last 10 turns (user + assistant), 30-minute
TTL refreshed each turn, deleted on end_session.
"""
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from voice import pages

logger = logging.getLogger("voice")

MEMORY_TURNS = 10
MEMORY_TTL_SECONDS = 30 * 60
LLM_TIMEOUT_SECONDS = 8
FALLBACK_REPLY = "Abhi samajh nahi paaya, phir se boliye."

SYSTEM_PROMPT = """You are VoyageAI's voice assistant inside a travel app for Indian users.

How to reply:
- Reply in the language the user spoke: Hinglish in Roman script, Hindi, or English.
- Your reply is spoken aloud: at most 2 short sentences, no lists, no emojis.

What you can do (call exactly one tool when it fits):
- navigate: open a page. "Plan a new trip" / "nayi trip banani hai" -> navigate to plan_trip at once,
  do not ask for details. "Itinerary kholo" without a day -> navigate to itinerary, do not ask which day.
- answer_question: any question about places, timings, tickets, food, weather, culture, transport or
  travel tips. ("Where can I eat" / "khana kahan milega" nearby -> navigate to food instead.) Do NOT answer these from memory; always call answer_question.
- search_places: the user wants to SEE where a place is: "Hawa Mahal dikhao", "where is Amber Fort",
  "Qutub Minar kahan hai" (kahan hai / where is = show it on the map, not a question).
  Only for a NAMED place. General "ghoomne ki jagah dikhao" / things to do -> navigate to explore.
- list_my_trips: the user asks which trips they have ("meri trips kaun si hain"); past trips only when
  they say purani / past.
- open_trip: the user wants to open a specific trip by name, destination, month, or next/current/last
  ("Goa wali trip kholo", "agli trip kholo"). If you asked "which one?" and the user answers with a
  month, call open_trip again with that month.
- If the request is unclear, ask ONE short question instead of guessing.
- If the user asks for something unrelated to travel (jokes, cricket, coding), politely decline:
  "Main sirf aapki trip mein madad kar sakta hoon." Do not call a tool.
- Never invent pages, routes, trips or facts.

Current state:
- Today (India): {today}
- User is on page: {screen}
- Open trip: {trip_line}"""

NAVIGATE_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "navigate",
        "description": "Open a page of the app. Pages: " + "; ".join(f"{p}: {m}" for p, m in pages.MEANINGS.items()) + ".",
        "parameters": {
            "type": "object",
            "properties": {
                "page": {"type": "string", "enum": pages.PAGES},
                "day": {"type": ["integer", "null"], "minimum": pages.MIN_DAY, "maximum": pages.MAX_DAY,
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
        "description": "Answer a travel question (places, timings, tickets, food, weather, culture, transport, tips) "
                       "with the tour guide. Use for every such question; never answer them yourself.",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The user's question, cleaned up, in their language."},
                "place": {"type": ["string", "null"], "description": "The place it is about, if any."},
            },
            "required": ["question"],
        },
    },
}
SEARCH_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "search_places",
        "description": "Show a place in India on the map (the user wants to see where it is).",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "The place name, e.g. 'Hawa Mahal Jaipur'."}},
            "required": ["query"],
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
            "properties": {"include_past": {"type": ["boolean", "null"], "description": "true only if the user asks for past/old (purani) trips."}},
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
                "name_or_destination": {"type": ["string", "null"], "description": "Trip name or destination, e.g. 'Goa'."},
                "month": {"type": ["string", "null"], "description": "Month of the trip start, e.g. 'December' or '12'."},
                "which": {"type": ["string", "null"], "enum": ["next", "current", "last", None]},
            },
        },
    },
}
TOOLS = [NAVIGATE_TOOL, ANSWER_TOOL, SEARCH_TOOL, LIST_TRIPS_TOOL, OPEN_TRIP_TOOL]
TOOL_NAMES = {t["function"]["name"] for t in TOOLS}
ANSWER_FAILED = {"hi": "Abhi jawab nahi mil paaya, thodi der mein phir poochhiye.",
                 "en": "I couldn't get an answer right now, please ask again in a moment."}


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
    action: str = "reply"            # "navigate:<page>" | "answer" | "map_focus" | "list_trips" | "open_trip" | "reply" | "error"
    llm_ms: int = 0                   # the deciding Groq call
    tool_ms: int = 0                  # the tool (answer_question: cost guard + Gemini/Groq; look-ups: Google/DB)
    error_code: Optional[str] = None  # for logs only


def template_language(stt_language: Optional[str]) -> str:
    """STT language -> template language: hi/ur -> "hi", en -> "en", anything else -> "hi"."""
    lang = (stt_language or "").strip().lower()
    return "en" if lang == "en" else "hi"


def build_system_prompt(screen: Optional[str], trip: Optional[TripInfo], today: Optional[str] = None) -> str:
    trip_line = (f"{trip.title} ({trip.start_date or '?'} to {trip.end_date or '?'})" if trip else "none")
    if today is None:
        from datetime import datetime, timedelta, timezone
        today = datetime.now(timezone(timedelta(hours=5, minutes=30))).strftime("%A %d %B %Y")
    return SYSTEM_PROMPT.format(screen=(screen or "unknown")[:120], trip_line=trip_line, today=today)


def trim_sentences(text: str, limit: int = 2) -> str:
    """Spoken replies stay short: keep the first `limit` sentences."""
    text = re.sub(r"\s+", " ", (text or "").strip())
    parts = re.split(r"(?<=[.!?।])\s+", text)
    return " ".join(parts[:limit]).strip()


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
    except Exception:
        return []


def save_turn(redis_conn, user_id: str, conversation_id: str, user_text: str, reply_text: str) -> None:
    try:
        history = load_memory(redis_conn, user_id, conversation_id)
        history += [{"role": "user", "content": user_text}, {"role": "assistant", "content": reply_text}]
        history = history[-MEMORY_TURNS * 2:]
        redis_conn.setex(_mem_key(user_id, conversation_id), MEMORY_TTL_SECONDS, json.dumps(history))
    except Exception as err:
        logger.warning("[VOICE AGENT] memory save failed: %s", type(err).__name__)


def clear_memory(redis_conn, user_id: str, conversation_id: Optional[str] = None) -> None:
    """end_session: the conversation's memory (or all of the user's voice memory) is deleted."""
    try:
        if conversation_id:
            redis_conn.delete(_mem_key(user_id, conversation_id))
        else:
            for key in redis_conn.scan_iter(f"voice:mem:{user_id}:*"):
                redis_conn.delete(key)
    except Exception as err:
        logger.warning("[VOICE AGENT] memory clear failed: %s", type(err).__name__)


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
    return AgentResult(r.reply_text, ui_actions=list(r.ui_actions), action=r.action, error_code=r.error_code)


def _decide(tool_calls: List[Dict[str, Any]], content: Optional[str], lang: str, has_trip: bool,
            user_id: Optional[str] = None, trip: Optional[TripInfo] = None) -> AgentResult:
    """Check the model's choice and run the tool. user_id comes from the session, never from the model."""
    call = next((c for c in tool_calls if c.get("name") in TOOL_NAMES), None)
    if call is None:
        if tool_calls:  # a tool we don't offer
            return AgentResult(pages.WHICH_PAGE_REPLY[lang], action="reply", error_code="unknown_tool")
        return AgentResult(trim_sentences(content or "") or pages.WHICH_PAGE_REPLY[lang], action="reply")

    name, args = call["name"], call.get("arguments") or {}
    if not isinstance(args, dict):
        return AgentResult(FALLBACK_REPLY, action="error", error_code="bad_tool_args")
    if name == "navigate":
        return _navigate(args, lang, has_trip)

    from voice.tools import lookups
    if name == "search_places":
        return _from_tool(lookups.search_place(str(args.get("query") or ""), lang))
    if not user_id:
        return AgentResult(FALLBACK_REPLY, action="error", error_code="no_user")
    if name == "list_my_trips":
        return _from_tool(lookups.list_my_trips(user_id, lang, include_past=args.get("include_past") is True))
    if name == "open_trip":
        return _from_tool(lookups.open_trip(user_id, lang, name_or_destination=args.get("name_or_destination"),
                                            month=args.get("month"), which=args.get("which")))
    # answer_question
    from tour_guide_service import voice_answer
    ans = voice_answer(str(args.get("question") or "")[:500], lang, user_id=user_id,
                       trip_id=trip.id if trip else None, place=args.get("place"))
    if ans["status"] == "ok":
        return AgentResult(ans["spoken"], action="answer", error_code=None if ans["source"] == "gemini" else "answered_by_groq")
    if ans["status"] == "declined":
        return AgentResult(ans["spoken"], action="answer", error_code="declined")
    return AgentResult(ANSWER_FAILED[lang], action="answer", error_code="answer_failed")


def run_agent(transcript: str, stt_language: Optional[str], *, user_id: str, conversation_id: str,
              screen: Optional[str], trip: Optional[TripInfo], redis_conn=None) -> AgentResult:
    """Blocking (HTTP): call from a threadpool. Never raises."""
    from groq_client import GroqError, GroqRateLimited, groq_chat_tools

    lang = template_language(stt_language)
    if redis_conn is None:
        from redis_client import redis_conn as _r
        redis_conn = _r

    messages: List[Dict[str, Any]] = [{"role": "system", "content": build_system_prompt(screen, trip)}]
    messages += load_memory(redis_conn, user_id, conversation_id)
    messages.append({"role": "user", "content": transcript})

    started = time.perf_counter()
    llm_done = None
    try:
        answer = groq_chat_tools(messages, TOOLS, tool_choice="auto", temperature=0.2,
                                 timeout=LLM_TIMEOUT_SECONDS, reasoning_effort="low")
        llm_done = time.perf_counter()
        result = _decide(answer["tool_calls"], answer["content"], lang, has_trip=trip is not None,
                         user_id=user_id, trip=trip)
    except GroqRateLimited:
        result = AgentResult(FALLBACK_REPLY, action="error", error_code="rate_limited")
    except GroqError as err:
        code = "bad_tool_args" if "arguments" in str(err) else "groq_error"
        result = AgentResult(FALLBACK_REPLY, action="error", error_code=code)
    except Exception as err:
        result = AgentResult(FALLBACK_REPLY, action="error", error_code=type(err).__name__)
    ended = time.perf_counter()
    result.llm_ms = int(((llm_done or ended) - started) * 1000)
    result.tool_ms = int((ended - llm_done) * 1000) if llm_done else 0

    if result.action != "error":
        save_turn(redis_conn, user_id, conversation_id, transcript, result.reply_text)
    logger.info("[VOICE AGENT] action=%s llm_ms=%s tool_ms=%s%s", result.action, result.llm_ms, result.tool_ms,
                f" code={result.error_code}" if result.error_code else "")
    return result
