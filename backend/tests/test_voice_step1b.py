"""
Voice step 1b checks (spoken reply): app DB = SQLite, Redis = local, STT and Sarvam simulated.
Run from backend/: python -m tests.test_voice_step1b
The debug-store checks need a LOCAL Postgres admin URL (same rule as test_voice_step1); else skipped.
"""
import base64
import io
import json
import math
import os
import struct
import sys
import tempfile
import time
import wave
from pathlib import Path
from unittest import mock

import dotenv

dotenv.load_dotenv = lambda *a, **k: None
os.environ["DATABASE_URL"] = "postgresql://x:y@127.0.0.1:1/none"
os.environ["AI_PROVIDER"] = "mock"
os.environ["SARVAM_API_KEY"] = "test-key-not-real"
os.environ.pop("VOICE_DEBUG_STORE", None)
os.environ.pop("VOICE_TTS_ENABLED", None)
os.environ.pop("VOICE_TTS_SPEAKER", None)
os.environ["GROQ_API_KEY"] = ""  # the step 2 agent is replaced by an echo stub below

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)
SCRATCH = tempfile.mkdtemp(prefix="voyageai_test_")

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker


def _local_admin_url():
    raw = os.getenv("VOICE_TEST_PG_ADMIN_URL")
    if not raw:
        from dotenv import dotenv_values
        raw = (dotenv_values(BACKEND_DIR / ".env").get("VOICE_DEBUG_DATABASE_URL") or "").strip()
        if raw:
            raw = make_url(raw).set(database="postgres").render_as_string(hide_password=False)
    if raw and (make_url(raw).host or "") in ("localhost", "127.0.0.1", "::1"):
        return raw
    return None


ADMIN_URL = _local_admin_url()
CI_DB = "voice_test_ci_1b"
CI_URL = make_url(ADMIN_URL).set(database=CI_DB).render_as_string(hide_password=False) if ADMIN_URL else None
admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT") if ADMIN_URL else None

import database

database.engine = create_engine(f"sqlite:///{os.path.join(SCRATCH, 'voice1b.db')}", connect_args={"check_same_thread": False})
database.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=database.engine)

import main  # noqa: E402
import tts_service  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from redis_client import redis_conn  # noqa: E402
from voice import debug_store, pipeline  # noqa: E402
from voice import tts as voice_tts  # noqa: E402
from voice.stt import STTResult  # noqa: E402
from voice.agent import AgentResult  # noqa: E402


def echo_agent(text, language, **kw):
    """Step 1b behaviour: echo what was heard. Step 2 (the real agent) is tested in test_voice_step2."""
    return AgentResult(f"Aapne kaha: {text}", action="reply")

main.SessionLocal = database.SessionLocal
database.Base.metadata.create_all(bind=database.engine)
for key in redis_conn.scan_iter("rl:*"):
    redis_conn.delete(key)

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail != "" else ""), flush=True)


ORIGIN = {"origin": "http://localhost:5173"}


def pcm(seconds, freq=440.0):
    n = int(16000 * seconds)
    return b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * freq * i / 16000))) for i in range(n))


def fake_wav_b64():
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(22050); w.writeframes(b"\x00\x00" * 2205)
    return base64.b64encode(buf.getvalue()).decode()


WAV_B64 = fake_wav_b64()


class FakeSTT:
    provider, model = "groq", "whisper-large-v3-turbo"
    text, language = "mujhe jaipur jaana hai", "hi"

    def transcribe(self, audio):
        return STTResult(text=FakeSTT.text, language=FakeSTT.language, duration_ms=len(audio) * 1000 // 32000,
                         latency_ms=111, provider="groq", model=self.model)


class FakeSarvam:
    """Stands in for requests.post to api.sarvam.ai."""
    fail = False
    calls = []

    def __call__(self, url, json=None, headers=None, timeout=None):
        FakeSarvam.calls.append(json)
        resp = mock.Mock()
        if FakeSarvam.fail:
            resp.status_code = 500
            resp.json.return_value = {}
        else:
            resp.status_code = 200
            resp.json.return_value = {"audios": [WAV_B64]}
        return resp


