"""
One voice turn, run as stages in order.

Stages: run_turn() = speech to text (its result goes to the app at once as "transcript"),
then make_reply() = the agent decides (voice/agent.py: navigate, answers and look-ups) and Sarvam
speaks its short reply (step 1b TTS, never cached).
after_turn() is the last stage, run once the app has its answer; it only feeds the test-only
debug store (testing.md).

These functions are blocking (HTTP, disk, DB): call them from a threadpool.
Logs carry the turn ID, lengths, timings and status. Never the words or the audio.
"""
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from voice import debug_store, error_log
from voice.messages import ErrorCode
from voice.stt import STTError, STTRateLimited, get_stt, pcm_duration_ms
from voice.agent import TripInfo, run_agent
from voice.lang import detect_lang
from voice.tts import REPLY_MIME, synthesize_reply

EMPTY_TRANSCRIPT_REPLY = "Mujhe kuch sunai nahi diya, phir se boliye."

logger = logging.getLogger("voice")


def new_turn_id() -> str:
    return f"turn_{uuid.uuid4().hex[:16]}"


@dataclass
class TurnContext:
    turn_id: str
    user_id: str
    session_id: str
    conversation_id: Optional[str] = None
    screen: Optional[str] = None
    trip: Optional[TripInfo] = None  # the open trip, already ownership-checked (title + dates only)
    location: Optional[Tuple[float, float]] = None  # the user's position from the app (this turn only; never logged)
    screen_place: Optional[dict] = None  # step 5: {place_id, name, address} of the place page on screen (checked shape)
    truncated: bool = False          # cut at 30 s
    turn_number: int = 0             # n-th recording on this connection (error log)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class TurnResult:
    turn_id: str
    ok: bool
    text: str = ""
    language: Optional[str] = None
    duration_ms: int = 0
    stt_ms: int = 0
    stt_provider: Optional[str] = None
    stt_model: Optional[str] = None
    error_code: Optional[str] = None
    error_detail: Optional[str] = None   # STT failure reason: logs, debug store, and the error message's "detail"
    # Spoken reply (step 1b)
    reply_text: Optional[str] = None
    reply_audio_b64: Optional[str] = None
    reply_mime: str = REPLY_MIME
    tts_ms: int = 0
    # Agent (step 2)
    ui_actions: List[Dict[str, Any]] = field(default_factory=list)
    action: str = "reply"                # "navigate:<page>" | "reply" | "error"
    llm_ms: int = 0
    # Why the agent failed / fell back. One mechanism: sent to the app as the reply's error_code / error_detail,
    # saved in the debug store's agent_error_code / agent_error_detail and written to logs/voice_errors.md.
    agent_error_code: Optional[str] = None
    agent_error_detail: Optional[str] = None  # status / code / class names only, never words
    agent_error_info: Dict[str, Any] = field(default_factory=dict)
    tool_ms: int = 0                     # step 3: the tool after the deciding call (answer: cost guard + Gemini)
    note: Optional[str] = None           # small on-screen text, never spoken (e.g. "Details badal sakti hain.")
    note_attribution: Optional[str] = None  # "Google Maps" when the note is Google Maps content
    pending_confirmation: Optional[Dict[str, Any]] = None  # step 4: {id, summary} -> the Confirm card
    reply_language: Optional[str] = None # "hi" / "en", from the reply text (TTS voice)
    tts_error: Optional[str] = None      # None = reply audio ready; else why (e.g. "sarvam: http_429 <code>")


def run_turn(pcm: bytes, ctx: TurnContext) -> TurnResult:
    """Stage 1: speech to text. The PCM is not kept anywhere by this function."""
    duration_ms = pcm_duration_ms(pcm)
    try:
        stt = get_stt()
        res = stt.transcribe(pcm)
        result = TurnResult(
            turn_id=ctx.turn_id, ok=True, text=res.text, language=res.language,
            duration_ms=res.duration_ms, stt_ms=res.latency_ms,
            stt_provider=res.provider, stt_model=res.model,
        )
    except STTRateLimited as err:
        result = TurnResult(turn_id=ctx.turn_id, ok=False, duration_ms=duration_ms,
                            error_code=ErrorCode.RATE_LIMITED, error_detail=str(err))
    except STTError as err:
        result = TurnResult(turn_id=ctx.turn_id, ok=False, duration_ms=duration_ms,
                            error_code=ErrorCode.STT_FAILED, error_detail=str(err))
    except Exception as err:  # never let a turn crash the socket
        logger.exception("[VOICE] turn=%s speech-to-text crashed", ctx.turn_id)
        result = TurnResult(turn_id=ctx.turn_id, ok=False, duration_ms=duration_ms,
                            error_code=ErrorCode.STT_FAILED,
                            error_detail=f"{type(err).__name__}: {str(err)[:200]}")

    logger.info(
        "[VOICE] turn=%s user=%s audio_ms=%s stt_ms=%s truncated=%s status=%s%s",
        ctx.turn_id, ctx.user_id, result.duration_ms, result.stt_ms, ctx.truncated,
        "ok" if result.ok else "failed", "" if result.ok else f" error={result.error_code} ({result.error_detail})",
    )
    return result


