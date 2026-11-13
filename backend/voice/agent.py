"""
The voice agent ("the mind"), voicefirst.md step 2. ONE Groq call per turn, ONE tool: navigate.

transcript + memory + current state -> Groq (function calling) -> checked against voice/pages.py ->
(reply_text, ui_actions). The agent never touches data. Logs carry the action and timings only,
never the user's words or the reply.

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

What you can do:
- To open a page, call the navigate tool. Only call it when the user clearly asks to open
  or see something.
- If the request is unclear, ask ONE short question instead of guessing.
- If the user asks for something unrelated to travel, politely decline:
  "Main sirf aapki trip mein madad kar sakta hoon."
- Never invent pages, routes or facts.

Current state:
- User is on page: {screen}
- Open trip: {trip_line}"""

NAVIGATE_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "navigate",
        "description": "Open a page of the app.",
        "parameters": {
            "type": "object",
            "properties": {
                "page": {"type": "string", "enum": pages.PAGES},
                "day": {"type": "integer", "minimum": pages.MIN_DAY, "maximum": pages.MAX_DAY,
                        "description": "Only for itinerary: which day to open."},
            },
            "required": ["page"],
        },
    },
}
TOOLS = [NAVIGATE_TOOL]


@dataclass
class TripInfo:
    title: str
    start_date: Optional[str]
    end_date: Optional[str]


@dataclass
class AgentResult:
    reply_text: str
    ui_actions: List[Dict[str, Any]] = field(default_factory=list)
    action: str = "reply"            # "navigate:<page>" | "reply" | "error"
    llm_ms: int = 0
    error_code: Optional[str] = None  # for logs only


def template_language(stt_language: Optional[str]) -> str:
    """STT language -> template language: hi/ur -> "hi", en -> "en", anything else -> "hi"."""
    lang = (stt_language or "").strip().lower()
    return "en" if lang == "en" else "hi"


def build_system_prompt(screen: Optional[str], trip: Optional[TripInfo]) -> str:
    trip_line = (f"{trip.title} ({trip.start_date or '?'} to {trip.end_date or '?'})" if trip else "none")
    return SYSTEM_PROMPT.format(screen=(screen or "unknown")[:120], trip_line=trip_line)


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

def _decide(tool_calls: List[Dict[str, Any]], content: Optional[str], lang: str, has_trip: bool) -> AgentResult:
    nav = next((c for c in tool_calls if c.get("name") == "navigate"), None)
    if nav is None:
        if tool_calls:  # a tool we don't offer
            return AgentResult(pages.WHICH_PAGE_REPLY[lang], action="reply", error_code="unknown_tool")
        return AgentResult(trim_sentences(content or "") or pages.WHICH_PAGE_REPLY[lang], action="reply")

    args = nav.get("arguments") or {}
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
    try:
        answer = groq_chat_tools(messages, TOOLS, tool_choice="auto", temperature=0.2,
                                 timeout=LLM_TIMEOUT_SECONDS, reasoning_effort="low")
        result = _decide(answer["tool_calls"], answer["content"], lang, has_trip=trip is not None)
    except GroqRateLimited:
        result = AgentResult(FALLBACK_REPLY, action="error", error_code="rate_limited")
    except GroqError as err:
        code = "bad_tool_args" if "arguments" in str(err) else "groq_error"
        result = AgentResult(FALLBACK_REPLY, action="error", error_code=code)
    except Exception as err:
        result = AgentResult(FALLBACK_REPLY, action="error", error_code=type(err).__name__)
    result.llm_ms = int((time.perf_counter() - started) * 1000)

    if result.action != "error":
        save_turn(redis_conn, user_id, conversation_id, transcript, result.reply_text)
    logger.info("[VOICE AGENT] action=%s llm_ms=%s%s", result.action, result.llm_ms,
                f" code={result.error_code}" if result.error_code else "")
    return result
