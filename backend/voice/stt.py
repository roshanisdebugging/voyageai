"""
Speech to text behind a swappable provider.

VOICE_STT_PROVIDER   openai (default). Sarvam / xAI can be added as new classes.
VOICE_STT_MODEL      default gpt-transcribe
VOICE_STT_LANGUAGES  optional comma-separated language codes to pin (e.g. "hi,en"); unset = auto-detect
VOICE_STT_PROMPT     optional spelling hint for romanized Hinglish; unset = built-in hint, empty = none
OPENAI_API_KEY       shared with the rest of the app
"""
import io
import os
import time
import wave
from dataclasses import dataclass
from typing import List, Optional, Protocol

import requests

from voice.messages import CHANNELS, SAMPLE_RATE, SAMPLE_WIDTH, BYTES_PER_SECOND

OPENAI_TRANSCRIBE_URL = "https://api.openai.com/v1/audio/transcriptions"
DEFAULT_STT_MODEL = "gpt-transcribe"
# Nudges the model towards romanized Hinglish spellings for travel talk. Not a translation instruction.
DEFAULT_HINGLISH_PROMPT = "Namaste. Mujhe Delhi se Jaipur jaana hai, 3 din ke liye, budget 20 hazaar. Itinerary dikhao."

def active_prompts() -> List[str]:
    """Every spelling hint sent to speech-to-text (today one: VOICE_STT_PROMPT or the built-in Hinglish hint)."""
    prompt = os.getenv("VOICE_STT_PROMPT", DEFAULT_HINGLISH_PROMPT)
    return [prompt] if prompt and prompt.strip() else []


# A short or silent clip can come back as the hint text itself ("Namaste. Mujhe Delhi se Jaipur jaana hai, 3 din ke
# liye..."). Such a transcript is treated as nothing heard. "Mostly the hint": a run of at least ECHO_MIN_RUN_SHARE of
# the hint's words, in order, that is also at least ECHO_MIN_TEXT_SHARE of what was transcribed.
ECHO_MIN_RUN_SHARE = 0.75
ECHO_MIN_TEXT_SHARE = 0.6


def _longest_common_run(a: List[str], b: List[str]) -> int:
    best = 0
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0] * (len(b) + 1)
        for j, y in enumerate(b, 1):
            if x == y:
                cur[j] = prev[j - 1] + 1
                best = max(best, cur[j])
        prev = cur
    return best


def is_prompt_echo(text: str, prompts: Optional[List[str]] = None) -> bool:
    """True when the transcript is the STT hint, contains the whole hint, or is mostly made of it."""
    from voice.text_utils import words
    said = words(text)
    if not said:
        return False
    for prompt in (active_prompts() if prompts is None else prompts):
        hint = words(prompt)
        if not hint:
            continue
        run = _longest_common_run(said, hint)
        if run == len(hint) or (run >= ECHO_MIN_RUN_SHARE * len(hint) and run >= ECHO_MIN_TEXT_SHARE * len(said)):
            return True
    return False


# A response that reports the language as a name ("hindi", Whisper-style verbose_json) gets a short code too.
LANGUAGE_CODES = {"english": "en", "hindi": "hi", "urdu": "ur", "marathi": "mr", "bengali": "bn",
                  "tamil": "ta", "telugu": "te", "gujarati": "gu", "punjabi": "pa", "kannada": "kn",
                  "malayalam": "ml", "nepali": "ne"}


class STTError(RuntimeError):
    """Transcription failed. The message is for logs, not for users."""


class STTRateLimited(STTError):
    """The provider's own rate limit was hit (HTTP 429)."""


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

    def transcribe(self, pcm: bytes, languages: Optional[List[str]] = None) -> STTResult: ...


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


def _pinned_languages() -> List[str]:
    raw = os.getenv("VOICE_STT_LANGUAGES") or ""
    return [code.strip() for code in raw.split(",") if code.strip()]


class OpenAITranscribeSTT:
    provider = "openai"

    def __init__(self, model: Optional[str] = None, timeout: float = 20):
        self.model = (model or os.getenv("VOICE_STT_MODEL") or DEFAULT_STT_MODEL).strip()
        self.timeout = timeout

    def transcribe(self, pcm: bytes, languages: Optional[List[str]] = None) -> STTResult:
        """languages: the user's chosen voice language (voice/languages.py) pins the STT; None = as before
        (VOICE_STT_LANGUAGES or auto-detect)."""
        api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
        if not api_key:
            raise STTError("OPENAI_API_KEY is not set")
        prompt = (active_prompts() or [""])[0]
        # A list of tuples so `languages[]` can repeat. gpt-transcribe takes `languages[]`, never `language`.
        data = [("model", self.model)]
        if prompt:
            data.append(("prompt", prompt))
        data += [("languages[]", code) for code in (languages or _pinned_languages())]

        started = time.perf_counter()
        try:
            res = requests.post(
                OPENAI_TRANSCRIBE_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                files={"file": ("speech.wav", pcm_to_wav(pcm), "audio/wav")},
                data=data,
                timeout=self.timeout,
            )
        except requests.RequestException as err:
            raise STTError(f"OpenAI request failed: {type(err).__name__}") from err
        latency_ms = int((time.perf_counter() - started) * 1000)

        if res.status_code == 429:
            raise STTRateLimited("OpenAI rate limit (429)")
        if res.status_code >= 400:
            code = ""
            try:  # the provider's error code only (e.g. invalid_api_key); never the message
                err_obj = res.json().get("error")
                code = str((err_obj.get("code") if isinstance(err_obj, dict) else "") or "")[:40]
            except Exception:
                code = "non_json_body"
            raise STTError(f"OpenAI HTTP {res.status_code} {code}".strip())
        try:
            body = res.json()
        except ValueError as err:
            raise STTError("OpenAI returned non-JSON") from err

        language = None
        detected = body.get("languages")
        if isinstance(detected, list) and detected and isinstance(detected[0], dict):
            language = (str(detected[0].get("code") or "").strip().lower() or None)
        if language is None and isinstance(body.get("language"), str):   # a single language name or code
            name = body["language"].strip().lower()
            language = LANGUAGE_CODES.get(name, name) or None
        return STTResult(
            text=(body.get("text") or "").strip(),
            language=language,
            duration_ms=pcm_duration_ms(pcm),
            latency_ms=latency_ms,
            provider=self.provider,
            model=self.model,
        )


def get_stt() -> SpeechToText:
    name = (os.getenv("VOICE_STT_PROVIDER") or "openai").strip().lower()
    if name == "openai":
        return OpenAITranscribeSTT()
    raise STTError(f"Unknown VOICE_STT_PROVIDER '{name}'")
