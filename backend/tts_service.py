import os
import hashlib
import json
import re
import requests
from typing import Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from redis_client import redis_conn

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "")
SARVAM_TTS_URL = "https://api.sarvam.ai/text-to-speech"
AUDIO_CACHE_TTL_SECONDS = 604800  # 7 days
AUDIO_CACHE_VERSION = "v2"        # v2: the key holds model, speaker, pace and sample rate

# Settings (backend/.env). Defaults keep the old behaviour (bulbul:v3, pace 1.0, 22050 Hz).
DEFAULT_TTS_MODEL = "bulbul:v3"
DEFAULT_TTS_PACE = 1.0
DEFAULT_TTS_SAMPLE_RATE = 22050
SAMPLE_RATES = {8000, 16000, 22050, 24000, 32000, 44100, 48000}   # Sarvam REST speech_sample_rate values

# Text limits: Sarvam REST takes up to 2,500 characters; short voice replies stay short for speed.
VOICE_REPLY_MAX_CHARS = 480
NARRATION_MAX_CHARS = 2000

V3_SPEAKERS = {
    'shubh', 'aditya', 'ritu', 'ashutosh', 'priya', 'neha', 'rahul', 'pooja', 'rohan',
    'simran', 'kavya', 'amit', 'dev', 'ishita', 'shreya', 'ratan', 'varun',
    'manan', 'sumit', 'roopa', 'kabir', 'aayan', 'advait', 'anand',
    'tanya', 'tarun', 'sunny', 'mani', 'gokul', 'vijay', 'shruti', 'suhani',
    'mohit', 'kavitha', 'rehan', 'soham', 'rupali'
}


def tts_model() -> str:
    return (os.getenv("SARVAM_TTS_MODEL") or DEFAULT_TTS_MODEL).strip() or DEFAULT_TTS_MODEL


def tts_pace() -> float:
    try:
        pace = float(os.getenv("SARVAM_TTS_PACE") or DEFAULT_TTS_PACE)
    except ValueError:
        return DEFAULT_TTS_PACE
    return pace if 0.5 <= pace <= 2.0 else DEFAULT_TTS_PACE        # Sarvam's range


def tts_sample_rate() -> int:
    try:
        rate = int(float(os.getenv("SARVAM_TTS_SAMPLE_RATE") or DEFAULT_TTS_SAMPLE_RATE))
    except ValueError:
        return DEFAULT_TTS_SAMPLE_RATE
    return rate if rate in SAMPLE_RATES else DEFAULT_TTS_SAMPLE_RATE


def is_v3(model: str) -> bool:
    return model.strip().lower() == "bulbul:v3"


_SENTENCE_END = re.compile(r"[.!?\u0964\u0965](?=\s|$)|\n")


def trim_for_tts(text: str, limit: int) -> str:
    """Up to `limit` characters, cut at the last sentence end that fits; else at the last space; never mid-word."""
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    window = t[:limit + 1]
    ends = [m.end() for m in _SENTENCE_END.finditer(window) if m.end() <= limit]
    if ends and ends[-1] >= limit // 3:
        return window[:ends[-1]].strip()
    space = window.rfind(" ", 0, limit + 1)
    if space > 0:
        return window[:space].rstrip(" ,;:-")
    return ""   # one unbroken "word" longer than the limit: say nothing rather than half a word

class SarvamTTSError(Exception):
    """Why a Sarvam TTS call failed: a status/code, never the response message (it can echo the text)."""


def _sarvam_error_code(response) -> str:
    """The provider's error code only (e.g. insufficient_quota_error), max 40 chars."""
    try:
        err = response.json().get("error")
        code = err.get("code") if isinstance(err, dict) else None
        return str(code or "")[:40]
    except Exception:
        return ""


def resolve_speaker(speaker: Optional[str], model: Optional[str] = None) -> Optional[str]:
    """
    bulbul:v3: the v3 name, old aliases mapped (meera -> ritu, arvind -> rahul), anything unknown -> ritu.
    Any other model (bulbul:v4-flash): its voice IDs differ from v3's, so the ID is passed through exactly as given in
    VOICE_TTS_SPEAKER (never mapped to ritu). Without VOICE_TTS_SPEAKER, a caller's ID that looks like a v4 persona
    (name_lang_style) is passed through; a v3 name is dropped (None: Sarvam uses the model's default voice).
    """
    model = model or tts_model()
    if not is_v3(model):
        configured = (os.getenv("VOICE_TTS_SPEAKER") or "").strip()
        if configured:
            return configured
        given = (speaker or "").strip()
        return given if given.count("_") >= 1 and given.lower() not in V3_SPEAKERS else None
    sp_lower = (speaker or 'ritu').lower().strip()
    if sp_lower in V3_SPEAKERS:
        return sp_lower
    if sp_lower in ('meera', 'pavithra', 'maitreyi', 'female'):
        return 'ritu'
    if sp_lower in ('arvind', 'amartya', 'male'):
        return 'rahul'
    return 'ritu'


def cache_key(text: str, poi_id: Optional[str], language: str, model: str, speaker: Optional[str], pace: float,
              sample_rate: int) -> str:
    """Includes everything that changes the sound, so audio made with another model / voice / pace / rate
    (e.g. bulbul:v3 + ritu) is never served after a switch."""
    voice = f"{language}:{model}:{speaker or 'default'}:{pace:g}:{sample_rate}"
    if poi_id:
        return f"audio:{AUDIO_CACHE_VERSION}:poi:{poi_id}:{voice}"
    text_hash = hashlib.md5(text.encode("utf-8")).hexdigest()[:12]
    return f"audio:{AUDIO_CACHE_VERSION}:text:{text_hash}:{voice}"


