"""
Voice step 1 backend checks: app DB = SQLite, Redis = local, STT = simulated (no Groq calls),
debug store = a throwaway LOCAL Postgres DB (voice_test_ci, dropped at the end).
Run from backend/: python -m tests.test_voice_step1
The debug-store checks need a LOCAL Postgres admin URL: VOICE_TEST_PG_ADMIN_URL, or else the
user/password of VOICE_DEBUG_DATABASE_URL in backend/.env (database `postgres`). Without one they are skipped.
"""
import json
import math
import os
import struct
import sys
import threading
import time
from unittest import mock

import dotenv

dotenv.load_dotenv = lambda *a, **k: None
os.environ["DATABASE_URL"] = "postgresql://x:y@127.0.0.1:1/none"
os.environ["AI_PROVIDER"] = "mock"
os.environ.pop("VOICE_DEBUG_STORE", None)
os.environ["VOICE_TTS_ENABLED"] = "false"  # step 1 behaviour only; step 1b is tests/test_voice_step1b.py
from pathlib import Path
import tempfile

# backend/ on the import path, so this runs as `python -m tests.<name>` or `python tests/<name>.py` from backend/.
BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)
SCRATCH = tempfile.mkdtemp(prefix="voyageai_test_")
scratch = SCRATCH

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from sqlalchemy.engine import make_url


def _local_admin_url():
    raw = os.getenv("VOICE_TEST_PG_ADMIN_URL")
    if not raw:
        from dotenv import dotenv_values  # read one value; the app's load_dotenv stays disabled
        raw = (dotenv_values(BACKEND_DIR / ".env").get("VOICE_DEBUG_DATABASE_URL") or "").strip()
        if raw:
            raw = make_url(raw).set(database="postgres").render_as_string(hide_password=False)
    if raw and (make_url(raw).host or "") in ("localhost", "127.0.0.1", "::1"):
        return raw
    return None


ADMIN_URL = _local_admin_url()
CI_DB = "voice_test_ci"
CI_URL = make_url(ADMIN_URL).set(database=CI_DB).render_as_string(hide_password=False) if ADMIN_URL else None
admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT") if ADMIN_URL else None
if admin:
    with admin.connect() as c:
        c.execute(text(f"DROP DATABASE IF EXISTS {CI_DB}"))
        c.execute(text(f"CREATE DATABASE {CI_DB}"))

import database

db_path = os.path.join(scratch, "voice1.db")
if os.path.exists(db_path):
    os.remove(db_path)
database.engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
database.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=database.engine)

import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from redis_client import redis_conn  # noqa: E402
from voice import debug_store, pipeline  # noqa: E402
from voice.stt import STTResult, STTError  # noqa: E402

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


class FakeSTT:
    provider, model = "groq", "whisper-large-v3-turbo"
    delay = 0.0
    fail = False
    calls = 0

    def transcribe(self, audio):
        FakeSTT.calls += 1
        time.sleep(FakeSTT.delay)
        if FakeSTT.fail:
            raise STTError("Groq HTTP 500")
        return STTResult(text="mujhe jaipur jaana hai", language="hi", duration_ms=len(audio) * 1000 // 32000,
                         latency_ms=123, provider="groq", model=self.model)


client = TestClient(main.app)
client.__enter__()
r = client.post("/api/auth/register", json={"name": "Voice Tester", "email": "voice1@example.com", "password": "secret123"})
token, user_id = r.json()["token"], r.json()["user"]["id"]
r2 = client.post("/api/auth/register", json={"name": "Other Tester", "email": "voice2@example.com", "password": "secret123"})
token2, user2 = r2.json()["token"], r2.json()["user"]["id"]
client.cookies.clear()


def recv_until(ws, kinds):
    while True:
        msg = ws.receive_json()
        if msg.get("type") in kinds:
            return msg


def connect(tok=token, origin=ORIGIN):
    ws = client.websocket_connect("/ws/voice", headers=origin)
    ws.__enter__()
    ws.send_json({"type": "auth", "token": tok})
    return ws


def turn(ws, audio, chunk=3200):
    ws.send_json({"type": "start", "conversation_id": "conv1", "screen": "/trip"})
    started = recv_until(ws, {"recording", "error"})
    if started["type"] == "error":
        return started
    for i in range(0, len(audio), chunk):
        ws.send_bytes(audio[i:i + chunk])
    ws.send_json({"type": "stop"})
    return recv_until(ws, {"transcript", "error"})


