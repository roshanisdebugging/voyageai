"""
Sarvam TTS settings (bulbul:v4-flash switch): model / speaker / pace / sample rate from env, the request body (current
REST field names text + language_code, WAV), the cache key, v4 speaker pass-through, the v3 speaker mapping,
sentence-boundary trimming, the en-IN -> hi-IN retry for a Hindi v4 voice, and the failure reasons.
Sarvam is simulated (requests.post); Redis = local (only this test's audio:v2:* keys are written, then deleted).
Run from backend/: python -m tests.test_sarvam_tts
"""
import os
import sys
import uuid
from pathlib import Path
from unittest import mock

import dotenv

dotenv.load_dotenv = lambda *a, **k: None
BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)
for k in ("SARVAM_TTS_MODEL", "SARVAM_TTS_PACE", "SARVAM_TTS_SAMPLE_RATE", "VOICE_TTS_SPEAKER", "VOICE_TTS_ENABLED"):
    os.environ.pop(k, None)
os.environ["SARVAM_API_KEY"] = "test-key-not-real"

import tts_service as T  # noqa: E402
from redis_client import redis_conn  # noqa: E402
from voice import tts as VT  # noqa: E402

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail != "" else ""), flush=True)


class FakeSarvam:
    """requests.post stand-in. queue items: (status, body) or "ok"."""
    calls = []
    queue = []

    def __call__(self, url, json=None, headers=None, timeout=None):
        FakeSarvam.calls.append({"url": url, "json": json, "headers": headers})
        item = FakeSarvam.queue.pop(0) if FakeSarvam.queue else "ok"
        resp = mock.Mock()
        if item == "ok":
            resp.status_code = 200
            resp.json.return_value = {"request_id": "r1", "audios": ["UklGRgAAAABXQVZF"]}
        else:
            resp.status_code, body = item
            resp.json.return_value = body
        return resp


def env(**kw):
    for k in ("SARVAM_TTS_MODEL", "SARVAM_TTS_PACE", "SARVAM_TTS_SAMPLE_RATE", "VOICE_TTS_SPEAKER"):
        os.environ.pop(k, None)
    os.environ.update({k: str(v) for k, v in kw.items()})


def run(text="Namaste! Map khol diya.", lang="hi-IN", speaker="ritu", **kw):
    FakeSarvam.calls = []
    return T.synthesize_speech_sarvam(text=text, target_language_code=lang, speaker=speaker, use_cache=False,
                                      raise_errors=True, **kw)


fake = mock.patch.object(T.requests, "post", FakeSarvam())
fake.start()

# ---------------- defaults (env unset): unchanged behaviour
env()
run()
body = FakeSarvam.calls[0]["json"]
check("defaults: bulbul:v3, pace 1.0, 22050 Hz, speaker ritu", body["model"] == "bulbul:v3" and body["pace"] == 1.0
      and body["speech_sample_rate"] == 22050 and body["speaker"] == "ritu", body)
check("current REST field names: text (string) + language_code, no inputs / target_language_code",
      body["text"] == "Namaste! Map khol diya." and body["language_code"] == "hi-IN"
      and "inputs" not in body and "target_language_code" not in body, sorted(body))
check("WAV output: no codec override (WAV is Sarvam's default); voice mime stays audio/wav",
      "output_audio_codec" not in body and VT.REPLY_MIME == "audio/wav")
check("endpoint + auth header unchanged", FakeSarvam.calls[0]["url"] == "https://api.sarvam.ai/text-to-speech"
      and FakeSarvam.calls[0]["headers"]["api-subscription-key"] == "test-key-not-real")

# ---------------- the settings I will use
env(SARVAM_TTS_MODEL="bulbul:v4-flash", VOICE_TTS_SPEAKER="aayan_hi_conversational", SARVAM_TTS_PACE="1.05",
    SARVAM_TTS_SAMPLE_RATE="24000")
audio, mime, ms, err = VT.synthesize_reply("Hawa Mahal yahan se 6.8 km hai.", "hi")
body = FakeSarvam.calls[-1]["json"]
check("v4-flash from env: model, speaker passed through, pace 1.05, 24000 Hz",
      body["model"] == "bulbul:v4-flash" and body["speaker"] == "aayan_hi_conversational" and body["pace"] == 1.05
      and body["speech_sample_rate"] == 24000 and err is None and mime == "audio/wav", body)
run(speaker="meera")
check("v4: a caller's v3 name ('meera') is never mapped to ritu: VOICE_TTS_SPEAKER is used",
      FakeSarvam.calls[0]["json"]["speaker"] == "aayan_hi_conversational")
