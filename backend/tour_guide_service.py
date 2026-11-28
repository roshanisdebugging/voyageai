"""
VoyageAI tour guide / concierge service.

Request flow (process_concierge_message):
    1. Cost guard      -> bounded intent classification gates paid answer generation
    2. Pick prompt     -> normal travel prompt, or emergency prompt
    3. Build context   -> location anchor + last few chat messages
    4. Call LLM        -> OpenAI (TOURGUIDE_PRIMARY=openai, the default; 8 s to first token, 20 s total)
                          -> Gemini Tier A (grounded) -> Tier B (plain) -> Tier C (REST)
    5. Parse reply     -> split text / chips / card
    6. Save to DB      -> user message + assistant reply
Replies carry provider ("openai"|"gemini") and grounded (true only when Gemini search grounding was used).
stream_concierge_events is the same flow as Server-Sent Events (POST /api/tour-guide/chat/stream).
"""

import asyncio
import json
import logging
import math
import os
import re
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv
from sqlalchemy import text

import guide_places
from cost_guard import evaluate_cost_guards
from database import engine

load_dotenv()
log = logging.getLogger(__name__)

# One INFO line per chat turn (provider, timings). uvicorn doesn't configure app loggers, so this one gets its own
# handler, like the `voice` logger does in mount_voice.
turn_log = logging.getLogger("voyageai.tourguide")
if not turn_log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    turn_log.addHandler(_h)
    turn_log.setLevel(logging.INFO)
    turn_log.propagate = False

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
You give practical insider guidance and proactive assistance from your travel knowledge.
You cannot check live information. Never say a detail is verified, live, real-time or "as of today";
timings, prices, entry fees and closures can change, so say so briefly and suggest checking before going.

RULES:
1. Speak concisely (2 to 4 crisp sentences). Natural Hinglish or English based on user query language.
2. If recommending an activity or sight, explain the ground reality: usual best timing or any heads-up (common closures, peak queues, ticket hacks).
3. If recommending a concrete spot to add in Trip Mode, append a structured card at the very end:
<<<CARD:{"id": "rec_id_1", "title": "Place Name", "category": "Food/Sight/Stay", "location": "Area", "latitude": null, "longitude": null, "duration": "1.5h", "cost": 300, "heads_up": "Short caution or None"}>>>
In the card only, fill latitude and longitude with the place's decimal coordinates; keep null when you are not sure.
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
    "I can help with travel, sightseeing, and local experiences. Where are you headed?"
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


def _sdk_was_grounded(resp) -> bool:
    """True only when Gemini says it used search results (grounding_metadata with chunks or queries)."""
    try:
        meta = getattr(resp.candidates[0], "grounding_metadata", None)
        return bool(meta and (list(getattr(meta, "grounding_chunks", None) or [])
                              or list(getattr(meta, "web_search_queries", None) or [])))
    except Exception:
        return False


def _try_sdk_info(prompt: str, system_prompt: str, grounded: bool, temperature: float) -> Tuple[Optional[str], bool]:
    """Walk MODEL_CANDIDATES with the SDK; return (first non-empty text, whether search grounding was used)."""
    label = "grounded" if grounded else "plain"
    for name in MODEL_CANDIDATES:
        model = _build_model(name, system_prompt, grounded, temperature)
        if not model:
            continue
        try:
            resp = model.generate_content(prompt)
            if resp and resp.text:
                return resp.text.strip(), (grounded and _sdk_was_grounded(resp))
        except Exception as e:
            log.warning("[%s] model %s failed: %s", label, name, e)
    return None, False


def _try_sdk(prompt: str, system_prompt: str, grounded: bool, temperature: float) -> Optional[str]:
    """Walk MODEL_CANDIDATES with the SDK; return first non-empty text, else None."""
    return _try_sdk_info(prompt, system_prompt, grounded, temperature)[0]


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


def _gemini_chain(prompt: str, system_prompt: str, is_essential: bool) -> Tuple[Optional[str], bool]:
    """Tier A (live search) -> Tier B (no search) -> Tier C (raw REST).
    Returns (text or None, grounded); grounded is True only when Tier A answered AND used search results."""
    temp = 0.2 if is_essential else 0.4
    text_a, grounded = _try_sdk_info(prompt, system_prompt, grounded=True, temperature=temp)
    if text_a:
        return text_a, grounded
    return (_try_sdk(prompt, system_prompt, grounded=False, temperature=temp)
            or _try_rest(prompt, system_prompt, temp)), False


def _generate_reply(prompt: str, system_prompt: str, is_essential: bool) -> Optional[str]:
    """Tier A (live search) -> Tier B (no search) -> Tier C (raw REST). None if all fail."""
    return _gemini_chain(prompt, system_prompt, is_essential)[0]


# --------------------------------------------------------------------------
# OpenAI (primary for the chat since Nov 2026; TOURGUIDE_PRIMARY=gemini flips back)
# --------------------------------------------------------------------------
OPENAI_FIRST_TOKEN_TIMEOUT = 8.0
OPENAI_TOTAL_TIMEOUT = 20.0
OPENAI_MAX_TOKENS = 1024


def tourguide_primary() -> str:
    """TOURGUIDE_PRIMARY=openai|gemini (default openai), read on every turn so a flip needs no restart."""
    value = (os.getenv("TOURGUIDE_PRIMARY") or "openai").strip().lower()
    return value if value in ("openai", "gemini") else "openai"


def _openai_stream(prompt: str, system_prompt: str, temperature: float = 0.4):
    """Generator of answer pieces from OpenAI (same client, key and OPENAI_MODEL as the voice brain).
    Raises openai_client.LLMError on failure, timeout (8 s to first token, 20 s total) or an empty answer."""
    from openai_client import chat_stream
    yield from chat_stream(
        [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}],
        temperature=temperature, first_token_timeout=OPENAI_FIRST_TOKEN_TIMEOUT,
        total_timeout=OPENAI_TOTAL_TIMEOUT, max_completion_tokens=OPENAI_MAX_TOKENS)


def _openai_once(prompt: str, system_prompt: str, temperature: float = 0.4) -> Optional[str]:
    """The whole OpenAI answer (same timeouts as the stream), or None on any failure or an empty answer."""
    try:
        text_out = "".join(_openai_stream(prompt, system_prompt, temperature)).strip()
        return text_out or None
    except Exception as e:
        log.warning("[TOURGUIDE] openai failed: %s code=%s", type(e).__name__, getattr(e, "code", None))
        return None