# ---------------- unit checks
check("lang hi -> hi-IN", voice_tts.sarvam_language("hi") == "hi-IN")
check("lang ur -> hi-IN", voice_tts.sarvam_language("ur") == "hi-IN")
check("lang en -> en-IN", voice_tts.sarvam_language("en") == "en-IN")
check("lang ta / None -> hi-IN", voice_tts.sarvam_language("ta") == "hi-IN" and voice_tts.sarvam_language(None) == "hi-IN")
check("empty transcript reply text", pipeline.EMPTY_TRANSCRIPT_REPLY == "Mujhe kuch sunai nahi diya, phir se boliye.")

# ---------------- over the socket
client = TestClient(main.app)
client.__enter__()
r = client.post("/api/auth/register", json={"name": "Voice Reply", "email": "voice1b@example.com", "password": "secret123"})
token = r.json()["token"]
client.cookies.clear()


def recv_until(ws, kinds):
    while True:
        msg = ws.receive_json()
        if msg.get("type") in kinds:
            return msg


def connect():
    ws = client.websocket_connect("/ws/voice", headers=ORIGIN)
    ws.__enter__()
    ws.send_json({"type": "auth", "token": token})
    assert ws.receive_json()["type"] == "ready"
    return ws


def turn(ws, audio):
    """Returns the frames of one turn, in order, up to and including 'reply' (+ a trailing error if any)."""
    ws.send_json({"type": "start", "conversation_id": "c1b", "screen": "/"})
    recv_until(ws, {"recording"})
    for i in range(0, len(audio), 3200):
        ws.send_bytes(audio[i:i + 3200])
    ws.send_json({"type": "stop"})
    frames = []
    while True:
        f = ws.receive_json()
        frames.append(f)
        if f["type"] == "reply":
            break
        if f["type"] == "error" and f.get("code") != "tts_failed":
            return frames
    return frames


def audio_text_keys():
    return set(redis_conn.scan_iter("audio:text:*"))