def _retry_language(model: str, speaker: Optional[str], language: str) -> Optional[str]:
    """A Hindi v4 persona (e.g. aayan_hi_conversational) refused with en-IN: try hi-IN once for that voice."""
    if is_v3(model) or not speaker or language != "en-IN":
        return None
    parts = speaker.lower().split("_")
    return "hi-IN" if len(parts) >= 2 and parts[1] == "hi" else None


def synthesize_speech_sarvam(
    text: str,
    target_language_code: str = "hi-IN", # 'hi-IN', 'en-IN', 'bn-IN', 'ta-IN', etc. (sent as language_code)
    speaker: Optional[str] = "ritu",     # v3: 'ritu', 'rahul', ...; v4-flash: VOICE_TTS_SPEAKER is used
    poi_id: Optional[str] = None,
    use_cache: bool = True,
    raise_errors: bool = False,
    max_chars: int = VOICE_REPLY_MAX_CHARS,
) -> Optional[str]:
    """
    Speech via Sarvam (SARVAM_TTS_MODEL, default bulbul:v3) as Base64-encoded WAV
    (SARVAM_TTS_SAMPLE_RATE, default 22050 Hz; pace SARVAM_TTS_PACE, default 1.0).
    Text is cut at a sentence boundary to max_chars (voice replies 480, narration up to 2000), never mid-word.
    Redis cache (7 days) for POI narration; the key holds the language, model, speaker, pace and rate.
    use_cache=False skips the Redis cache entirely (no read, no write). Voice replies use it:
    they can contain the user's own words, which must never be stored.
    raise_errors=True raises SarvamTTSError(reason) instead of returning None (voice uses it to
    report why: no_api_key, http_429 <code>, no_audio_in_response, request_failed <Exc>).
    """
    if not text or not text.strip():
        return None

    api_key = os.getenv("SARVAM_API_KEY") or SARVAM_API_KEY
    if not api_key:
        print("[SARVAM TTS WARN] SARVAM_API_KEY is not configured.", flush=True)
        if raise_errors:
            raise SarvamTTSError("no_api_key")
        return None

    model, pace, sample_rate = tts_model(), tts_pace(), tts_sample_rate()
    resolved_spk = resolve_speaker(speaker, model)
    clean_text = trim_for_tts(text, max(1, min(int(max_chars or VOICE_REPLY_MAX_CHARS), 2500)))
    if not clean_text:
        if raise_errors:
            raise SarvamTTSError("text_not_speakable")
        return None
    key = cache_key(clean_text, poi_id, target_language_code, model, resolved_spk, pace, sample_rate)

    # 1. Check Redis Cache
    try:
        cached_audio = redis_conn.get(key) if use_cache else None
        if cached_audio:
            if isinstance(cached_audio, bytes):
                cached_audio = cached_audio.decode("utf-8")
            print(f">>> [REDIS AUDIO HIT] Key: {key} (0ms latency, Rs 0 cost)", flush=True)
            return cached_audio
    except Exception as e:
        print(f"[REDIS AUDIO WARN] Redis read failed: {e}", flush=True)

    # 2. Request body: current REST field names (text, language_code); WAV output (the default codec).
    def body(language: str) -> dict:
        payload = {
            "text": clean_text,
            "language_code": language,
            "pitch": 0,
            "pace": pace,
            "loudness": 1.5,
            "speech_sample_rate": sample_rate,
            "enable_preprocessing": True,
            "model": model,
        }
        if resolved_spk:
            payload["speaker"] = resolved_spk
        return payload

    headers = {
        "api-subscription-key": api_key,
        "Content-Type": "application/json"
    }

    # 3. Call Sarvam TTS Endpoint
    reason = ""
    language = target_language_code
    try:
        response = requests.post(SARVAM_TTS_URL, json=body(language), headers=headers, timeout=6.0)
        fallback = _retry_language(model, resolved_spk, language) if response.status_code == 400 else None
        if fallback:
            print(f"[SARVAM TTS] {resolved_spk} refused {language}; retrying with {fallback}", flush=True)
            language = fallback
            response = requests.post(SARVAM_TTS_URL, json=body(language), headers=headers, timeout=6.0)
        if response.status_code == 200:
            data = response.json()
            audios = data.get("audios", [])
            if not (audios and isinstance(audios, list) and len(audios) > 0):
                reason = "no_audio_in_response"
                print(f"[SARVAM TTS ERROR] {reason}", flush=True)
            else:
                base64_audio = audios[0]

                # Cache in Redis with 7-day TTL (never for use_cache=False)
                if use_cache:
                    try:
                        redis_conn.setex(key, AUDIO_CACHE_TTL_SECONDS, base64_audio)
                        print(f">>> [SARVAM TTS CACHED] Saved audio to Redis key: {key}", flush=True)
                    except Exception as cache_err:
                        print(f"[REDIS AUDIO WARN] Redis write failed: {cache_err}", flush=True)

                return base64_audio
        else:
            # Status + the provider's error code only: the response body can echo the input text.
            reason = f"http_{response.status_code} {_sarvam_error_code(response)}".strip()
            print(f"[SARVAM TTS ERROR] {reason}", flush=True)
    except Exception as e:
        # The server log keeps the full error; the reason sent to the app is the type only.
        reason = f"request_failed {type(e).__name__}"
        print(f"[SARVAM TTS EXCEPTION]: {e}", flush=True)

    if raise_errors:
        raise SarvamTTSError(reason or "unknown")

    return None
