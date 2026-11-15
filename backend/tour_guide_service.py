"""
VoyageAI tour guide / concierge service.

Request flow (process_concierge_message):
    1. Cost guard      -> bounded intent classification gates paid answer generation
    2. Pick prompt     -> normal travel prompt, or emergency prompt
    3. Build context   -> location anchor + last few chat messages
    4. Call LLM        -> Tier A (grounded) -> Tier B (plain) -> Tier C (REST)
    5. Parse reply     -> split text / chips / card
    6. Save to DB      -> user message + assistant reply
"""

import asyncio
import json
import logging
import math
import os
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv
from sqlalchemy import text

from cost_guard import evaluate_cost_guards
from database import engine

load_dotenv()
log = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Gemini SDK setup
# --------------------------------------------------------------------------
try:
    import google.generativeai as genai

    _API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if _API_KEY:
        genai.configure(api_key=_API_KEY)
except ImportError:
    genai = None
    _API_KEY = None

# Verified model candidates list with env override support
import os

_env_model = os.getenv("GEMINI_MODEL")
_env_models = os.getenv("GEMINI_MODELS")
_raw_candidates = []
if _env_model and _env_model.strip():
    _raw_candidates.append(_env_model.strip())
if _env_models and _env_models.strip():
    _raw_candidates.extend([m.strip() for m in _env_models.split(",") if m.strip()])
else:
    _raw_candidates.extend([
        "gemini-3.5-flash-lite",
        "gemini-flash-lite-latest",
        "gemini-3.8-flash",
        "gemini-3.7-flash",
    ])
MODEL_CANDIDATES = list(dict.fromkeys([m for m in _raw_candidates if m]))

# cost_guard returns this string when the message is a medical/hygiene need.
ESSENTIAL_GATE = "PASSED_ESSENTIAL_NEED"

# --------------------------------------------------------------------------
# Prompts
# --------------------------------------------------------------------------
JARVIS_SYSTEM_PROMPT = """
You are VoyageAI's Jarvis-grade Travel Concierge.
You provide verified, real-time insider guidance and proactive assistance.

RULES:
1. Speak concisely (2 to 4 crisp sentences). Natural Hinglish or English based on user query language.
2. If recommending an activity or sight, explain the ground reality: best timing or any heads-up (closures, peak queues, ticket hacks).
3. If recommending a concrete spot to add in Trip Mode, append a structured card at the very end:
<<<CARD:{"id": "rec_id_1", "title": "Place Name", "category": "Food/Sight/Stay", "location": "Area", "duration": "1.5h", "cost": 300, "heads_up": "Live warning or None"}>>>
4. Always provide 2-3 short contextual follow-up chips at the end:
<<<CHIPS:["Check timings", "Alternative spot", "Show on Map"]>>>
5. Under NO circumstances output markdown code blocks (```). You are strictly a travel companion.
"""

EMERGENCY_SYSTEM_PROMPT = """
You are VoyageAI's Emergency & Essentials Travel Assistant.
The traveler has an urgent, hygiene, or medical requirement (e.g. sanitary pads, medicine, doctor, clinic, fever, period cramps, police, lost items).

RULES:
1. Be immediate, empathetic, calm, and 100% practical. No travel fluff or poetic descriptions.
2. Directly advise nearest action: mention 24x7 pharmacies, Apollo/MedPlus/local chemist availability, quick delivery apps (Blinkit, Zepto, Swiggy Instamart) if applicable, or local hospital emergency desk.
3. If nearby emergency places data is provided in context, use those exact names and areas.
4. Keep the response crisp (2-3 sentences).
5. Output relevant emergency follow-up chips at the end:
<<<CHIPS:["Locate on Map", "Quick Delivery", "Emergency Helpline"]>>>
6. Do NOT output markdown code blocks (```).
"""

CODE_BLOCK_DEFLECTION = (
    "Safar mein coding chhoriye dost! Main sirf travel, sightseeing aur local "
    "experiences mein madad karta hoon. Kahan chalna hai bataiye?"
)


