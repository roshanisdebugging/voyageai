"""
TEST ONLY: a readable log of failed voice turns, backend/logs/voice_errors.md (gitignored).

Written only when VOICE_DEBUG_STORE=true. One entry per turn that failed (action "error"), carries an agent
error_code, or whose speech-to-text or Sarvam TTS failed, newest at the bottom. Over 1 MB, the file is renamed to voice_errors.<date>.md and a new one starts.

Entries hold IDs, stage, model, attempt, timings and status/code names only: never the user's words,
the transcript, tool arguments, reply text or the provider's response body (OpenAI, Sarvam).
The caller must catch every error from append(): a log write must never break a turn.
"""
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:  # avoid an import cycle with pipeline.py
    from voice.pipeline import TurnContext, TurnResult

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IST = timezone(timedelta(hours=5, minutes=30))
MAX_BYTES = 1024 * 1024
_lock = threading.Lock()


def log_path() -> str:
    return (os.getenv("VOICE_ERROR_LOG_PATH") or "").strip() or os.path.join(BACKEND_DIR, "logs", "voice_errors.md")


def _safe(value: Any, limit: int = 120) -> str:
    """IDs and code names only: letters, digits and a few separators; no newlines or markdown."""
    text = "" if value is None else str(value)
    return "".join(ch for ch in text if ch.isalnum() or ch in "-_.:/=,() ")[:limit].strip() or "-"


def should_log(result: "TurnResult") -> bool:
    from voice.pipeline import failure_reason
    return result.action == "error" or failure_reason(result)[0] is not None


def format_entry(ctx: "TurnContext", result: "TurnResult", total_ms: int, turn_index: Optional[int] = None) -> str:
    when = ctx.started_at.astimezone(IST).strftime("%Y-%m-%d %H:%M:%S")
    turn = turn_index if turn_index is not None else (ctx.turn_number or "?")
    info: Dict[str, Any] = result.agent_error_info or {}
    if not result.ok:   # speech to text failed: no agent ran
        action, code, stage = "stt_failed", result.error_code, "stt"
        model, detail, tool = result.stt_model or os.getenv("VOICE_STT_MODEL") or "", result.error_detail, None
    elif not result.agent_error_code and result.action != "error":   # the reply worked, its audio didn't
        from voice.pipeline import failure_reason
        action, stage, tool = result.action, "tts", None
        code, detail = failure_reason(result)
        model = "sarvam"
    else:
        action, code = result.action, result.agent_error_code
        stage = info.get("stage") or "agent"
        if info.get("attempt"):
            stage += f" (attempt {info['attempt']} of {info.get('attempts') or 2})"
        model, tool = info.get("model") or "", info.get("tool")
        detail = info.get("detail") or result.agent_error_detail
    lines = [
        f"## {when} IST | turn {_safe(turn)} | {_safe(action)} | {_safe(code)}",
        f"- session: {_safe(ctx.session_id)}   user: {_safe(ctx.user_id)}   "
        f"conversation: {_safe(ctx.conversation_id)}   turn_id: {_safe(ctx.turn_id)}",
        f"- stage: {_safe(stage)}" + (f"   model: {_safe(model)}" if model else ""),
        f"- detail: {_safe(detail, 300)}",
        f"- timings: stt {result.stt_ms} ms, llm {result.llm_ms} ms, total {total_ms} ms",
        f"- tool in progress: {_safe(tool) if tool else 'none'}",
    ]
    return "\n".join(lines) + "\n\n"


def _rotate(path: str) -> None:
    if not os.path.exists(path) or os.path.getsize(path) <= MAX_BYTES:
        return
    now = datetime.now(IST)
    base, ext = os.path.splitext(path)
    target = f"{base}.{now:%Y-%m-%d}{ext}"
    if os.path.exists(target):
        target = f"{base}.{now:%Y-%m-%d-%H%M%S}{ext}"
    os.replace(path, target)


def append(ctx: "TurnContext", result: "TurnResult", total_ms: int, turn_index: Optional[int] = None) -> None:
    entry = format_entry(ctx, result, total_ms, turn_index)
    path = log_path()
    with _lock:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _rotate(path)
        with open(path, "a", encoding="utf-8") as f:
            f.write(entry)
