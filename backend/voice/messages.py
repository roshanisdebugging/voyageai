"""
Message shapes for /ws/voice, in one place.

App -> server (text frames, JSON):
  {"type": "auth", "token": "..."}                       only when the login cookie isn't sent
  {"type": "start", "conversation_id": "...", "screen": "/trip"}
  {"type": "stop"}
  {"type": "end_session"}
App -> server (binary frames): raw PCM, 16 kHz, 16-bit little-endian, mono, ~100 ms per frame.

Server -> app (text frames, JSON):
  {"type": "ready"}                                       login accepted
  {"type": "recording", "turn_id": "..."}                 start accepted, send audio now
  {"type": "transcript", "turn_id", "text", "language", "duration_ms", "latency_ms", "truncated"}
  {"type": "error", "code": "...", "message": "...", "turn_id"?}
"""
from typing import Any, Dict, Optional

# Audio format the app must send.
SAMPLE_RATE = 16_000
SAMPLE_WIDTH = 2  # bytes (16-bit)
CHANNELS = 1
BYTES_PER_SECOND = SAMPLE_RATE * SAMPLE_WIDTH * CHANNELS  # 32,000

MAX_SECONDS = 30
MAX_BYTES = MAX_SECONDS * BYTES_PER_SECOND  # 960,000 bytes = 960 KB
MIN_MS = 300
MIN_BYTES = MIN_MS * BYTES_PER_SECOND // 1000  # 9,600 bytes


class ErrorCode:
    UNAUTHORIZED = "unauthorized"        # no/invalid/expired login
    BAD_MESSAGE = "bad_message"
    BUSY = "busy"                        # a recording is already running or being transcribed
    NOT_RECORDING = "not_recording"      # stop without start
    TOO_SHORT = "too_short"              # under 0.3 s
    RATE_LIMITED = "rate_limited"        # our per-user limit or Groq's
    STT_FAILED = "stt_failed"
    UNAVAILABLE = "unavailable"          # limiter/Redis down: fail closed


# Messages the app can show as they are.
ERROR_MESSAGES = {
    ErrorCode.UNAUTHORIZED: "Your login has expired. Please log in again.",
    ErrorCode.BAD_MESSAGE: "Something went wrong with the recording. Please try again.",
    ErrorCode.BUSY: "Still working on the last recording. Please wait a moment.",
    ErrorCode.NOT_RECORDING: "No recording was in progress.",
    ErrorCode.TOO_SHORT: "That was too short. Tap, speak, then tap again.",
    ErrorCode.RATE_LIMITED: "Too many voice requests. Try again in a minute.",
    ErrorCode.STT_FAILED: "Couldn't understand the audio right now. Please try again.",
    ErrorCode.UNAVAILABLE: "Voice is unavailable right now. Please try again shortly.",
}


def error(code: str, message: Optional[str] = None, turn_id: Optional[str] = None) -> Dict[str, Any]:
    msg: Dict[str, Any] = {"type": "error", "code": code, "message": message or ERROR_MESSAGES.get(code, "Voice error.")}
    if turn_id:
        msg["turn_id"] = turn_id
    return msg


def ready() -> Dict[str, Any]:
    return {"type": "ready"}


def recording(turn_id: str) -> Dict[str, Any]:
    return {"type": "recording", "turn_id": turn_id}


def transcript(turn_id: str, text: str, language: Optional[str], duration_ms: int, latency_ms: int,
               truncated: bool = False) -> Dict[str, Any]:
    return {
        "type": "transcript",
        "turn_id": turn_id,
        "text": text,
        "language": language,
        "duration_ms": duration_ms,
        "latency_ms": latency_ms,
        "truncated": truncated,
    }