# --------------------------------------------------------------------------
# Parsing the LLM output
# --------------------------------------------------------------------------
def _extract_json_block(tag: str, raw: str):
    """Find <<<TAG:{...}>>> in raw and return the parsed JSON, or None if missing/invalid."""
    match = re.search(rf"<<<{tag}:(.*?)>>>", raw, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except Exception:
        return None


def parse_blocks(raw_text: str) -> Tuple[str, List[str], Optional[dict]]:
    """Split the model reply into (clean_text, chips, card)."""
    chips = _extract_json_block("CHIPS", raw_text) or []
    card = _extract_json_block("CARD", raw_text)
    if not isinstance(chips, list):
        chips = []
    if not isinstance(card, dict):
        card = None
    clean_text = re.sub(r"<<<.*?>>>", "", raw_text, flags=re.DOTALL).strip()
    return clean_text, chips, card


# --------------------------------------------------------------------------
# Database helpers
# --------------------------------------------------------------------------
def _is_guest(user_id: Optional[str]) -> bool:
    return not user_id or str(user_id).startswith("guest_")


def persist_message(
    user_id: str,
    role: str,
    content: str,
    mode: str,
    trip_id: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> None:
    """Insert one chat row. Refuses guests; swallows DB errors so chat never breaks."""
    if _is_guest(user_id):
        raise ValueError("Unauthorized: Cannot persist message without authenticated user_id")
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO chat_messages (id, user_id, trip_id, role, content, mode, metadata)
                    VALUES (:id, :user_id, :trip_id, :role, :content, :mode, CAST(:meta AS JSONB))
                    """
                ),
                {
                    "id": f"msg_{uuid.uuid4().hex[:12]}",
                    "user_id": user_id,
                    "trip_id": trip_id,
                    "role": role,
                    "content": content,
                    "mode": mode or "local",
                    "meta": json.dumps(metadata or {}),
                },
            )
    except Exception as e:
        log.error("DB log error: %s", e)


save_chat_message = persist_message  # backward-compat alias


def _save_exchange(user_id, message, reply, mode, trip_id, payload) -> None:
    """Save the user's message and the assistant's reply. Guests are skipped, not crashed on."""
    if _is_guest(user_id):
        return
    persist_message(user_id, "user", message, mode, trip_id)
    persist_message(user_id, "assistant", reply, mode, trip_id, payload)


def fetch_chat_history(
    user_id: str, trip_id: Optional[str] = None, limit: int = 100, db=None
) -> List[Dict[str, Any]]:
    """Return the LATEST `limit` messages, oldest-first (chronological)."""
    if not user_id:
        return []

    sql = """
        SELECT id, role, content, mode, trip_id, metadata, created_at
        FROM chat_messages
        WHERE user_id = :user_id
    """
    params: Dict[str, Any] = {"user_id": user_id, "limit": limit}
    if trip_id:
        sql += " AND trip_id = :trip_id"
        params["trip_id"] = trip_id

    # Take the newest n, then reverse back into chronological order below
    sql += " ORDER BY created_at DESC LIMIT :limit"

    try:
        with engine.connect() as conn:
            rows = conn.execute(text(sql), params).mappings().all()
    except Exception as err:
        log.warning("History fetch failed: %s", err)
        return []

    history = []
    for r in rows:
        meta = r.get("metadata") or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        created = r.get("created_at")
        history.append(
            {
                "id": str(r.get("id")),
                "role": r.get("role"),
                "content": r.get("content"),
                "mode": r.get("mode"),
                "trip_id": r.get("trip_id"),
                "metadata": meta,
                "created_at": created.isoformat() if hasattr(created, "isoformat") else str(created),
            }
        )
    history.reverse()
    return history


# --------------------------------------------------------------------------
# LLM calling (three tiers)
# --------------------------------------------------------------------------
def _build_model(name: str, system_prompt: str, grounded: bool, temperature: float):
    """Create an SDK model. grounded=True attaches Google Search for live info."""
    if not (genai and hasattr(genai, "GenerativeModel")):
        return None
    kwargs: Dict[str, Any] = {
        "model_name": name,
        "system_instruction": system_prompt,
        "generation_config": {"temperature": temperature, "max_output_tokens": 1024},
    }
    if grounded:
        try:
            return genai.GenerativeModel(tools=["google_search_retrieval"], **kwargs)
        except Exception:
            pass
    try:
        return genai.GenerativeModel(**kwargs)
    except Exception as e:
        log.warning("Could not build model %s: %s", name, e)
        return None


def get_grounded_model(m_name: str, system_prompt: str = JARVIS_SYSTEM_PROMPT):
    return _build_model(m_name, system_prompt, grounded=True, temperature=0.4)


def get_plain_model(m_name: str, system_prompt: str = JARVIS_SYSTEM_PROMPT):
    return _build_model(m_name, system_prompt, grounded=False, temperature=0.4)


def _try_sdk(prompt: str, system_prompt: str, grounded: bool, temperature: float) -> Optional[str]:
    """Walk MODEL_CANDIDATES with the SDK; return first non-empty text, else None."""
    label = "grounded" if grounded else "plain"
    for name in MODEL_CANDIDATES:
        model = _build_model(name, system_prompt, grounded, temperature)
        if not model:
            continue
        try:
            resp = model.generate_content(prompt)
            if resp and resp.text:
                return resp.text.strip()
        except Exception as e:
            log.warning("[%s] model %s failed: %s", label, name, e)
    return None


def _try_rest(prompt: str, system_prompt: str, temperature: float) -> Optional[str]:
    """Last resort: call the Gemini REST API directly."""
    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key or not key.strip():
        return None
    body = {
        "contents": [{"parts": [{"text": f"{system_prompt}\n\n{prompt}"}]}],
        "generationConfig": {"temperature": temperature, "maxOutputTokens": 1024},
    }
    for name in MODEL_CANDIDATES:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{name}:generateContent"
        try:
            res = requests.post(url, json=body, headers={"x-goog-api-key": key}, timeout=12.0)
            if res.status_code != 200:
                continue
            candidates = res.json().get("candidates") or []
            parts = (candidates[0].get("content") or {}).get("parts") if candidates else None
            if parts and "text" in parts[0]:
                return parts[0]["text"].strip()
        except Exception as e:
            log.warning("[rest] model %s failed: %s", name, e)
    return None


def _generate_reply(prompt: str, system_prompt: str, is_essential: bool) -> Optional[str]:
    """Tier A (live search) -> Tier B (no search) -> Tier C (raw REST). None if all fail."""
    temp = 0.2 if is_essential else 0.4
    return (
        _try_sdk(prompt, system_prompt, grounded=True, temperature=temp)
        or _try_sdk(prompt, system_prompt, grounded=False, temperature=temp)
        or _try_rest(prompt, system_prompt, temp)
    )


# --------------------------------------------------------------------------
# Prompt context
# --------------------------------------------------------------------------
def _nearby_pharmacy_note(lat: Optional[float], lng: Optional[float]) -> str:
    if lat is None or lng is None:
        return ""
    try:
        from places import get_progressive_nearby_places
        places = get_progressive_nearby_places(lat, lng, "pharmacy")[:3]
        names = [p.get("name", "Local Chemist") for p in places]
        return f" | Nearby verified stores: {', '.join(names)}" if names else ""
    except Exception:
        return ""


def _build_context_anchor(is_essential: bool, mode: str, dest: Optional[str], lat: Optional[float], lng: Optional[float]) -> str:
    """One bracketed line telling the LLM where the user is / what mode we're in."""
    if is_essential:
        return (
            f"[URGENT MEDICAL/ESSENTIAL MODE | User Location: lat={lat}, lng={lng}"
            f"{_nearby_pharmacy_note(lat, lng)}]"
        )
    if mode == "trip":
        return f"[Active Trip Mode | Destination: {dest or 'Planned Trip'} | STRICT: DO NOT consider current user GPS coordinates]"
    if lat is not None and lng is not None:
        return f"[Local Mode | User Coordinates: lat={lat:.5f}, lng={lng:.5f}]"
    return "[Local Mode | Current location unknown, suggest asking destination if broad]"


def _build_history_block(items: List[Dict[str, Any]], window: int = 5, max_chars: int = 250) -> str:
    """Last `window` messages, each truncated, so the prompt stays concise."""
    lines = []
    for item in items[-window:]:
        who = "Traveler" if item.get("role") == "user" else "Assistant"
        lines.append(f"{who}: {str(item.get('content', ''))[:max_chars]}")
    return ("Recent Conversation Snippet:\n" + "\n".join(lines) + "\n\n") if lines else ""


# --------------------------------------------------------------------------
# Main entry point
# --------------------------------------------------------------------------
def process_concierge_message(
    user_id: str,
    message: str,
    mode: str = "local",
    trip_id: Optional[str] = None,
    destination_name: Optional[str] = None,
    trip_destination: Optional[str] = None,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    user_lat: Optional[float] = None,
    user_lng: Optional[float] = None,
    recent_history: Optional[List[Dict[str, str]]] = None,
    db=None,
) -> Dict[str, Any]:
    dest = destination_name or trip_destination
    eff_lat = lat if lat is not None else user_lat
    eff_lng = lng if lng is not None else user_lng

    # 1. Cost guard: unmatched or unavailable classification asks for clarification.
    should_call_llm, gate_reason, deflection = evaluate_cost_guards(message)
    if not should_call_llm:
        payload = {
            "reply": deflection,
            "chips": ["Must-try street food", "Top sights today", "Hidden gems"],
            "card": None,
            "mode": mode,
            "gate": gate_reason,
        }
        _save_exchange(user_id, message, deflection, mode, trip_id, payload)
        return payload

    # 2. Choose prompt
    is_essential = gate_reason == ESSENTIAL_GATE
    system_prompt = EMERGENCY_SYSTEM_PROMPT if is_essential else JARVIS_SYSTEM_PROMPT

    # 3. Build context
    anchor = _build_context_anchor(is_essential, mode, dest, eff_lat, eff_lng)

    if recent_history is None:
        rows = fetch_chat_history(user_id, trip_id=trip_id if mode == "trip" else None, limit=6)
        recent_history = [{"role": r["role"], "content": r["content"]} for r in rows]

    prompt = f"{anchor}\n\n{_build_history_block(recent_history)}Traveler current query: {message}"

    # 4. Call LLM
    raw_text = _generate_reply(prompt, system_prompt, is_essential)

    if not raw_text:
        log.error("All LLM tiers failed")
        if is_essential:
            reply = "Aapke paas ke medical store ya 24x7 pharmacy ke liye Google Maps check karein ya Blinkit/Instamart se order karein."
            chips = ["Locate nearby pharmacy", "Nearest hospital", "Retry"]
        else:
            reply = "Connection thoda slow chal raha hai dost. Ek baar query dobara bhej kar dekho!"
            chips = ["Retry now", "Nearby food", "Top sights"]
        return {
            "reply": reply,
            "chips": chips,
            "card": None,
            "mode": mode,
            "gate": gate_reason,
            "error": "LLM_TOTAL_FAILURE"
        }

    # 5. Parse reply
    clean_text, chips, card = parse_blocks(raw_text)
    if "```" in clean_text:
        clean_text = CODE_BLOCK_DEFLECTION

    default_chips = ["Locate on Map", "Quick Delivery"] if is_essential else ["Show map", "Nearby food", "Timing tips"]
    payload = {
        "reply": clean_text,
        "chips": chips or default_chips,
        "card": card,
        "mode": mode,
        "gate": gate_reason,
        "error": None,
    }

    # 6. Persist exchange
    _save_exchange(user_id, message, clean_text, mode, trip_id, payload)
    return payload


async def handle_tour_guide_chat(
    user_id: str,
    message: str,
    mode: str,
    trip_id: Optional[str] = None,
    trip_destination: Optional[str] = None,
    user_lat: Optional[float] = None,
    user_lng: Optional[float] = None,
) -> Dict[str, Any]:
    return await asyncio.to_thread(
        process_concierge_message,
        user_id=user_id,
        message=message,
        mode=mode,
        trip_id=trip_id,
        destination_name=trip_destination,
        trip_destination=trip_destination,
        user_lat=user_lat,
        user_lng=user_lng,
    )


# --------------------------------------------------------------------------
# Legacy & auxiliary endpoints support
# --------------------------------------------------------------------------
def generate_tour_guide_response(
    messages: List[Dict[str, str]],
    place_context: Optional[Dict[str, Any]],
    nearby_places: List[Dict[str, Any]],
    user_location: Optional[Dict[str, float]],
    trip_context: Optional[Dict[str, Any]] = None,
    user_prefs: Optional[Dict[str, Any]] = None,
    mode: str = "local",
    user_id: str = "",
) -> Dict[str, Any]:
    if _is_guest(user_id):
        raise ValueError("Unauthorized: Cannot generate tour guide response without authenticated user_id")
    last_msg = messages[-1].get("text", "") if messages else ""
    dest_name = ((trip_context or {}).get("destination") or {}).get("name")
    return process_concierge_message(
        user_id,
        last_msg,
        mode,
        (trip_context or {}).get("id"),
        dest_name,
        lat=(user_location or {}).get("latitude"),
        lng=(user_location or {}).get("longitude"),
    )


def search_nearby_pois(lat: float, lng: float, radius_m: int = 5000, category: str = "all") -> List[Dict[str, Any]]:
    try:
        from places import get_progressive_nearby_places
        return get_progressive_nearby_places(lat, lng, radius=radius_m)
    except Exception as e:
        log.warning("Nearby POIs error: %s", e)
        return []


def fetch_and_cache_pois_task(lat: float, lng: float, radius_m: int = 5000, category: str = "all") -> List[Dict[str, Any]]:
    return search_nearby_pois(lat, lng, radius_m, category)


def generate_poi_story(place_name: str, category: str = "attraction", address: str = "") -> str:
    prompt = f"Share a brief, captivating 2-sentence cultural or historical highlight about {place_name} ({category}) in {address} for a traveler audio guide. No markdown, natural speech."
    reply = _generate_reply(prompt, JARVIS_SYSTEM_PROMPT, is_essential=False)
    if reply:
        clean, _, _ = parse_blocks(reply)
        return clean
    return f"{place_name} is one of the most prominent {category} spots in the area, offering a distinct glimpse into the local heritage and atmosphere."


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Real spherical distance calculation in meters."""
    r = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def rank_places(places, user_prefs=None, limit=10):
    return places[:limit] if places else []


def get_or_create_session(user_id):
    return {"user_id": user_id, "messages": []}


def should_refresh_nearby(session, lat, lng):
    return False


def resolve_active_place(req_place_id, message_text, session, nearby_places):
    return None


def add_message_to_session(session, role, text, place_id=None):
    pass


def fetch_nearby_places(lat, lng, radius=5000):
    return search_nearby_pois(lat, lng, radius)


def check_proactive_alert(session, lat, lng, places):
    return None


# --------------------------------------------------------------------------
# Voice mode (voicefirst.md step 3): short spoken answers
# --------------------------------------------------------------------------
VOICE_ANSWER_PROMPT = """
You are VoyageAI's travel guide answering by VOICE inside a travel app for India.

RULES:
1. {lang_rule}
2. Answer in at most 4 short sentences of under 15 words each. The FIRST TWO sentences must answer the
   question on their own, because only they are spoken aloud; the rest may add detail.
3. Plain spoken text only: no markdown, lists, headings, emojis, links, cards or chips.
4. Facts that change (timings, prices, closures): give what you know and say it may vary.
5. Only travel topics (places, food, timings, tickets, transport, weather, culture, safety).
   For anything else answer exactly: {decline}
"""
VOICE_LANG_RULE = {
    "hi": "Reply in natural Hinglish written in Roman script (Hindi words in English letters).",
    "en": "Reply in simple English.",
}
VOICE_DECLINE = {
    "hi": "Main sirf travel aur aapki trip mein madad kar sakta hoon.",
    "en": "I can only help with travel and your trip.",
}
VOICE_GROQ_NOTE = {"hi": "Details badal sakti hain.", "en": "Details may vary."}
VOICE_GEMINI_TIMEOUT = 5.0
VOICE_GROQ_TIMEOUT = 5.0

_MARKDOWN = re.compile(r"(\*\*|__|`|#+\s|^\s*[-*•]\s+|\[\d+\])", re.MULTILINE)


def _clean_spoken(raw: str) -> str:
    """Drop chips/cards/markdown/links so the text can be spoken."""
    text, _, _ = parse_blocks(raw or "")
    text = re.sub(r"https?://\S+", "", text)
    text = _MARKDOWN.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def _first_sentences(text: str, limit: int) -> str:
    parts = re.split(r"(?<=[.!?।])\s+", text.strip())
    return " ".join(parts[:limit]).strip()


def _voice_gemini(question: str, system_prompt: str) -> Optional[str]:
    """One grounded Gemini call (first model only, with a timeout): voice can't wait for the full tier walk."""
    if not MODEL_CANDIDATES:
        return None
    model = _build_model(MODEL_CANDIDATES[0], system_prompt, grounded=True, temperature=0.3)
    if not model:
        return None
    try:
        resp = model.generate_content(question, request_options={"timeout": VOICE_GEMINI_TIMEOUT})
        return resp.text.strip() if resp and resp.text else None
    except Exception as e:
        log.warning("[voice answer] gemini failed: %s", type(e).__name__)
        return None


def _voice_groq(question: str, system_prompt: str) -> Optional[str]:
    try:
        from groq_client import groq_chat
        return groq_chat([{"role": "system", "content": system_prompt}, {"role": "user", "content": question}],
                         temperature=0.3, timeout=VOICE_GROQ_TIMEOUT, max_completion_tokens=600, reasoning_effort="low")
    except Exception as e:
        log.warning("[voice answer] groq failed: %s", type(e).__name__)
        return None


def voice_answer(question: str, lang: str = "hi", user_id: Optional[str] = None,
                 trip_id: Optional[str] = None, place: Optional[str] = None) -> Dict[str, Any]:
    """
    Short spoken answer to a travel question. Gemini (grounded) first, Groq second (same rules, plus
    "details may vary"). The cost guard runs first and fails closed, as for every paid answer.
    The question and the full answer are saved to the user's Guide chat history (mode "voice").
    Returns {status: ok|declined|failed, spoken, full, source: gemini|groq|None}. Never raises.
    Logs carry the outcome only, never the question or the answer.
    """
    lang = lang if lang in VOICE_LANG_RULE else "hi"
    q = (question or "").strip()[:500]
    if place and place.strip() and place.strip().lower() not in q.lower():
        q = f"{q} ({place.strip()[:120]})"
    if not q:
        return {"status": "failed", "spoken": None, "full": None, "source": None}

    allowed, gate, _reply = evaluate_cost_guards(q)
    if not allowed:
        log.info("[voice answer] cost guard refused (%s)", gate)
        return {"status": "declined", "spoken": VOICE_DECLINE[lang], "full": None, "source": None}

    system_prompt = VOICE_ANSWER_PROMPT.format(lang_rule=VOICE_LANG_RULE[lang], decline=VOICE_DECLINE[lang])
    source, raw = "gemini", _voice_gemini(q, system_prompt)
    if not raw:
        source, raw = "groq", _voice_groq(q, system_prompt)
    full = _clean_spoken(raw or "")
    if not full:
        return {"status": "failed", "spoken": None, "full": None, "source": None}
    if source == "groq":
        full = f"{full} {VOICE_GROQ_NOTE[lang]}"
    spoken = _first_sentences(full, 2)
    if source == "groq" and VOICE_GROQ_NOTE[lang] not in spoken:
        spoken = f"{spoken} {VOICE_GROQ_NOTE[lang]}"

    if user_id and not _is_guest(user_id):
        try:
            persist_message(user_id, "user", q, "voice", trip_id, {"via": "voice"})
            persist_message(user_id, "assistant", full, "voice", trip_id, {"via": "voice", "source": source})
        except Exception as e:
            log.warning("[voice answer] history save failed: %s", type(e).__name__)
    return {"status": "ok", "spoken": spoken, "full": full, "source": source}