check("v4: the speaker ID keeps its exact spelling", T.resolve_speaker("x", "bulbul:v4-flash") == "aayan_hi_conversational")
env(SARVAM_TTS_MODEL="bulbul:v4-flash")
check("v4 without VOICE_TTS_SPEAKER: a v4 ID from the caller passes through", T.resolve_speaker("shubh_enhi_ads", "bulbul:v4-flash") == "shubh_enhi_ads")
run(speaker="ritu")
check("v4 without VOICE_TTS_SPEAKER: a v3 name is dropped (Sarvam's default v4 voice), never 'ritu'",
      "speaker" not in FakeSarvam.calls[0]["json"], FakeSarvam.calls[0]["json"].get("speaker"))

# ---------------- v3 mapping unchanged
check("v3 mapping: ritu, meera -> ritu, arvind -> rahul, unknown -> ritu, shubh kept",
      [T.resolve_speaker(s, "bulbul:v3") for s in ("ritu", "Meera", "arvind", "aayan_hi_conversational", "shubh")]
      == ["ritu", "ritu", "rahul", "ritu", "shubh"])

# ---------------- bad env values fall back to the defaults
env(SARVAM_TTS_PACE="9", SARVAM_TTS_SAMPLE_RATE="12345")
check("pace outside 0.5-2.0 -> 1.0; unknown sample rate -> 22050", T.tts_pace() == 1.0 and T.tts_sample_rate() == 22050)
env(SARVAM_TTS_PACE="abc", SARVAM_TTS_SAMPLE_RATE="abc")
check("non-numbers -> defaults", T.tts_pace() == 1.0 and T.tts_sample_rate() == 22050)

# ---------------- cache key
k_old = T.cache_key("x", "ChIJpoi", "hi-IN", "bulbul:v3", "ritu", 1.0, 22050)
k_new = T.cache_key("x", "ChIJpoi", "hi-IN", "bulbul:v4-flash", "aayan_hi_conversational", 1.05, 24000)
check("cache key holds model, speaker, pace, sample rate", all(p in k_new for p in ("bulbul:v4-flash", "aayan_hi_conversational", ":1.05:", ":24000")), k_new)
check("v3/ritu and v4/aayan keys differ; pace or rate alone changes the key", k_old != k_new
      and T.cache_key("x", "ChIJpoi", "hi-IN", "bulbul:v4-flash", "aayan_hi_conversational", 1.0, 24000) != k_new
      and T.cache_key("x", "ChIJpoi", "hi-IN", "bulbul:v4-flash", "aayan_hi_conversational", 1.05, 22050) != k_new)
check("new keys never match the old format (audio:poi:{id}:{lang}:{speaker})", not k_new.startswith("audio:poi:")
      and k_new.startswith("audio:v2:poi:"))
# an old v3 entry in Redis is not served after the switch
poi = f"ChIJtest{uuid.uuid4().hex[:8]}"
old_key = f"audio:poi:{poi}:hi-IN:ritu"
redis_conn.setex(old_key, 60, "OLD_V3_AUDIO")
env(SARVAM_TTS_MODEL="bulbul:v4-flash", VOICE_TTS_SPEAKER="aayan_hi_conversational", SARVAM_TTS_PACE="1.05",
    SARVAM_TTS_SAMPLE_RATE="24000")
FakeSarvam.calls = []
got = T.synthesize_speech_sarvam(text="Hawa Mahal ki kahani.", target_language_code="hi-IN", speaker="ritu", poi_id=poi,
                                 max_chars=2000)
check("after the switch the old v3/ritu audio is not served; one Sarvam call", got != "OLD_V3_AUDIO" and len(FakeSarvam.calls) == 1, got)
FakeSarvam.calls = []
again = T.synthesize_speech_sarvam(text="Hawa Mahal ki kahani.", target_language_code="hi-IN", speaker="ritu", poi_id=poi,
                                   max_chars=2000)
check("the new audio is cached under the new key (second call: no Sarvam call)", again == got and FakeSarvam.calls == [])
for k in list(redis_conn.scan_iter(f"audio:*{poi}*")):
    redis_conn.delete(k)

# ---------------- sentence-boundary trimming
long_reply = "Hawa Mahal Jaipur ka sabse mashhoor mahal hai aur subah jaana sabse achha rehta hai. " * 8
cut = T.trim_for_tts(long_reply, 480)
check("cut at the last sentence end within 480, never mid-word", 400 < len(cut) <= 480 and cut.endswith(".")
      and long_reply.startswith(cut), (len(cut), cut[-30:]))
