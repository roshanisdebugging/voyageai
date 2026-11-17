import os
import hashlib
import json
import requests
from typing import Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from redis_client import redis_conn

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "")
SARVAM_TTS_URL = "https://api.sarvam.ai/text-to-speech"
AUDIO_CACHE_TTL_SECONDS = 604800  # 7 days

V3_SPEAKERS = {
    'aditya', 'ritu', 'ashutosh', 'priya', 'neha', 'rahul', 'pooja', 'rohan',
    'simran', 'kavya', 'amit', 'dev', 'ishita', 'shreya', 'ratan', 'varun',
    'manan', 'sumit', 'roopa', 'kabir', 'aayan', 'shubh', 'advait', 'anand',
    'tanya', 'tarun', 'sunny', 'mani', 'gokul', 'vijay', 'shruti', 'suhani',
    'mohit', 'kavitha', 'rehan', 'soham', 'rupali'
}

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


def resolve_speaker(speaker: str) -> str:
    sp_lower = (speaker or 'ritu').lower().strip()
    if sp_lower in V3_SPEAKERS:
        return sp_lower
    if sp_lower in ('meera', 'pavithra', 'maitreyi', 'female'):
        return 'ritu'
    if sp_lower in ('arvind', 'amartya', 'male'):
        return 'rahul'
    return 'ritu'

def synthesize_speech_sarvam(
    text: str, 
    target_language_code: str = "hi-IN", # 'hi-IN', 'en-IN', 'bn-IN', 'ta-IN', etc.
    speaker: str = "ritu",               # 'ritu', 'priya', 'rahul', 'aditya', etc.
    poi_id: Optional[str] = None,
    use_cache: bool = True,
    raise_errors: bool = False,
) -> Optional[str]:
    """
    Generates realistic speech via Sarvam AI (bulbul:v3) and returns Base64-encoded WAV audio.
    Employs sub-3ms Redis caching for 0ms latency on repeated POI narratives.
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

    resolved_spk = resolve_speaker(speaker)

    # Determine Redis Cache Key
    if poi_id:
        cache_key = f"audio:poi:{poi_id}:{target_language_code}:{resolved_spk}"
    else:
        text_hash = hashlib.md5(text.encode("utf-8")).hexdigest()[:12]
        cache_key = f"audio:text:{text_hash}:{target_language_code}:{resolved_spk}"

    # 1. Check Redis Cache
    try:
        cached_audio = redis_conn.get(cache_key) if use_cache else None
        if cached_audio:
            if isinstance(cached_audio, bytes):
                cached_audio = cached_audio.decode("utf-8")
            print(f">>> [REDIS AUDIO HIT] Key: {cache_key} (0ms latency, Rs 0 cost)", flush=True)
            return cached_audio
    except Exception as e:
        print(f"[REDIS AUDIO WARN] Redis read failed: {e}", flush=True)

    # 2. Sarvam API Payload (Truncated to 480 chars for ultra-low latency sub-300ms)
    clean_text = text.strip()[:480]
    payload = {
        "inputs": [clean_text],
        "target_language_code": target_language_code,
        "speaker": resolved_spk,
        "pitch": 0,
        "pace": 1.0,
        "loudness": 1.5,
        "speech_sample_rate": 22050,
        "enable_preprocessing": True,
        "model": "bulbul:v3"
    }

    headers = {
        "api-subscription-key": api_key,
        "Content-Type": "application/json"
    }

    # 3. Call Sarvam TTS Endpoint
    reason = ""
    try:
        response = requests.post(SARVAM_TTS_URL, json=payload, headers=headers, timeout=6.0)
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
                        redis_conn.setex(cache_key, AUDIO_CACHE_TTL_SECONDS, base64_audio)
                        print(f">>> [SARVAM TTS CACHED] Saved audio to Redis key: {cache_key}", flush=True)
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