with mock.patch.object(pipeline, "get_stt", lambda: FakeSTT()):
    # ---- login
    with client.websocket_connect("/ws/voice", headers=ORIGIN) as ws:
        ws.send_json({"type": "auth", "token": "not-a-real-token"})
        msg = ws.receive_json()
        check("bad token refused", msg.get("code") == "unauthorized", msg)
    with client.websocket_connect("/ws/voice", headers=ORIGIN) as ws:
        ws.send_json({"type": "start"})
        msg = ws.receive_json()
        check("no login: first message must be auth", msg.get("code") == "unauthorized", msg)
    try:
        with client.websocket_connect("/ws/voice", headers={"origin": "https://evil.example"}) as ws:
            ws.receive_json()
        check("foreign origin refused", False)
    except Exception as err:
        check("foreign origin refused", "4403" in repr(err) or "Disconnect" in type(err).__name__, type(err).__name__)

    # cookie login path
    client.cookies.set("voyageai_session", token)
    with client.websocket_connect("/ws/voice", headers=ORIGIN) as ws:
        check("login by cookie", ws.receive_json().get("type") == "ready")
    client.cookies.clear()

    ws = connect()
    check("login by auth message", ws.receive_json().get("type") == "ready")

    # ---- a normal turn
    msg = turn(ws, pcm(2.0))
    check("transcript returned", msg.get("type") == "transcript" and msg["text"] == "mujhe jaipur jaana hai", msg)
    check("transcript fields", msg.get("language") == "hi" and msg.get("duration_ms") == 2000 and msg.get("latency_ms") == 123
          and msg.get("truncated") is False and msg.get("turn_id", "").startswith("turn_"), msg)

    # ---- too short
    msg = turn(ws, pcm(0.2))
    check("under 0.3 s -> too_short", msg.get("code") == "too_short", msg)

    # ---- stop without start
    ws.send_json({"type": "stop"})
    msg = recv_until(ws, {"error"})
    check("stop without start -> not_recording", msg.get("code") == "not_recording", msg)

    # ---- 40 s is cut at 30 s, the app's late stop is ignored
    calls_before = FakeSTT.calls
    ws.send_json({"type": "start"})
    recv_until(ws, {"recording"})
    audio = pcm(40.0)
    for i in range(0, len(audio), 3200):
        ws.send_bytes(audio[i:i + 3200])
    msg = recv_until(ws, {"transcript", "error"})
    check("40 s recording cut at 30 s", msg.get("type") == "transcript" and msg["duration_ms"] == 30000 and msg["truncated"] is True, msg)
    ws.send_json({"type": "stop"})
    ws.send_json({"type": "bogus"})
    msg = recv_until(ws, {"error", "transcript"})
    check("late stop after the cut is ignored", msg.get("code") == "bad_message", msg)
    check("cut recording transcribed once", FakeSTT.calls - calls_before == 1, FakeSTT.calls - calls_before)

    # ---- busy while transcribing, and /ws/app keeps working meanwhile
    FakeSTT.delay = 2.0
    ws.send_json({"type": "start"})
    recv_until(ws, {"recording"})
    ws.send_bytes(pcm(1.0))
    ws.send_json({"type": "stop"})
    time.sleep(0.2)
    ws.send_json({"type": "start"})
    msg = recv_until(ws, {"error", "recording"})
    check("start while transcribing -> busy", msg.get("code") == "busy", msg)
    with client.websocket_connect("/ws/app", headers=ORIGIN) as app_ws:
        t0 = time.perf_counter()
        app_ws.send_json({"id": "a1", "action": "trips:list", "payload": {"token": token}})
        while app_ws.receive_json().get("id") != "a1":
            pass
        took = time.perf_counter() - t0
    check("/ws/app answers during a voice turn", took < 1.0, f"{took:.2f}s")
    msg = recv_until(ws, {"transcript", "error"})
    check("slow turn still completes", msg.get("type") == "transcript")
    FakeSTT.delay = 0.0

    # ---- Groq failure
    FakeSTT.fail = True
    msg = turn(ws, pcm(1.0))
    check("Groq failure -> stt_failed with a user message", msg.get("code") == "stt_failed" and "try again" in msg.get("message", "").lower(), msg)
    FakeSTT.fail = False
    ws.__exit__(None, None, None)

    # ---- nothing stored when the debug store is off
    audio_dir = os.path.join(scratch, "voice_audio_ci")
    import shutil
    shutil.rmtree(audio_dir, ignore_errors=True)
    os.environ["VOICE_DEBUG_AUDIO_DIR"] = audio_dir
    check("debug store off by default", debug_store.enabled() is False)
    check("no audio folder written while off", not os.path.exists(audio_dir))

    # ---- rate limit: 15 a minute
    for key in redis_conn.scan_iter("rl:*"):
        redis_conn.delete(key)
    ws = connect(token2)
    ws.receive_json()
    codes = []
    for _ in range(16):
        codes.append(turn(ws, pcm(0.1)).get("code"))
    check("16th recording in a minute -> rate_limited", codes[:15] == ["too_short"] * 15 and codes[15] == "rate_limited", codes[-3:])
    ws.__exit__(None, None, None)
    for key in redis_conn.scan_iter("rl:*"):
        redis_conn.delete(key)

    if ADMIN_URL:
        # ---- debug store ON (local throwaway Postgres)
        os.environ["VOICE_DEBUG_STORE"] = "true"
        os.environ["VOICE_DEBUG_DATABASE_URL"] = CI_URL
        debug_store._engine = None
        try:
            os.environ["VOICE_DEBUG_DATABASE_URL"] = "postgresql://u:p@db.example.com:5432/x"
            debug_store._engine = None
            debug_store._engine_or_create()
            check("non-local URL rejected", False)
        except RuntimeError:
            check("non-local URL rejected", True)
        os.environ["VOICE_DEBUG_DATABASE_URL"] = CI_URL
        debug_store._engine = None
        check("debug store on", debug_store.enabled() and debug_store.init())

        ws = connect()
        ws.receive_json()
        a = turn(ws, pcm(1.0, 440))
        b = turn(ws, pcm(1.5, 660))
        FakeSTT.fail = True
        c = turn(ws, pcm(0.8, 880))
        FakeSTT.fail = False
        time.sleep(0.5)  # after_turn runs right after each reply
        ws.send_json({"type": "end_session"})
        time.sleep(1.0)
        ws.__exit__(None, None, None)

        eng = create_engine(CI_URL)
        with eng.connect() as conn:
            rows = conn.execute(text("SELECT speech_id, session_id, user_id, conversation_id, turn_index, audio_path, audio_duration_ms, "
                                     "transcription, language, stt_provider, stt_model, stt_time_ms, total_time_ms, status, error "
                                     "FROM voice_speeches ORDER BY turn_index")).mappings().all()
            sess = conn.execute(text("SELECT * FROM voice_sessions")).mappings().all()
        check("3 rows in voice_speeches", len(rows) == 3, len(rows))
        if len(rows) == 3:
            r0 = rows[0]
            with database.SessionLocal() as db:
                from models_db import SessionModel
                import auth
                real_sid = db.query(SessionModel).filter(SessionModel.token_hash == auth.hash_token(token)).first().id
            check("ids are real: speech_id = turn_id, session_id = sessions.id, user_id", r0["speech_id"] == a["turn_id"]
                  and r0["session_id"] == real_sid and r0["user_id"] == user_id and r0["conversation_id"] == "conv1")
            check("row has transcript and timings", r0["transcription"] == "mujhe jaipur jaana hai" and r0["stt_time_ms"] == 123
                  and r0["total_time_ms"] is not None and r0["audio_duration_ms"] == 1000 and r0["status"] == "ok"
                  and r0["stt_provider"] == "groq" and r0["stt_model"] == "whisper-large-v3-turbo", dict(r0))
            check("turn_index 1,2,3", [r["turn_index"] for r in rows] == [1, 2, 3])
            check("failed Groq call: failed row, no transcript", rows[2]["status"] == "failed" and rows[2]["transcription"] is None
                  and "stt_failed" in (rows[2]["error"] or "") and rows[2]["stt_model"] == "whisper-large-v3-turbo", dict(rows[2]))
            wav_paths = [r["audio_path"] for r in rows]
            check("a WAV per recording (also the failed one)", all(os.path.exists(p) for p in wav_paths), wav_paths)
            import wave
            with wave.open(wav_paths[1], "rb") as w:
                check("WAV is 16 kHz mono 16-bit, right length", (w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()) == (16000, 1, 2, 24000))
            check("voice_sessions row", len(sess) == 1 and sess[0]["speech_count"] == 3 and sess[0]["total_audio_ms"] == 3300
                  and sess[0]["avg_stt_time_ms"] == 123 and sess[0]["ended_at"] is not None, sess and dict(sess[0]))
            merged = sess[0]["merged_audio_path"] if sess else ""
            if merged and os.path.exists(merged):
                with wave.open(merged, "rb") as w:
                    frames = w.getnframes()
                check("session_full.wav = all recordings + 0.5 s gaps", frames == 16000 * (1.0 + 1.5 + 0.8) + 2 * 8000, frames)
            else:
                check("session_full.wav exists", False, merged)

        # session also closes on socket close (no end_session message)
        ws = connect()
        ws.receive_json()
        turn(ws, pcm(1.0))
        time.sleep(0.3)
        ws.__exit__(None, None, None)
        time.sleep(1.0)
        with eng.connect() as conn:
            n = conn.execute(text("SELECT speech_count FROM voice_sessions")).scalar()
        check("socket close also updates voice_sessions", n == 4, n)
        eng.dispose()

    else:
        print("SKIP debug-store checks: no local Postgres admin URL (see the docstring)")

client.__exit__(None, None, None)
debug_store._engine and debug_store._engine.dispose()
if admin:
    with admin.connect() as c:
        c.execute(text(f"DROP DATABASE IF EXISTS {CI_DB} WITH (FORCE)"))
for key in redis_conn.scan_iter("rl:*"):
    redis_conn.delete(key)
print(f"\n{sum(results)}/{len(results)} passed")
