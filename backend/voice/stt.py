"""
Speech to text behind a swappable provider.

VOICE_STT_PROVIDER  groq (default). Sarvam / xAI can be added as new classes.
VOICE_STT_MODEL     default whisper-large-v3-turbo
VOICE_STT_PROMPT    optional spelling hint for romanized Hinglish; unset = built-in hint, empty = none
GROQ_API_KEY        shared with the rest of the app
"""
import io
import os
import time
import wave
from dataclasses import dataclass
from typing import Optional, Protocol

import requests

from voice.messages import CHANNELS, SAMPLE_RATE, SAMPLE_WIDTH, BYTES_PER_SECOND

GROQ_TRANSCRIBE_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
DEFAULT_STT_MODEL = "whisper-large-v3-turbo"
# Nudges Whisper towards romanized Hinglish spellings for travel talk. Not a translation instruction.
DEFAULT_HINGLISH_PROMPT = "Namaste. Mujhe Delhi se Jaipur jaana hai, 3 din ke liye, budget 20 hazaar. Itinerary dikhao."

# Whisper's verbose_json reports the language as a name; the app gets a short code.
LANGUAGE_CODES = {"english": "en", "hindi": "hi", "urdu": "ur", "marathi": "mr", "bengali": "bn",
                  "tamil": "ta", "telugu": "te", "gujarati": "gu", "punjabi": "pa", "kannada": "kn",
                  "malayalam": "ml", "nepali": "ne"}


class STTError(RuntimeError):
    """Transcription failed. The message is for logs, not for users."""


class STTRateLimited(STTError):
    """The provider's own rate limit was hit (Groq 429)."""


@dataclass
class STTResult:
    text: str
    language: Optional[str]
    duration_ms: int        # length of the audio sent
    latency_ms: int         # request sent -> response received
    provider: str
    model: str


class SpeechToText(Protocol):
    provider: str
    model: str

    def transcribe(self, pcm: bytes) -> STTResult: ...


def pcm_to_wav(pcm: bytes) -> bytes:
    """Wraps raw 16 kHz 16-bit mono PCM in a WAV header."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(CHANNELS)
        w.setsampwidth(SAMPLE_WIDTH)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)
    return buf.getvalue()


def pcm_duration_ms(pcm: bytes) -> int:
    return len(pcm) * 1000 // BYTES_PER_SECOND


class GroqWhisperSTT:
    provider = "groq"

    def __init__(self, model: Optional[str] = None, timeout: float = 20):
        self.model = (model or os.getenv("VOICE_STT_MODEL") or DEFAULT_STT_MODEL).strip()
        self.timeout = timeout

    def transcribe(self, pcm: bytes) -> STTResult:
        api_key = (os.getenv("GROQ_API_KEY") or "").strip()
        if not api_key:
            raise STTError("GROQ_API_KEY is not set")
        prompt = os.getenv("VOICE_STT_PROMPT", DEFAULT_HINGLISH_PROMPT)
        data = {"model": self.model, "response_format": "verbose_json", "temperature": "0"}
        if prompt:
            data["prompt"] = prompt

        started = time.perf_counter()
        try:
            res = requests.post(
                GROQ_TRANSCRIBE_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                files={"file": ("speech.wav", pcm_to_wav(pcm), "audio/wav")},
                data=data,
                timeout=self.timeout,
            )
        except requests.RequestException as err:
            raise STTError(f"Groq request failed: {type(err).__name__}") from err
        latency_ms = int((time.perf_counter() - started) * 1000)

        if res.status_code == 429:
            raise STTRateLimited("Groq rate limit (429)")
        if res.status_code >= 400:
            raise STTError(f"Groq HTTP {res.status_code}")
        try:
            body = res.json()
        except ValueError as err:
            raise STTError("Groq returned non-JSON") from err

        language = (body.get("language") or "").strip().lower() or None
        return STTResult(
            text=(body.get("text") or "").strip(),
            language=LANGUAGE_CODES.get(language, language),
            duration_ms=pcm_duration_ms(pcm),
            latency_ms=latency_ms,
            provider=self.provider,
            model=self.model,
        )


def get_stt() -> SpeechToText:
    name = (os.getenv("VOICE_STT_PROVIDER") or "groq").strip().lower()
    if name == "groq":
        return GroqWhisperSTT()
    raise STTError(f"Unknown VOICE_STT_PROVIDER '{name}'")
