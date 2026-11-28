"""
Message shapes for /ws/voice, in one place.

App -> server (text frames, JSON):
  {"type": "auth", "token": "..."}                       only when the login cookie isn't sent
  {"type": "start", "conversation_id": "...", "screen": "/trip", "trip_id": "..." | null,
   "language": "auto" | "hi" | "en" | "bn"}   the user's voice language (voice/languages.py; unknown -> "auto")
                                                          trip_id is ownership-checked; not yours = none
  {"type": "stop"}
  {"type": "end_session"}
  {"type": "confirm", "conversation_id", "pending_id", "language"?}  the Confirm card's button (same action as voice
                                                          "haan"); "language" as in start (also on "cancel")
  {"type": "cancel", "conversation_id", "pending_id"}   the Cancel button: the draft is dropped, nothing saved
  {"type": "draft_done", "conversation_id"}            the wizard created the trip (e.g. Proceed tapped): clear the draft
App -> server (binary frames): raw PCM, 16 kHz, 16-bit little-endian, mono, ~100 ms per frame.

Server -> app (text frames, JSON):
  {"type": "ready"}                                       login accepted
  {"type": "recording", "turn_id": "..."}                 start accepted, send audio now
  {"type": "transcript", "turn_id", "text", "language", "duration_ms", "latency_ms", "truncated"}
                                                          sent as soon as speech-to-text finishes
  {"type": "reply", "turn_id", "reply_text", "reply_audio_base64" | null, "mime": "audio/wav", "tts_ms",
   "ui_actions": [{"type": "navigate", "to": "/map"}, {"type": "refresh", "what": "itinerary"}], "action": "navigate:<page>" | "answer" | "map_focus" | "list_trips" | "open_trip" | "reply" | "error",
   "llm_ms", "tool_ms", "note" (small on-screen text, never spoken, or null),
   "pending_confirmation": {"id", "summary", "title"?} | null,  step 4/5/6: show the Confirm card
   "note_attribution"?,                                    "Google Maps" when the note is Google Maps content
   "error_code"?, "error_detail"?, "tts_error"?}          only when something failed: the reason (codes/status/class
                                                          names, never user text); also written to the test-only
                                                          debug store and logs/voice_errors.md
  {"type": "confirm_result", "pending_id", "ok", "reply_text", "ui_actions"}
                                                          answer to confirm / cancel (ok=false: nothing to confirm)
                                                          the agent's spoken reply (steps 1b + 2), after
                                                          "transcript"; the app runs ui_actions first
  {"type": "error", "code": "...", "message": "...", "turn_id"?}
                                                          a failed reply sends "reply" (audio null), then
                                                          an error with code "tts_failed"
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
    RATE_LIMITED = "rate_limited"        # our per-user limit or OpenAI's
    STT_FAILED = "stt_failed"
    UNAVAILABLE = "unavailable"          # limiter/Redis down: fail closed
    TTS_FAILED = "tts_failed"            # the spoken reply couldn't be made (the turn still worked)
    TURN_CRASHED = "turn_crashed"        # an unexpected exception while handling the turn


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
    ErrorCode.TTS_FAILED: "Couldn't play the reply.",
    ErrorCode.TURN_CRASHED: "Something went wrong. Please try again.",
}


def error(code: str, message: Optional[str] = None, turn_id: Optional[str] = None,
          detail: Optional[str] = None) -> Dict[str, Any]:
    msg: Dict[str, Any] = {"type": "error", "code": code, "message": message or ERROR_MESSAGES.get(code, "Voice error.")}
    if turn_id:
        msg["turn_id"] = turn_id
    if detail:
        msg["detail"] = detail  # the technical reason (status/code/exception): for the console and test panel, not users
    return msg


def ready() -> Dict[str, Any]:
    return {"type": "ready"}


def recording(turn_id: str) -> Dict[str, Any]:
    return {"type": "recording", "turn_id": turn_id}


def reply(turn_id: str, reply_text: str, audio_base64: Optional[str], mime: str, tts_ms: int,
          ui_actions: Optional[list] = None, action: str = "reply", llm_ms: int = 0,
          tool_ms: int = 0, note: Optional[str] = None,
          pending_confirmation: Optional[Dict[str, Any]] = None,
          note_attribution: Optional[str] = None, error_code: Optional[str] = None,
          error_detail: Optional[str] = None, tts_error: Optional[str] = None) -> Dict[str, Any]:
    out = {
        "type": "reply",
        "turn_id": turn_id,
        "reply_text": reply_text,
        "reply_audio_base64": audio_base64,
        "mime": mime,
        "tts_ms": tts_ms,
        "ui_actions": ui_actions or [],
        "action": action,
        "llm_ms": llm_ms,
        "tool_ms": tool_ms,
        "note": note,
        "pending_confirmation": pending_confirmation,
    }
    if note and note_attribution:
        out["note_attribution"] = note_attribution   # e.g. "Google Maps" for a Google route warning
    # Why a turn went wrong, for the browser console and the test panel. Sent only when set.
    for key, value in (("error_code", error_code), ("error_detail", error_detail), ("tts_error", tts_error)):
        if value:
            out[key] = value
    return out


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


def confirm_result(pending_id: Optional[str], ok: bool, reply_text: str, ui_actions: Optional[list] = None) -> Dict[str, Any]:
    return {"type": "confirm_result", "pending_id": pending_id, "ok": ok, "reply_text": reply_text, "ui_actions": ui_actions or []}
