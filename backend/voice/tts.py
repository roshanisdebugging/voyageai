"""
Spoken reply for a voice turn (voicefirst.md step 1b), via Sarvam bulbul:v3.

VOICE_TTS_ENABLED   true (default) / false
VOICE_TTS_SPEAKER   default "ritu"
SARVAM_API_KEY      shared with the rest of the app

Never cached: a reply can contain the user's own words, so synthesize_speech_sarvam is
called with use_cache=False (no Redis read or write). Logs never contain the text.
"""
import os
import time
from typing import Optional, Tuple

REPLY_MIME = "audio/wav"  # bulbul:v3 returns WAV (speech_sample_rate 22050)

# STT language code -> Sarvam target_language_code. Urdu speech is spoken back in Hindi.
LANGUAGE_TO_SARVAM = {"hi": "hi-IN", "ur": "hi-IN", "en": "en-IN"}
DEFAULT_SARVAM_LANGUAGE = "hi-IN"


def sarvam_language(stt_language: Optional[str]) -> str:
    return LANGUAGE_TO_SARVAM.get((stt_language or "").strip().lower(), DEFAULT_SARVAM_LANGUAGE)


def tts_enabled() -> bool:
    return (os.getenv("VOICE_TTS_ENABLED") or "true").strip().lower() != "false"


def tts_speaker() -> str:
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
        from tts_service import synthesize_speech_sarvam
        audio = synthesize_speech_sarvam(
            text=text,
            target_language_code=sarvam_language(stt_language),
            speaker=tts_speaker(),
            use_cache=False,
        )
    except Exception as err:
        return None, REPLY_MIME, int((time.perf_counter() - started) * 1000), type(err).__name__
    tts_ms = int((time.perf_counter() - started) * 1000)
    if not audio:
        return None, REPLY_MIME, tts_ms, "sarvam_failed"
    return audio, REPLY_MIME, tts_ms, None