def decide_reply(ctx: TurnContext, result: TurnResult) -> None:
    """Stage 2a: the agent (one LLM call). Empty transcript -> a fixed reply, no LLM call."""
    text = (result.text or "").strip()
    if not text:
        result.reply_text, result.ui_actions, result.action, result.llm_ms = EMPTY_TRANSCRIPT_REPLY, [], "unclear", 0
        return
    try:
        agent = run_agent(text, result.language, user_id=ctx.user_id,
                          conversation_id=ctx.conversation_id or ctx.session_id,
                          screen=ctx.screen, trip=ctx.trip, location=ctx.location, screen_place=ctx.screen_place)
    except Exception as exc:  # run_agent doesn't raise, but a turn must never crash here
        from voice.agent import FALLBACK_REPLY, crash_error_info
        logger.exception("[VOICE] turn=%s agent crashed", ctx.turn_id)   # server log only: full traceback
        result.reply_text, result.ui_actions, result.action, result.llm_ms = FALLBACK_REPLY, [], "error", 0
        result.agent_error_info = crash_error_info(exc)
        result.agent_error_code, result.agent_error_detail = "agent_crashed", result.agent_error_info["detail"]
        return
    result.reply_text, result.ui_actions, result.action, result.llm_ms, result.tool_ms, result.note = (
        agent.reply_text, agent.ui_actions, agent.action, agent.llm_ms, agent.tool_ms, agent.note)
    result.note_attribution = getattr(agent, "note_attribution", None)
    result.pending_confirmation = agent.pending_confirmation
    result.agent_error_code, result.agent_error_detail = agent.error_code, agent.error_detail
    result.agent_error_info = dict(agent.error_info or {})


def make_reply(ctx: TurnContext, result: TurnResult) -> TurnResult:
    """Stage 2: agent decision + Sarvam audio. Fills the reply fields; never raises."""
    decide_reply(ctx, result)
    if result.action == "error" or result.agent_error_code:
        info = result.agent_error_info or {}
        attempt = f"{info['attempt']}/{info.get('attempts') or 2}" if info.get("attempt") else "-"
        logger.warning("[VOICE] turn=%s agent_error=%s status=%s attempt=%s action=%s", ctx.turn_id,
                       result.agent_error_code or "-", info.get("status") or "-", attempt, result.action)
    # The voice follows the reply's own words (Hinglish -> hi-IN, plain English -> en-IN), not Whisper's tag.
    result.reply_language = detect_lang(result.reply_text, result.language)
    try:
        audio, mime, tts_ms, err = synthesize_reply(result.reply_text, result.reply_language)
    except Exception as exc:  # synthesize_reply doesn't raise, but a turn must never crash here
        logger.exception("[VOICE] turn=%s text-to-speech crashed", ctx.turn_id)
        audio, mime, tts_ms, err = None, REPLY_MIME, 0, f"{type(exc).__name__}: {str(exc)[:200]}"
    result.reply_audio_b64, result.reply_mime, result.tts_ms, result.tts_error = audio, mime, tts_ms, err
    # tts_disabled / empty_text are settings, not failures; a real failure (Sarvam limit, key, network) is a warning.
    logger.log(logging.WARNING if tts_failed(result) else logging.INFO, "[VOICE] turn=%s tts_ms=%s tts_status=%s",
               ctx.turn_id, tts_ms, "ok" if not err else f"failed ({err})")
    return result


def tts_failed(result: TurnResult) -> bool:
    """A real TTS failure (Sarvam limit, key, network); tts_disabled / empty_text are settings, not failures."""
    return bool(result.tts_error) and result.tts_error not in ("tts_disabled", "empty_text")


def failure_reason(result: TurnResult) -> Tuple[Optional[str], Optional[str]]:
    """The one failure reason of a turn, for the debug store and voice_errors.md:
    STT failed -> (stt code, detail); agent failed -> (agent code, detail); else a real TTS failure ->
    ("tts_failed", tts_error); else (None, None)."""
    if not result.ok:
        return result.error_code or ErrorCode.STT_FAILED, result.error_detail
    if result.agent_error_code:
        return result.agent_error_code, result.agent_error_detail
    if tts_failed(result):
        return ErrorCode.TTS_FAILED, result.tts_error
    return None, None


def after_turn(pcm: bytes, ctx: TurnContext, result: TurnResult, total_ms: int) -> None:
    """Last stage, after the app has its answer. Failures here are logged, never raised."""
    turn_index: Optional[int] = None
    if debug_store.enabled():
        try:
            turn_index = debug_store.save_speech(pcm, ctx, result, total_ms)
        except Exception as err:
            logger.warning("[VOICE DEBUG STORE] save failed for turn=%s: %s: %s", ctx.turn_id, type(err).__name__,
                           str(err)[:200])
    if debug_store.test_mode() and error_log.should_log(result):
        try:
            error_log.append(ctx, result, total_ms, turn_index)
        except Exception as err:  # the error log must never break a turn
            logger.warning("[VOICE] error log write failed for turn=%s: %s", ctx.turn_id, type(err).__name__)


def end_session(user_id: str, session_id: str, conversation_ids: Optional[List[str]] = None) -> None:
    # The agent's conversation memory goes with the session (step 2).
    from voice.agent import clear_memory
    from redis_client import redis_conn
    for conversation_id in (conversation_ids or []):
        clear_memory(redis_conn, user_id, conversation_id)
    if not debug_store.enabled():
        return
    try:
        debug_store.end_session(user_id, session_id)
    except Exception as err:
        logger.warning("[VOICE DEBUG STORE] end_session failed for session=%s: %s: %s", session_id, type(err).__name__, str(err)[:200])