keys_before = audio_text_keys()
with mock.patch.object(pipeline, "get_stt", lambda: FakeSTT()), mock.patch.object(tts_service.requests, "post", FakeSarvam()), \
        mock.patch.object(pipeline, "run_agent", echo_agent):
    ws = connect()

    frames = turn(ws, pcm(1.5))
    kinds = [f["type"] for f in frames]
    check("transcript first, then reply", kinds[:2] == ["transcript", "reply"], kinds)
    rep = frames[1] if len(frames) > 1 else {}
    check("reply message shape", set(rep) == {"type", "turn_id", "reply_text", "reply_audio_base64", "mime", "tts_ms", "ui_actions", "action", "llm_ms"}
          and rep["turn_id"] == frames[0]["turn_id"] and rep["mime"] == "audio/wav" and isinstance(rep["tts_ms"], int), rep.keys())
    check("reply text is the echo", rep.get("reply_text") == "Aapne kaha: mujhe jaipur jaana hai", rep.get("reply_text"))
    check("reply audio is Sarvam's WAV", rep.get("reply_audio_base64") == WAV_B64)
    sent = FakeSarvam.calls[-1]
    check("Sarvam asked for hi-IN, speaker ritu, bulbul:v3", sent["target_language_code"] == "hi-IN" and sent["speaker"] == "ritu"
          and sent["model"] == "bulbul:v3", {k: sent[k] for k in ("target_language_code", "speaker", "model")})

    FakeSTT.text, FakeSTT.language = "I want to go to Jaipur", "en"
    frames = turn(ws, pcm(1.0))
    check("English speech -> en-IN reply", FakeSarvam.calls[-1]["target_language_code"] == "en-IN")

    FakeSTT.text, FakeSTT.language = "", None
    frames = turn(ws, pcm(1.0))
    check("empty transcript -> 'nothing heard' reply",
          frames[-1]["type"] == "reply" and frames[-1]["reply_text"] == "Mujhe kuch sunai nahi diya, phir se boliye.")

    # TTS failure: reply with null audio + tts_failed; socket stays usable
    FakeSTT.text, FakeSTT.language = "mujhe jaipur jaana hai", "hi"
    FakeSarvam.fail = True
    frames = turn(ws, pcm(1.0))
    nxt = ws.receive_json()
    check("TTS failure: reply with null audio", frames[-1]["type"] == "reply" and frames[-1]["reply_audio_base64"] is None
          and frames[-1]["reply_text"].startswith("Aapne kaha"))
    check("TTS failure: then error tts_failed 'Couldn't play the reply.'",
          nxt.get("type") == "error" and nxt.get("code") == "tts_failed" and nxt.get("message") == "Couldn't play the reply.", nxt)
    FakeSarvam.fail = False
    frames = turn(ws, pcm(1.0))
    check("after a TTS failure the next turn works", [f["type"] for f in frames][:2] == ["transcript", "reply"]
          and frames[1]["reply_audio_base64"] == WAV_B64)

    # Disabled: reply text, no audio, no error
    os.environ["VOICE_TTS_ENABLED"] = "false"
    n_calls = len(FakeSarvam.calls)
    frames = turn(ws, pcm(1.0))
    ws.send_json({"type": "bogus"})
    after = ws.receive_json()
    check("VOICE_TTS_ENABLED=false: reply without audio, no Sarvam call, no tts_failed",
          frames[-1]["type"] == "reply" and frames[-1]["reply_audio_base64"] is None and len(FakeSarvam.calls) == n_calls
          and after.get("code") == "bad_message", after)
    os.environ.pop("VOICE_TTS_ENABLED")

    # VOICE_TTS_SPEAKER
    os.environ["VOICE_TTS_SPEAKER"] = "priya"
    turn(ws, pcm(1.0))
    check("VOICE_TTS_SPEAKER is used", FakeSarvam.calls[-1]["speaker"] == "priya")
    os.environ.pop("VOICE_TTS_SPEAKER")
    ws.__exit__(None, None, None)

    keys_after = audio_text_keys()
    check("voice replies write no audio:text:* keys to Redis", keys_after == keys_before, len(keys_after - keys_before))

    # sanity: the default (other callers) still caches
    probe = "cache probe step1b"
    tts_service.synthesize_speech_sarvam(probe, "hi-IN", "ritu")
    new_keys = audio_text_keys() - keys_after
    check("other callers still cache (use_cache default True)", len(new_keys) == 1)
    for k in new_keys:
        redis_conn.delete(k)

    # ---------------- debug store: reply_text + tts_time_ms, never the reply audio
    if admin:
        with admin.connect() as c:
            c.execute(text(f"DROP DATABASE IF EXISTS {CI_DB}"))
            c.execute(text(f"CREATE DATABASE {CI_DB}"))
        # an old table WITHOUT the 1b columns, as on a machine that ran step 1 before
        eng = create_engine(CI_URL)
        with eng.begin() as c:
            c.execute(text("CREATE TABLE voice_speeches (speech_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, user_id TEXT NOT NULL,"
                           " conversation_id TEXT, turn_index INTEGER NOT NULL, audio_path TEXT, audio_duration_ms INTEGER,"
                           " transcription TEXT, language TEXT, stt_provider TEXT, stt_model TEXT, stt_time_ms INTEGER,"
                           " total_time_ms INTEGER, status VARCHAR(16) NOT NULL, error TEXT, created_at TIMESTAMPTZ NOT NULL)"))
        os.environ["VOICE_DEBUG_STORE"] = "true"
        os.environ["VOICE_DEBUG_DATABASE_URL"] = CI_URL
        os.environ["VOICE_DEBUG_AUDIO_DIR"] = os.path.join(SCRATCH, "audio")
        debug_store._engine = None
        check("debug store starts on an old table (ALTER adds columns)", debug_store.init())
        ws = connect()
        turn(ws, pcm(1.0))
        time.sleep(0.6)
        ws.__exit__(None, None, None)
        time.sleep(0.8)
        with eng.connect() as c:
            row = c.execute(text("SELECT reply_text, tts_time_ms FROM voice_speeches")).mappings().first()
            cols = [r[0] for r in c.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='voice_speeches'"))]
        check("row has reply_text and tts_time_ms", row and row["reply_text"] == "Aapne kaha: mujhe jaipur jaana hai"
              and row["tts_time_ms"] is not None, dict(row) if row else None)
        check("no column holds reply audio", not any("audio" in c and c != "audio_path" and c != "audio_duration_ms" for c in cols), cols)
        eng.dispose()
        debug_store._engine and debug_store._engine.dispose()
        with admin.connect() as c:
            c.execute(text(f"DROP DATABASE IF EXISTS {CI_DB} WITH (FORCE)"))
        os.environ.pop("VOICE_DEBUG_STORE")
    else:
        print("SKIP debug-store checks: no local Postgres admin URL")

client.__exit__(None, None, None)
for key in redis_conn.scan_iter("rl:*"):
    redis_conn.delete(key)
print(f"\n{sum(results)}/{len(results)} passed")