tiny_first = "Haan. " + "yeh ek bahut lamba vakya hai jo khatam hi nahi hota " * 12
cut_t = T.trim_for_tts(tiny_first, 480)
check("a sentence end that would drop over 2/3 of the text: cut at a word instead (never mid-word)",
      len(cut_t) > 160 and not cut_t.endswith("Haan.") and tiny_first.startswith(cut_t) and cut_t.split()[-1] in tiny_first.split(),
      (len(cut_t), cut_t[-20:]))
no_stop = "shabd " * 120
cut2 = T.trim_for_tts(no_stop, 480)
check("no sentence end: cut at a space, never mid-word", len(cut2) <= 480 and cut2.split()[-1] == "shabd" and no_stop.startswith(cut2), cut2[-20:])
hindi = "पहला वाक्य। " * 60
cut3 = T.trim_for_tts(hindi, 480)
check("Devanagari danda counts as a sentence end", len(cut3) <= 480 and cut3.endswith("।"), cut3[-10:])
check("short text unchanged", T.trim_for_tts("Map khol diya.", 480) == "Map khol diya.")
story = ("Yeh mahal 1799 mein bana. " * 100)
check("narration: up to 2000 at a sentence end", 1900 <= len(T.trim_for_tts(story, 2000)) <= 2000 and T.trim_for_tts(story, 2000).endswith("."))
env()
run(text=long_reply)
check("voice replies are trimmed to 480 by default", len(FakeSarvam.calls[0]["json"]["text"]) <= 480)
run(text=story, max_chars=2000)
check("narration callers get up to 2000", 480 < len(FakeSarvam.calls[0]["json"]["text"]) <= 2000)

# ---------------- en-IN with a Hindi v4 voice: retry hi-IN only if Sarvam refuses
env(SARVAM_TTS_MODEL="bulbul:v4-flash", VOICE_TTS_SPEAKER="aayan_hi_conversational")
FakeSarvam.queue = []
FakeSarvam.calls = []
audio, mime, ms, err = VT.synthesize_reply("Your trip is ready.", "en")
check("English reply: en-IN sent as is (Sarvam accepts it)", len(FakeSarvam.calls) == 1
      and FakeSarvam.calls[0]["json"]["language_code"] == "en-IN" and err is None)
FakeSarvam.calls = []
FakeSarvam.queue = [(400, {"error": {"code": "invalid_request_error", "message": "x"}}), "ok"]
audio, mime, ms, err = VT.synthesize_reply("Your trip is ready.", "en")
check("if Sarvam refuses en-IN for a _hi_ voice: one retry with hi-IN", [c["json"]["language_code"] for c in FakeSarvam.calls]
      == ["en-IN", "hi-IN"] and err is None and audio)
env()
FakeSarvam.calls = []
FakeSarvam.queue = [(400, {"error": {"code": "invalid_request_error", "message": "x"}})]
audio, mime, ms, err = VT.synthesize_reply("Your trip is ready.", "en")
check("no retry on v3 (a 400 is just a failure)", len(FakeSarvam.calls) == 1 and err == "sarvam: http_400 invalid_request_error", err)

# ---------------- failure reasons
FakeSarvam.queue = [(429, {"error": {"code": "insufficient_quota_error", "message": "echo of the user's words"}})]
audio, mime, ms, err = VT.synthesize_reply("Map khol diya.", "hi")
check("quota -> 'sarvam: http_429 insufficient_quota_error' (no message text)",
      err == "sarvam: http_429 insufficient_quota_error" and audio is None, err)
FakeSarvam.queue = [(500, {})]
audio, mime, ms, err = VT.synthesize_reply("Map khol diya.", "hi")
check("500 without a code -> 'sarvam: http_500'", err == "sarvam: http_500", err)
FakeSarvam.queue = [(200, {"audios": []})]
audio, mime, ms, err = VT.synthesize_reply("Map khol diya.", "hi")
check("200 without audio -> no_audio_in_response", err == "sarvam: no_audio_in_response", err)
os.environ.pop("SARVAM_API_KEY")
with mock.patch.object(T, "SARVAM_API_KEY", ""):
    audio, mime, ms, err = VT.synthesize_reply("Map khol diya.", "hi")
check("no key -> 'sarvam: no_api_key'", err == "sarvam: no_api_key", err)
os.environ["SARVAM_API_KEY"] = "test-key-not-real"
FakeSarvam.queue = []
check("an unbroken over-long word -> text_not_speakable, no call", (lambda: (FakeSarvam.calls.clear(), VT.synthesize_reply("x" * 900, "hi"))[1])()[3]
      == "sarvam: text_not_speakable" and FakeSarvam.calls == [])

fake.stop()
print(f"\n{sum(results)}/{len(results)} passed", flush=True)
sys.exit(0 if all(results) else 1)
