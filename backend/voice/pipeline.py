"""
One voice turn, run as stages in order.

Stages: run_turn() = speech to text (its result goes to the app at once as "transcript"),
then make_reply() = the spoken reply (step 1b: an echo; step 2 replaces it with the agent).
after_turn() is the last stage, run once the app has its answer; it only feeds the test-only
debug store (testing.md).

These functions are blocking (HTTP, disk, DB): call them from a threadpool.
Logs carry the turn ID, lengths, timings and status. Never the words or the audio.
"""
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from voice import debug_store
from voice.messages import ErrorCode
from voice.stt import STTError, STTRateLimited, get_stt, pcm_duration_ms
from voice.tts import REPLY_MIME, synthesize_reply

EMPTY_TRANSCRIPT_REPLY = "Mujhe kuch sunai nahi diya, phir se boliye."
ECHO_PREFIX = "Aapne kaha: "

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
    truncated: bool = False          # cut at 30 s
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
    error_detail: Optional[str] = None   # for logs/debug store only, never sent to the app
    # Spoken reply (step 1b)
    reply_text: Optional[str] = None
    reply_audio_b64: Optional[str] = None
    reply_mime: str = REPLY_MIME
    tts_ms: int = 0
    tts_error: Optional[str] = None      # None = reply audio ready


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
        result = TurnResult(turn_id=ctx.turn_id, ok=False, duration_ms=duration_ms,
                            error_code=ErrorCode.STT_FAILED, error_detail=type(err).__name__)

    logger.info(
        "[VOICE] turn=%s user=%s audio_ms=%s stt_ms=%s truncated=%s status=%s%s",
        ctx.turn_id, ctx.user_id, result.duration_ms, result.stt_ms, ctx.truncated,
        "ok" if result.ok else "failed", "" if result.ok else f" error={result.error_code} ({result.error_detail})",
    )
    return result


def build_reply_text(transcript: str) -> str:
    """Step 1b: echo what was heard. Step 2 replaces this with the agent's answer."""
    text = (transcript or "").strip()
    return f"{ECHO_PREFIX}{text}" if text else EMPTY_TRANSCRIPT_REPLY


def make_reply(ctx: TurnContext, result: TurnResult) -> TurnResult:
    """Stage 2: reply text + Sarvam audio. Fills the reply fields; never raises."""
    result.reply_text = build_reply_text(result.text)
    try:
        audio, mime, tts_ms, err = synthesize_reply(result.reply_text, result.language)
    except Exception as exc:  # synthesize_reply doesn't raise, but a turn must never crash here
        audio, mime, tts_ms, err = None, REPLY_MIME, 0, type(exc).__name__
    result.reply_audio_b64, result.reply_mime, result.tts_ms, result.tts_error = audio, mime, tts_ms, err
    logger.info("[VOICE] turn=%s tts_ms=%s tts_status=%s", ctx.turn_id, tts_ms, "ok" if not err else f"failed ({err})")
    return result


def after_turn(pcm: bytes, ctx: TurnContext, result: TurnResult, total_ms: int) -> None:
    """Last stage, after the app has its answer. Failures here are logged, never raised."""
    if not debug_store.enabled():
        return
    try:
        debug_store.save_speech(pcm, ctx, result, total_ms)
    except Exception as err:
        logger.warning("[VOICE DEBUG STORE] save failed for turn=%s: %s", ctx.turn_id, type(err).__name__)


def end_session(user_id: str, session_id: str) -> None:
    if not debug_store.enabled():
        return
    try:
        debug_store.end_session(user_id, session_id)
    except Exception as err:
        logger.warning("[VOICE DEBUG STORE] end_session failed for session=%s: %s", session_id, type(err).__name__)