def _log_turn(provider: Optional[str], ttft_ms: Optional[int], total_ms: int, grounded: bool,
              stream: bool, outcome: str) -> None:
    """One line per chat turn. Never the question or the answer."""
    turn_log.info("[TOURGUIDE] provider=%s ttft_ms=%s total_ms=%s grounded=%s stream=%s outcome=%s",
             provider or "none", ttft_ms if ttft_ms is not None else "-", total_ms,
             str(bool(grounded)).lower(), str(stream).lower(), outcome)


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


def _build_context_anchor(is_essential: bool, mode: str, dest: Optional[str], lat: Optional[float], lng: Optional[float],
                          pharmacy_note: bool = True) -> str:
    """One bracketed line telling the LLM where the user is / what mode we're in.
    pharmacy_note=False when the turn already has a VERIFIED PLACES block (no second Google call)."""
    if is_essential:
        return (
            f"[URGENT MEDICAL/ESSENTIAL MODE | User Location: lat={lat}, lng={lng}"
            f"{_nearby_pharmacy_note(lat, lng) if pharmacy_note else ''}]"
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
# Real places for "nearest hospital / medical shop near me / cafe near Hawa Mahal" (Google only)
# --------------------------------------------------------------------------
# category -> (Places API (New) includedTypes, words that mean it). Latin words match as whole words, any case;
# Devanagari words match as substrings (Python's \b doesn't work inside Devanagari words).
PLACE_CATEGORIES: Dict[str, Dict[str, Any]] = {
    "hospital": {
        "types": ["hospital"],
        # More than the 5 shown: the nearest results are often dispensaries and shops (guide_places.filter_and_sort).
        "max_results": 10,
        "words": ["hospital", "hospitals", "clinic", "clinics", "doctor", "doctors", "emergency", "ambulance",
                  "aspatal", "aspataal", "haspatal", "dawakhana"],
        "hindi": ["अस्पताल", "हॉस्पिटल", "हस्पताल", "डॉक्टर", "एम्बुलेंस", "दवाखाना"],
        "label": "hospital", "strong": True,
    },
    "pharmacy": {
        "types": ["pharmacy", "drugstore"],
        "words": ["pharmacy", "pharmacies", "medical shop", "medical shops", "medical store", "medical stores",
                  "chemist", "chemists", "medicine ki dukaan", "medicine ki dukan", "medicine shop", "medicine store",
                  "medicine", "medicines", "dawai", "dawaai", "dawa", "dawai ki dukaan", "drugstore"],
        "hindi": ["दवा", "दवाई", "दवा की दुकान", "दवाई की दुकान", "मेडिकल", "केमिस्ट", "फार्मेसी"],
        # Alone these don't mean a shop ("malaria medicine leni chahiye?"): they need a where/near word.
        "weak": ["medicine", "medicines", "dawai", "dawaai", "dawa", "दवा", "दवाई"],
        "label": "medical shop", "strong": True,
    },
    "cafe": {
        "types": ["cafe"],
        "words": ["cafe", "cafes", "café", "coffee", "chai", "tea stall", "chai ki tapri", "tapri"],
        "hindi": ["चाय", "कैफे", "कॉफी"],
        "label": "cafe", "strong": False,
    },
    "restaurant": {
        "types": ["restaurant"],
        "words": ["restaurant", "restaurants", "khana", "khaana", "khane", "dhaba", "dhabas", "food",
                  "eat", "eating", "lunch", "dinner", "breakfast", "nashta"],
        "hindi": ["खाना", "ढाबा", "रेस्टोरेंट", "रेस्तरां", "भोजन"],
        "label": "restaurant", "strong": False,
    },
}
# Checked in this order: "emergency medicine" is a hospital, "medical shop" a pharmacy, "chai aur khana" a cafe.
PLACE_CATEGORY_ORDER = ("hospital", "pharmacy", "cafe", "restaurant")

# Weak categories (food, cafe) only count as a place lookup with a "where / near" word, so
# "Jaipur ka famous khana kya hai?" stays a normal answer.
PLACE_SEARCH_WORDS = re.compile(
    r"\b(near|nearby|nearest|closest|close by|around|paas|pass|nazdeek|najdeek|nazdik|aaspas|aas paas|aas-paas|"
    r"kareeb|qareeb|kahan|kaha|kahaan|where|dhundo|dhoondo|dhundho|find|locate|open now|khula)\b", re.IGNORECASE)
PLACE_SEARCH_WORDS_HI = ("पास", "नज़दीक", "नजदीक", "कहाँ", "कहां")

_NEAR_X_EN = re.compile(r"\b(?:near(?:\s+to)?|close\s+to|next\s+to|around|nearby)\s+(?:the\s+)?(.+)$", re.IGNORECASE)
_X_KE_PAAS = re.compile(
    r"^(.+?)\s+(?:ke|ki|k)\s+(?:paas|pass|nazdeek|najdeek|nazdik|aaspas|aas\s*paas|aas-paas|kareeb|qareeb|saamne)\b",
    re.IGNORECASE)
_X_KE_PAAS_HI = re.compile(r"^(.+?)\s+के\s+(?:पास|नज़दीक|नजदीक|आसपास|आस-पास)")
# Words trimmed off both ends of a place name ("koi achha cafe Hawa Mahal" -> "Hawa Mahal").
_EDGE_WORDS = {
    "a", "an", "the", "me", "mujhe", "hume", "humein", "koi", "kuch", "ek", "achha", "accha", "acha", "achhi",
    "acchi", "best", "good", "nearest", "closest", "sasta", "sasti", "cheap", "top", "batao", "bataiye", "bata",
    "dikhao", "dikhaiye", "please", "pls", "plz", "chahiye", "hai", "hain", "kahan", "kaha", "where", "is", "are",
    "find", "show", "search", "open", "now", "abhi", "wala", "wali", "jagah", "place", "places", "shop", "store",
    "dukaan", "dukan", "ki", "ka", "ke", "se", "in", "at", "for", "of", "any", "some", "medical", "24x7", "24/7",
    "kaunsa", "konsa", "kaun", "sa", "si", "available", "nearby", "near", "and", "aur", "tell", "list", "give",
    "suggest", "recommend", "?", "street",
}
_EDGE_WORDS_HI = {"कोई", "अच्छा", "अच्छी", "बताओ", "बताइए", "दिखाओ", "कहाँ", "कहां", "है", "हैं", "मुझे", "की", "का", "के",
                  "दुकान", "सबसे", "पास", "नज़दीकी", "नजदीकी"}
# A "place" that is really the user ("mere ghar ke paas", "yahan ke paas", "near me").
_ME_FIRST_WORDS = {"me", "my", "mere", "mera", "meri", "hamare", "hamara", "yahan", "yahaan", "yaha", "here", "you",
                   "current", "मेरे", "मेरा", "यहाँ", "यहां", "हमारे"}


def _category_words() -> set:
    out = set()
    for spec in PLACE_CATEGORIES.values():
        for w in spec["words"] + spec["hindi"]:
            out.update(w.lower().split())
    return out


_CATEGORY_TOKENS = _category_words()


def _trim_place(raw: str, keep: str = "first") -> Optional[str]:
    """Trim fillers off both ends and category words off the front ("cafe Hawa Mahal" -> "Hawa Mahal"; a trailing
    one is part of the name: "AIIMS hospital"). keep: which clause to keep when punctuation splits the text
    ("first" after "near", "last" before "ke paas"). None when nothing (or only "me/here") is left."""
    parts = [p for p in re.split(r"[?!.,;:।]+", raw or "") if p.strip()]
    if not parts:
        return None
    words = (parts[0] if keep == "first" else parts[-1]).split()
    edge = _EDGE_WORDS | _EDGE_WORDS_HI
    while words and (words[0].lower() in edge or words[0].lower() in _CATEGORY_TOKENS):
        words.pop(0)
    while words and words[-1].lower() in edge:
        words.pop()
    if not words or words[0].lower() in _ME_FIRST_WORDS:
        return None
    try:
        from voice.tools.lookups import NEAR_ME_WORDS, _norm_words
        if _norm_words(" ".join(words)) in NEAR_ME_WORDS:
            return None
    except Exception:
        pass
    place = " ".join(words)
    return place if len(place) >= 2 else None


def _has_word(low: str, word: str) -> bool:
    return re.search(rf"(?<![\w]){re.escape(word)}(?![\w])", low) is not None


def _find_category(text_in: str) -> Optional[Tuple[str, bool]]:
    """(category, needs_search_word) for the first category mentioned, else None. needs_search_word is True for
    weak categories (food, cafe) and loose words ("medicine", "dawa") that alone don't mean "find me a place"."""
    low = (text_in or "").lower()
    for cat in PLACE_CATEGORY_ORDER:
        spec = PLACE_CATEGORIES[cat]
        weak = set(spec.get("weak", []))
        hits = [w for w in spec["words"] if _has_word(low, w)] + [h for h in spec["hindi"] if h in (text_in or "")]
        if hits:
            loose = (not spec["strong"]) or all(h in weak for h in hits)
            return cat, loose
    return None


def detect_place_intent(message: str) -> Optional[Dict[str, Any]]:
    """
    "nearest hospital" / "medical shop near me" / "cafe near Hawa Mahal" / "Hawa Mahal ke paas khana" ->
    {"category": hospital|pharmacy|cafe|restaurant, "place_text": "Hawa Mahal" | None}. Pure code, no LLM.
    place_text is the place named after "near"/"close to" or before "ke paas"/"के पास"; None = the user's location
    ("near me", "mere paas", "yahan", or no place at all). Not a place lookup -> None.
    """
    msg = (message or "").strip()
    if not msg or len(msg) > 300:
        return None
    place_text: Optional[str] = None
    for rx, keep in ((_X_KE_PAAS_HI, "last"), (_X_KE_PAAS, "last"), (_NEAR_X_EN, "first")):
        m = rx.search(msg)
        if m:
            place_text = _trim_place(m.group(1), keep)
            break
    # The category is looked for OUTSIDE the place name: "pharmacy near AIIMS hospital" is a pharmacy,
    # and "AIIMS hospital ke paas" alone names no category.
    rest = msg.replace(place_text, " ", 1) if place_text else msg
    found = _find_category(rest)
    if not found:
        return None
    category, needs_search_word = found
    if needs_search_word and place_text is None and PLACE_SEARCH_WORDS.search(msg) is None \
            and not any(w in msg for w in PLACE_SEARCH_WORDS_HI):
        return None
    return {"category": category, "place_text": place_text}


EMERGENCY_PREFIX = "In an emergency, call 112 or 108."
PLACES_RADIUS_M = 3000
PLACES_WIDE_RADIUS_M = 10000
PLACES_CACHE_SECONDS = 60
PLACES_SHOWN = 5


def _places_cache_key(category: str, lat: float, lng: float) -> str:
    return f"tg:places:{category}:{round(lat, 3)}:{round(lng, 3)}"


def _cache_get(key: str):
    try:
        from redis_client import redis_conn
        raw = redis_conn.get(key)
        return json.loads(raw) if raw else None
    except Exception:
        return None


def _cache_set(key: str, value: Any, ttl: int) -> None:
    try:
        from redis_client import redis_conn
        redis_conn.set(key, json.dumps(value), ex=ttl)
    except Exception:
        pass


def _resolve_named_place(place_text: str) -> Dict[str, Any]:
    """A named place -> its coordinates, with the app's named lookup (places.search_places_detailed: ONE Places
    Text Search (New), landmark-first, India only). Google only; never a guess."""
    import places as places_mod
    found = places_mod.search_places_detailed(place_text)
    if found.unavailable:
        return {"status": "unavailable"}
    if not found.results:
        return {"status": "not_found"}
    top = found.results[0]
    lat = top.get("latitude", top.get("lat"))
    lng = top.get("longitude", top.get("lng"))
    if lat is None or lng is None:
        return {"status": "not_found"}
    return {"status": "ok", "lat": float(lat), "lng": float(lng), "label": top.get("name") or place_text,
            "google_calls": found.google_calls or 0}


def _nearby_essentials(category: str, lat: float, lng: float) -> Tuple[List[Dict[str, Any]], bool, int, int]:
    """
    Google Places (New) searchNearby around (lat, lng) for the category: 3 km, then once more at 10 km if none matches
    the category (guide_places.filter_and_sort: types and order).
    rankPreference DISTANCE, 5 results (hospital: 10, the best 5 are kept), the essentials field mask, never Place Details.
    Cached 60 s per (category, lat/lng to 3 decimals). Returns (places, cache_hit, radius_used, google_calls).
    Raises GoogleQuotaError / GoogleNearbyError.
    """
    key = _places_cache_key(category, lat, lng)
    cached = _cache_get(key)
    if isinstance(cached, dict) and isinstance(cached.get("places"), list):
        return cached["places"], True, int(cached.get("radius_m") or PLACES_RADIUS_M), 0

    from places import _run_sync
    from services.google_maps_service import GoogleCallCounter, search_nearby_places
    counter = GoogleCallCounter()
    types = PLACE_CATEGORIES[category]["types"]
    max_results = PLACE_CATEGORIES[category].get("max_results", PLACES_SHOWN)

    def search(radius_m: int) -> Tuple[List[Dict[str, Any]], int]:
        rows = []
        for p in _run_sync(search_nearby_places(lat, lng, radius_m, place_types=types, strict=True, counter=counter,
                                                max_results=max_results)) or []:
            p_lat, p_lng = p.get("latitude"), p.get("longitude")
            if p_lat is None or p_lng is None or not p.get("name"):
                continue
            rows.append({
                "name": p["name"],
                "address": p.get("address") or None,
                "lat": p_lat,
                "lng": p_lng,
                "distance_m": int(round(haversine_meters(lat, lng, p_lat, p_lng))),
                "rating": p.get("rating"),
                "rating_count": p.get("userRatingCount") or None,
                "open_now": p.get("open_now"),
                "phone": p.get("phone"),
                "maps_url": p.get("maps_uri"),
                "primary_type": p.get("primary_type"),
                "types": p.get("types") or [],
            })
        return guide_places.filter_and_sort(category, rows)

    radius = PLACES_RADIUS_M
    out, matching = search(radius)
    if not matching:                # nothing of this category in 3 km (an empty answer, or only medicine shops)
        radius = PLACES_WIDE_RADIUS_M
        out, matching = search(radius)
    out = out[:PLACES_SHOWN]
    _cache_set(key, {"places": out, "radius_m": radius}, PLACES_CACHE_SECONDS)
    return out, False, radius, counter.count


def lookup_places(intent: Dict[str, Any], device_lat: Optional[float], device_lng: Optional[float]) -> Dict[str, Any]:
    """
    Where to look, then what is there. Location rule (same as voice search_nearby): a named place wins; otherwise
    the device location; neither -> needs_location (no Google call, no LLM call).
    Returns {status: ok|needs_location|unavailable|not_found|empty, category, source: named|device|None,
             label, places, radius_m}. Logs category, source, result count, cache hit, latency.
    """
    started = time.monotonic()
    category = intent["category"]
    place_text = intent.get("place_text")
    base = {"category": category, "source": None, "label": None, "places": [], "radius_m": None,
            "place_text": place_text}
    google_calls = 0
    cache_hit = False
    try:
        if place_text:
            named = _resolve_named_place(place_text)
            google_calls += named.get("google_calls", 0)
            if named["status"] != "ok":
                result = {**base, "status": named["status"], "source": "named", "label": place_text}
                return result
            center, source, label = (named["lat"], named["lng"]), "named", named["label"]
        elif device_lat is not None and device_lng is not None:
            center, source, label = (float(device_lat), float(device_lng)), "device", None
        else:
            result = {**base, "status": "needs_location"}
            return result
        try:
            found, cache_hit, radius, calls = _nearby_essentials(category, center[0], center[1])
            google_calls += calls
        except Exception as e:  # GoogleQuotaError / GoogleNearbyError: honest "unavailable", never invented places
            log.warning("[TOURGUIDE PLACES] nearby failed: %s", type(e).__name__)
            result = {**base, "status": "unavailable", "source": source, "label": label}
            return result
        result = {**base, "status": "ok" if found else "empty", "source": source, "label": label,
                  "places": found, "radius_m": radius}
        return result
    finally:
        r = locals().get("result") or {}
        turn_log.info("[TOURGUIDE PLACES] category=%s source=%s status=%s results=%s cache_hit=%s radius_m=%s "
                      "google_calls=%s ms=%s", category, r.get("source") or "none", r.get("status"),
                      len(r.get("places") or []), str(cache_hit).lower(), r.get("radius_m") or "-", google_calls,
                      _ms_since(started))


def _place_fields(found: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Response fields for every reply: places (cards), emergency (112/108 strip), needs_location (button)."""
    if not found:
        return {"places": [], "emergency": False, "needs_location": False, "place_intent": None}
    return {
        "places": [guide_places.public_place(p) for p in found.get("places") or []],
        "emergency": found["category"] == "hospital",
        "needs_location": found.get("status") == "needs_location",
        "place_intent": {"category": found["category"], "source": found.get("source"), "near": found.get("label")},
    }


def _history_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """What goes into chat_messages.metadata: the places without phone numbers or addresses."""
    if not payload.get("places"):
        return payload
    return {**payload, "places": [{k: v for k, v in p.items() if k not in ("phone", "address")}
                                  for p in payload["places"]]}


def _with_emergency_prefix(found: Optional[Dict[str, Any]], reply: str) -> str:
    if not found or found["category"] != "hospital" or reply.startswith(EMERGENCY_PREFIX):
        return reply
    return f"{EMERGENCY_PREFIX} {reply}".strip()


def _place_early_reply(found: Dict[str, Any]) -> Tuple[str, List[str]]:
    """No LLM: missing location, Google unavailable, the named place not found, or nothing nearby."""
    cat = found["category"]
    label = PLACE_CATEGORIES[cat]["label"]
    medical = cat in ("hospital", "pharmacy")
    status = found["status"]
    if status == "needs_location":
        reply = (f"We couldn’t determine your location. Enable location access or name a place, "
                 f"for example, \"{label} near Hawa Mahal\".")
        chips = []
    elif status == "unavailable":
        reply = "Google Maps is temporarily unavailable. Please try again shortly."
        if cat == "pharmacy":
            reply += " " + EMERGENCY_PREFIX
        chips = ["Retry now"]
    elif status == "not_found":
        reply = f"\"{found.get('place_text') or found.get('label')}\" couldn’t be found on Google Maps. Try a more specific place name."
        chips = []
    else:  # empty
        where = found["label"] if found.get("source") == "named" else "your location"
        reply = f"Google Maps found no results for {label} within 10 km of {where}."
        if medical and cat == "pharmacy":
            reply += " " + EMERGENCY_PREFIX
        chips = []
    return _with_emergency_prefix(found, reply), chips


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
    device_lat: Optional[float] = None,
    device_lng: Optional[float] = None,
) -> Dict[str, Any]:
    started = time.monotonic()
    turn = _prepare_turn(user_id, message, mode, trip_id, destination_name or trip_destination,
                         lat if lat is not None else user_lat, lng if lng is not None else user_lng, recent_history,
                         device_lat=device_lat, device_lng=device_lng)
    if turn["deflection"] is not None:
        _log_turn(None, None, _ms_since(started), False, stream=False, outcome="deflected")
        return turn["deflection"]

    # 4. Call LLM: OpenAI first (unless TOURGUIDE_PRIMARY=gemini), then the Gemini tiers.
    raw_text, provider, grounded = None, None, False
    if tourguide_primary() == "openai":
        raw_text = _openai_once(turn["prompt"], turn["system_prompt"], turn["temperature"])
        provider = "openai" if raw_text else None
    if not raw_text:
        raw_text, grounded = _gemini_chain(turn["prompt"], turn["system_prompt"], turn["is_essential"])
        provider = "gemini" if raw_text else None
    total_ms = _ms_since(started)

    if not raw_text:
        log.error("All LLM tiers failed")
        _log_turn(None, None, total_ms, False, stream=False, outcome="failed")
        return _failure_payload(turn)

    # 5. Parse reply, 6. persist exchange
    payload = _finish_payload(turn, raw_text, provider, grounded)
    _save_exchange(user_id, message, payload["reply"], mode, trip_id, _history_payload(payload))
    _log_turn(provider, total_ms, total_ms, grounded, stream=False, outcome="ok")
    return payload


def _ms_since(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


DEFLECTION_CHIPS = ["Must-try street food", "Top sights today", "Hidden gems"]


def _prepare_turn(user_id, message, mode, trip_id, dest, eff_lat, eff_lng, recent_history,
                  device_lat=None, device_lng=None) -> Dict[str, Any]:
    """
    Steps 1-3 of a chat turn, shared by the JSON and the streamed endpoint.
    Returns {"deflection": payload} (already saved) when no model call is needed: the cost guard refused, or a
    place lookup ("nearest hospital") ended early (no location, Google unavailable, nothing found). Else the
    prompt pieces; a place lookup with results adds a VERIFIED PLACES block and its rules.
    device_lat/lng: the device location for place lookups, sent in Trip mode too (eff_lat/lng is Local only).
    """
    # 1. Cost guard: unmatched or unavailable classification asks for clarification.
    should_call_llm, gate_reason, deflection = evaluate_cost_guards(message)
    base = {"user_id": user_id, "message": message, "mode": mode, "trip_id": trip_id, "gate": gate_reason,
            "place": None}
    if not should_call_llm:
        payload = {
            "reply": deflection,
            "chips": list(DEFLECTION_CHIPS),
            "card": None,
            "mode": mode,
            "gate": gate_reason,
            "provider": None,
            "grounded": False,
            **_place_fields(None),
        }
        _save_exchange(user_id, message, deflection, mode, trip_id, payload)
        return {**base, "deflection": payload}

    # 1b. Real places (Google) for "nearest hospital / medical shop / cafe near X": before any model call.
    found = None
    intent = detect_place_intent(message)
    if intent:
        found = lookup_places(intent,
                              device_lat if device_lat is not None else eff_lat,
                              device_lng if device_lng is not None else eff_lng)
        if found["status"] != "ok":
            reply, chips = _place_early_reply(found)
            payload = {"reply": reply, "chips": chips, "card": None, "mode": mode, "gate": gate_reason,
                       "provider": None, "grounded": False, "error": None, **_place_fields(found)}
            _save_exchange(user_id, message, reply, mode, trip_id, _history_payload(payload))
            return {**base, "place": found, "deflection": payload}

    # 2. Choose prompt
    is_essential = gate_reason == ESSENTIAL_GATE
    if found:       # nearby places: facts only. The general prompts ask for tips, timings and delivery apps.
        system_prompt = guide_places.places_system_prompt(found["category"])
    else:
        system_prompt = EMERGENCY_SYSTEM_PROMPT if is_essential else JARVIS_SYSTEM_PROMPT

    # 3. Build context
    anchor = _build_context_anchor(is_essential, mode, dest, eff_lat, eff_lng, pharmacy_note=found is None)

    if recent_history is None:
        rows = fetch_chat_history(user_id, trip_id=trip_id if mode == "trip" else None, limit=6)
        recent_history = [{"role": r["role"], "content": r["content"]} for r in rows]

    places_block = guide_places.places_block(found) if found else ""
    prompt = f"{anchor}\n\n{places_block}{_build_history_block(recent_history)}Traveler current query: {message}"
    if not found:
        system_prompt = system_prompt.replace(" Natural Hinglish or English based on user query language.", "")
        system_prompt += "\nUse clear English for chat replies and follow-up buttons. If the traveler explicitly asks for Hindi, use Devanagari."
    return {**base, "place": found, "deflection": None, "is_essential": is_essential,
            "system_prompt": system_prompt, "prompt": prompt, "temperature": 0.2 if is_essential or found else 0.4}


def _failure_payload(turn: Dict[str, Any]) -> Dict[str, Any]:
    """Every model failed: the same friendly text as before (nearby places: the plain facts). Never saved."""
    found = turn.get("place")
    if found and found.get("places"):
        reply = _with_emergency_prefix(found, guide_places.facts_reply(found, turn["message"]))
        chips = ["Retry now"]
    elif turn["is_essential"]:
        reply = "Check Google Maps for a nearby pharmacy or one open 24 hours. You can also check Blinkit or Instamart for delivery."
        chips = ["Locate nearby pharmacy", "Nearest hospital", "Retry"]
    else:
        reply = "The connection is slow. Please try sending your message again."
        chips = ["Retry now", "Nearby food", "Top sights"]
    return {
        "reply": reply,
        "chips": chips,
        "card": None,
        "mode": turn["mode"],
        "gate": turn["gate"],
        "error": "LLM_TOTAL_FAILURE",
        "provider": None,
        "grounded": False,
        **_place_fields(turn.get("place")),
    }


def _finish_payload(turn: Dict[str, Any], raw_text: str, provider: str, grounded: bool) -> Dict[str, Any]:
    """Step 5: split text / chips / card, deflect code fences, add default chips."""
    clean_text, chips, card = parse_blocks(raw_text)
    if "```" in clean_text:
        clean_text = CODE_BLOCK_DEFLECTION

    default_chips = ["Locate on Map", "Quick Delivery"] if turn["is_essential"] else ["Show map", "Nearby food", "Timing tips"]
    found = turn.get("place")
    if found:
        card = None  # the verified places are the cards; a model card could name something Google didn't return
        clean_text, dropped = guide_places.clean_places_text(clean_text, found, turn["message"])
        if dropped:
            turn_log.info("[TOURGUIDE PLACES] text_check category=%s dropped=%s", found["category"], dropped)
        clean_text = _with_emergency_prefix(found, clean_text)
        chips = guide_places.place_chips(found)
    return {
        "reply": clean_text,
        "chips": chips or default_chips,
        "card": card,
        "mode": turn["mode"],
        "gate": turn["gate"],
        "error": None,
        "provider": provider,
        "grounded": bool(grounded and provider == "gemini"),
        **_place_fields(found),
    }


# --------------------------------------------------------------------------
# Streaming (POST /api/tour-guide/chat/stream, Server-Sent Events)
# --------------------------------------------------------------------------
# The model ends with <<<CHIPS:[...]>>> / <<<CARD:{...}>>>; a code fence is replaced by a deflection. Neither may
# reach the client as tokens: streaming stops for good at the first marker.
STREAM_STOP_MARKERS = ("<<<", "```")
TOKEN_FLUSH_SECONDS = 0.04
TOKEN_FLUSH_WORDS = 3


class StreamTagFilter:
    """Feeds raw model text, returns only the part that is safe to show.
    Holds back a trailing partial marker ("<", "<<", "`", "``") and stops at the first full marker."""

    def __init__(self) -> None:
        self.raw = ""
        self._sent = 0
        self.stopped = False

    def feed(self, piece: str) -> str:
        self.raw += piece or ""
        if self.stopped:
            return ""
        hits = [i for i in (self.raw.find(m, max(0, self._sent - len(m))) for m in STREAM_STOP_MARKERS) if i >= 0]
        if hits:
            self.stopped = True
            end = min(hits)
        else:
            hold = 0
            for marker in STREAM_STOP_MARKERS:
                for k in range(len(marker) - 1, 0, -1):
                    if self.raw.endswith(marker[:k]):
                        hold = max(hold, k)
                        break
            end = len(self.raw) - hold
        out = self.raw[self._sent:end] if end > self._sent else ""
        self._sent = max(self._sent, end)
        return out

    def finish(self) -> str:
        """End of the answer: release a held-back tail that never became a marker."""
        if self.stopped:
            return ""
        out = self.raw[self._sent:]
        self._sent = len(self.raw)
        return out


class TokenBatcher:
    """Groups safe text into small token events: about 1-3 words, or whatever came in the last ~40 ms."""

    def __init__(self, clock=time.monotonic) -> None:
        self.buf = ""
        self._clock = clock
        self._last = clock()

    def add(self, text_piece: str, force: bool = False) -> Optional[str]:
        self.buf += text_piece or ""
        if not self.buf:
            return None
        due = force or len(self.buf.split()) > TOKEN_FLUSH_WORDS or (self._clock() - self._last) >= TOKEN_FLUSH_SECONDS
        if not due:
            return None
        if force:
            out, self.buf = self.buf, ""
        else:
            cut = max(self.buf.rfind(" "), self.buf.rfind("\n"))
            if cut < 0:
                return None  # still inside the first word: wait for its end
            out, self.buf = self.buf[:cut + 1], self.buf[cut + 1:]
        self._last = self._clock()
        return out or None


def _word_chunks(text_in: str, words: int = 6) -> List[str]:
    """A ready answer (Gemini) sent as a few quick token events."""
    parts = re.findall(r"\S+\s*", text_in)
    return ["".join(parts[i:i + words]) for i in range(0, len(parts), words)] or ([text_in] if text_in else [])


def sse(event: str, data: Dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def stream_concierge_events(
    user_id: str,
    message: str,
    mode: str = "local",
    trip_id: Optional[str] = None,
    destination_name: Optional[str] = None,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    recent_history: Optional[List[Dict[str, str]]] = None,
    is_disconnected=None,
    device_lat: Optional[float] = None,
    device_lng: Optional[float] = None,
):
    """
    Async generator of SSE strings: start -> token* -> done, or error.
      - cost-guard deflection: one token + done, no model call (saved, as before)
      - OpenAI streams; if it fails before any token reached the client -> Gemini (whole reply in a few tokens)
      - OpenAI fails after tokens were sent -> error {partial: true}, nothing saved
      - everything failed -> error {code, message: the friendly text, chips}, nothing saved
      - client gone (is_disconnected() true, or the task is cancelled) -> stop generating, nothing saved
    The exchange is saved only after a full reply, just before `done`.
    """
    started = time.monotonic()

    async def gone() -> bool:
        if is_disconnected is None:
            return False
        try:
            return bool(await is_disconnected())
        except Exception:
            return False

    turn = await asyncio.to_thread(_prepare_turn, user_id, message, mode, trip_id, destination_name, lat, lng,
                                   recent_history, device_lat, device_lng)
    if turn["deflection"] is not None:
        payload = turn["deflection"]
        yield sse("start", {"provider": None})
        yield sse("token", {"t": payload["reply"]})
        yield sse("done", {**payload, "error": None})
        _log_turn(None, None, _ms_since(started), False, stream=True, outcome="deflected")
        return

    provider = tourguide_primary()
    yield sse("start", {"provider": provider})
    if turn.get("place") and turn["place"]["category"] == "hospital":
        # Shown at once, before the model starts; done.reply begins with the same line.
        yield sse("token", {"t": EMERGENCY_PREFIX + " "})
    ttft_ms: Optional[int] = None
    raw_text: Optional[str] = None
    grounded = False
    tokens_sent = False

    if provider == "openai":
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        stop = threading.Event()

        def pump() -> None:
            gen = _openai_stream(turn["prompt"], turn["system_prompt"], turn["temperature"])
            try:
                for piece in gen:
                    if stop.is_set():
                        break
                    loop.call_soon_threadsafe(queue.put_nowait, ("piece", piece))
                loop.call_soon_threadsafe(queue.put_nowait, ("end", None))
            except Exception as exc:  # noqa: BLE001 - reported to the async side
                loop.call_soon_threadsafe(queue.put_nowait, ("error", exc))
            finally:
                gen.close()

        worker = loop.run_in_executor(None, pump)
        filt, batch = StreamTagFilter(), TokenBatcher()
        gate = guide_places.PlaceSentenceGate(turn["place"]) if turn.get("place") else None
        failure: Optional[BaseException] = None
        try:
            while True:
                try:
                    kind, value = await asyncio.wait_for(queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    if await gone():
                        stop.set()
                        _log_turn("openai", ttft_ms, _ms_since(started), False, stream=True, outcome="client_gone")
                        return
                    continue
                if kind == "piece":
                    safe = filt.feed(value)
                    out = batch.add(gate.feed(safe) if gate else safe)
                    if out:
                        if ttft_ms is None:
                            ttft_ms = _ms_since(started)
                        tokens_sent = True
                        yield sse("token", {"t": out})
                        if await gone():
                            stop.set()
                            _log_turn("openai", ttft_ms, _ms_since(started), False, stream=True,
                                      outcome="client_gone")
                            return
                elif kind == "end":
                    safe = filt.finish()
                    out = batch.add(gate.feed(safe) + gate.finish() if gate else safe, force=True)
                    if out:
                        if ttft_ms is None:
                            ttft_ms = _ms_since(started)
                        tokens_sent = True
                        yield sse("token", {"t": out})
                    raw_text = filt.raw.strip() or None
                    break
                else:
                    failure = value
                    break
        finally:
            stop.set()  # also on cancellation (client gone): the worker stops at its next piece
        if failure is not None:
            log.warning("[TOURGUIDE] openai stream failed: %s code=%s after_tokens=%s", type(failure).__name__,
                        getattr(failure, "code", None), tokens_sent)
            if tokens_sent:
                yield sse("error", {"code": "STREAM_INTERRUPTED", "message": "The answer was cut off.",
                                    "partial": True})
                _log_turn("openai", ttft_ms, _ms_since(started), False, stream=True, outcome="partial_error")
                return
            raw_text = None
        del worker  # not awaited: after `end`/`error` it has finished, after a stop it ends at its next piece

    if not raw_text:
        # Gemini: never streamed. Silent fallback when OpenAI failed before anything reached the client.
        provider = "gemini"
        task = asyncio.ensure_future(asyncio.to_thread(_gemini_chain, turn["prompt"], turn["system_prompt"],
                                                       turn["is_essential"]))
        while not task.done():
            await asyncio.wait({task}, timeout=0.5)
            if not task.done() and await gone():
                _log_turn("gemini", None, _ms_since(started), False, stream=True, outcome="client_gone")
                return
        raw_text, grounded = task.result()
        if raw_text:
            clean, _, _ = parse_blocks(raw_text)
            if "```" in clean:
                clean = CODE_BLOCK_DEFLECTION
            elif turn.get("place"):
                clean, _ = guide_places.clean_places_text(clean, turn["place"], message)
            for chunk in _word_chunks(clean):
                if ttft_ms is None:
                    ttft_ms = _ms_since(started)
                yield sse("token", {"t": chunk})

    if not raw_text:
        log.error("All LLM tiers failed")
        fail = _failure_payload(turn)
        yield sse("error", {"code": "LLM_TOTAL_FAILURE", "message": fail["reply"], "chips": fail["chips"],
                            "partial": False})
        _log_turn(None, None, _ms_since(started), False, stream=True, outcome="failed")
        return

    if await gone():
        _log_turn(provider, ttft_ms, _ms_since(started), grounded, stream=True, outcome="client_gone")
        return
    payload = _finish_payload(turn, raw_text, provider, grounded)
    await asyncio.to_thread(_save_exchange, user_id, message, payload["reply"], mode, turn["trip_id"],
                            _history_payload(payload))
    yield sse("done", payload)
    _log_turn(provider, ttft_ms, _ms_since(started), payload["grounded"], stream=True, outcome="ok")


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
# Voice mode (voicefirst.md step 3 + fixes before step 4): short spoken answers
# --------------------------------------------------------------------------
VOICE_ANSWER_PROMPT = """
You are VoyageAI's travel guide answering by VOICE inside a travel app for India.

RULES:
1. {lang_rule}
2. At most 2 short sentences, under 15 words each. They are spoken aloud.
3. Plain spoken text only: no markdown, lists, headings, emojis, links, cards or chips.
4. Never guess timings, opening hours, prices or entry fees. Give them only if your search results
   state them; otherwise say you don't have reliable information.
5. Only travel topics (places, food, timings, tickets, transport, culture, safety).
   For anything else answer exactly: {decline}
"""
VOICE_LANG_RULE = {
    "hi": "Reply in natural Hinglish written in Roman script (Hindi words in English letters).",
    "en": "Reply in simple English.",
}
VOICE_DECLINE = {
    "hi": "Main sirf aapki trip mein madad kar sakta hoon.",
    "en": "I can only help with your trip.",
}
VOICE_NO_FACTS = {
    "hi": "Abhi pakki jaankari nahi mil rahi.",
    "en": "I couldn't find reliable info right now.",
}
# Shown as small text on screen with ungrounded answers; never spoken.
VOICE_NOTE = {"hi": "Details may vary.", "en": "Details may vary."}
VOICE_GEMINI_TIMEOUT = 4.0
VOICE_LLM_TIMEOUT = 4.0
GROUNDING_COOLDOWN_SECONDS = 600  # after a quota error, don't spend ~0.5 s per question on a call that fails

# Questions whose answer must come from grounded search (timings, hours, prices, fees, tickets).
_FACT_WORDS = re.compile(
    r"\b(timing|timings|hours?|open|opening|close|closing|khul\w*|band\b|price|prices|cost|costs|fee|fees|"
    r"ticket|tickets|entry|kitne|kitna|kitni|rate|charges?|kab tak|kab se|baje)\b", re.IGNORECASE)

_MARKDOWN = re.compile(r"(\*\*|__|`|#+\s|^\s*[-*•]\s+|\[\d+\])", re.MULTILINE)
_grounding_off_until = 0.0


def is_fact_question(question: str) -> bool:
    return bool(_FACT_WORDS.search(question or ""))


def _clean_spoken(raw: str) -> str:
    """Drop chips/cards/markdown/links so the text can be spoken."""
    text, _, _ = parse_blocks(raw or "")
    text = re.sub(r"https?://\S+", "", text)
    text = _MARKDOWN.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def _first_sentences(text: str, limit: int) -> str:
    parts = re.split(r"(?<=[.!?।])\s+", text.strip())
    return " ".join(parts[:limit]).strip()


def _gemini_rest(question: str, system_prompt: str, grounded: bool) -> Tuple[Optional[str], Optional[str]]:
    """
    One Gemini call over REST (first model). grounded=True attaches Google Search (the `google_search` tool used
    by current Gemini models) and only accepts an answer that actually cites search results.
    Returns (text, error_code); error_code is e.g. "http_429", "timeout", "not_grounded".
    """
    global _grounding_off_until
    import time as _time
    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key or not MODEL_CANDIDATES:
        return None, "no_key"
    if grounded and _time.time() < _grounding_off_until:
        return None, "grounding_cooldown"
    body: Dict[str, Any] = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": question}]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 300},
    }
    if grounded:
        body["tools"] = [{"google_search": {}}]
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_CANDIDATES[0]}:generateContent"
    try:
        res = requests.post(url, json=body, headers={"x-goog-api-key": key}, timeout=VOICE_GEMINI_TIMEOUT)
    except requests.Timeout:
        return None, "timeout"
    except requests.RequestException as e:
        return None, type(e).__name__
    if res.status_code != 200:
        if grounded and res.status_code == 429:
            _grounding_off_until = _time.time() + GROUNDING_COOLDOWN_SECONDS
        return None, f"http_{res.status_code}"
    try:
        cand = (res.json().get("candidates") or [{}])[0]
        parts = (cand.get("content") or {}).get("parts") or []
        text = " ".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()
    except (ValueError, AttributeError):
        return None, "bad_response"
    if not text:
        return None, "empty"
    if grounded and not ((cand.get("groundingMetadata") or {}).get("groundingChunks")):
        return text, "not_grounded"
    return text, None


def _voice_llm(question: str, system_prompt: str) -> Optional[str]:
    try:
        from openai_client import chat
        return chat([{"role": "system", "content": system_prompt}, {"role": "user", "content": question}],
                    temperature=0.3, timeout=VOICE_LLM_TIMEOUT, max_completion_tokens=400, reasoning_effort="low")
    except Exception as e:
        log.warning("[voice answer] openai failed: %s", type(e).__name__)
        return None


def voice_answer(question: str, lang: str = "hi", user_id: Optional[str] = None,
                 trip_id: Optional[str] = None, place: Optional[str] = None, facts: Optional[bool] = None) -> Dict[str, Any]:
    """
    Short spoken answer to a travel question (at most 2 sentences).
      1. Cost guard (fails closed, as for every paid answer).
      2. Gemini with Google Search grounding.
      3. Timings / hours / prices / fees: ONLY a grounded answer is used; else "Abhi pakki jaankari nahi mil rahi."
         Other questions: plain Gemini, then OpenAI; these carry a `note` ("Details badal sakti hain") that the app
         shows as small text and never speaks.
    The question and the answer are saved to the user's Guide chat (mode "voice").
    Returns {status: ok|declined|no_facts|failed, spoken, full, note, source: gemini_grounded|gemini|openai|None,
             fallback_code}. Never raises. Logs carry outcomes and error codes, never the question or the answer.
    """
    lang = lang if lang in VOICE_LANG_RULE else "hi"
    q = (question or "").strip()[:500]
    if place and place.strip() and place.strip().lower() not in q.lower():
        q = f"{q} ({place.strip()[:120]})"
    empty = {"spoken": None, "full": None, "note": None, "source": None, "fallback_code": None}
    if not q:
        return {**empty, "status": "failed"}
    facts = is_fact_question(q) if facts is None else (facts or is_fact_question(q))

    allowed, gate, _reply = evaluate_cost_guards(q)
    if not allowed:
        log.info("[voice answer] cost guard refused (%s)", gate)
        return {**empty, "status": "declined", "spoken": VOICE_DECLINE[lang]}

    system_prompt = VOICE_ANSWER_PROMPT.format(lang_rule=VOICE_LANG_RULE[lang], decline=VOICE_DECLINE[lang])
    raw, code = _gemini_rest(q, system_prompt, grounded=True)
    source, note, fallback_code = "gemini_grounded", None, None
    if code is not None:
        fallback_code = code
        log.warning("[voice answer] grounded gemini not used: %s (facts=%s)", code, facts)
        if facts:
            # Never guess timings or prices: an ungrounded answer to a fact question is not used.
            return {**empty, "status": "no_facts", "spoken": VOICE_NO_FACTS[lang], "fallback_code": code}
        raw, code2 = (raw, None) if code == "not_grounded" else _gemini_rest(q, system_prompt, grounded=False)
        source, note = "gemini", VOICE_NOTE[lang]
        if not raw:
            log.warning("[voice answer] plain gemini failed: %s", code2)
            raw, source = _voice_llm(q, system_prompt), "openai"
    full = _first_sentences(_clean_spoken(raw or ""), 2)
    if not full:
        return {**empty, "status": "failed", "fallback_code": fallback_code}

    if user_id and not _is_guest(user_id):
        try:
            persist_message(user_id, "user", q, "voice", trip_id, {"via": "voice"})
            persist_message(user_id, "assistant", full, "voice", trip_id, {"via": "voice", "source": source})
        except Exception as e:
            log.warning("[voice answer] history save failed: %s", type(e).__name__)
    return {"status": "ok", "spoken": full, "full": full, "note": note, "source": source, "fallback_code": fallback_code}
