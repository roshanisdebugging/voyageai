"""
Spoken reply for a voice turn (voicefirst.md step 1b), via Sarvam (tts_service.py).

VOICE_TTS_ENABLED       true (default) / false
VOICE_TTS_SPEAKER       bulbul:v3: a v3 name (default "ritu"); bulbul:v4-flash: a v4 voice ID, passed through as is
                        (e.g. aayan_hi_conversational)
SARVAM_TTS_MODEL        default bulbul:v3 (e.g. bulbul:v4-flash)
SARVAM_TTS_PACE         default 1.0 (0.5 - 2.0)
SARVAM_TTS_SAMPLE_RATE  default 22050 (e.g. 24000); always WAV
SARVAM_API_KEY          shared with the rest of the app
Replies are cut at a sentence boundary to 480 characters (tts_service.VOICE_REPLY_MAX_CHARS).

Never cached: a reply can contain the user's own words, so synthesize_speech_sarvam is
called with use_cache=False (no Redis read or write). Logs never contain the text.
"""
import os
import time
from typing import Optional, Tuple

REPLY_MIME = "audio/wav"  # Sarvam returns WAV at SARVAM_TTS_SAMPLE_RATE; the browser decodes any rate

# STT language code -> Sarvam target_language_code. Urdu speech is spoken back in Hindi.
LANGUAGE_TO_SARVAM = {"hi": "hi-IN", "ur": "hi-IN", "en": "en-IN"}
DEFAULT_SARVAM_LANGUAGE = "hi-IN"


def sarvam_language(stt_language: Optional[str]) -> str:
    return LANGUAGE_TO_SARVAM.get((stt_language or "").strip().lower(), DEFAULT_SARVAM_LANGUAGE)


def tts_enabled() -> bool:
    return (os.getenv("VOICE_TTS_ENABLED") or "true").strip().lower() != "false"


def tts_speaker() -> str:
    """bulbul:v3 default "ritu"; for other models tts_service.resolve_speaker uses VOICE_TTS_SPEAKER as given."""
    return (os.getenv("VOICE_TTS_SPEAKER") or "ritu").strip() or "ritu"


def synthesize_reply(text: str, stt_language: Optional[str]) -> Tuple[Optional[str], str, int, Optional[str]]:
    """
    Returns (audio_base64 | None, mime, tts_ms, error | None). Blocking (HTTP): call it from a
    threadpool. Never raises.
    """
    if not tts_enabled():
        return None, REPLY_MIME, 0, "tts_disabled"
    if not text or not text.strip():
        return None, REPLY_MIME, 0, "empty_text"
    started = time.perf_counter()
    try:
        from tts_service import SarvamTTSError, synthesize_speech_sarvam
        audio = synthesize_speech_sarvam(
            text=text,
            target_language_code=sarvam_language(stt_language),
            speaker=tts_speaker(),
            use_cache=False,
            raise_errors=True,
        )
    except Exception as err:
        elapsed = int((time.perf_counter() - started) * 1000)
        try:
            is_sarvam = isinstance(err, SarvamTTSError)
        except NameError:  # the tts_service import itself failed
            is_sarvam = False
        # Sarvam reasons are status/code only. Anything else: the type plus a short message.
        detail = f"sarvam: {err}" if is_sarvam else f"{type(err).__name__}: {str(err)[:200]}"
        return None, REPLY_MIME, elapsed, detail
    tts_ms = int((time.perf_counter() - started) * 1000)
    if not audio:
        return None, REPLY_MIME, tts_ms, "sarvam_failed"
    return audio, REPLY_MIME, tts_ms, None
