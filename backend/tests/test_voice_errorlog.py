"""
Agent failures made visible (voice-errorlog): error_code + error_detail on every agent error path, the
test-only error log (logs/voice_errors.md), the debug-store columns, the reply's error_code (test mode only)
and one server log line per failed turn. Never the user's words, tool arguments or Groq's response body.

Groq is simulated at the HTTP level; STT and TTS are simulated. The debug-store row checks need a LOCAL
Postgres admin URL (VOICE_TEST_PG_ADMIN_URL, or else VOICE_DEBUG_DATABASE_URL in backend/.env); they use a
throwaway DB voice_errlog_ci, dropped at the end. The log file goes to a temp folder, never backend/logs/.
Run from backend/: python -m tests.test_voice_errorlog
"""
import logging
import math
import os
import struct
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import dotenv
from requests.structures import CaseInsensitiveDict

dotenv.load_dotenv = lambda *a, **k: None
os.environ["DATABASE_URL"] = "postgresql://x:y@127.0.0.1:1/none"
os.environ["AI_PROVIDER"] = "mock"
os.environ["GROQ_API_KEY"] = "test-key-not-real"
os.environ["VOICE_TTS_ENABLED"] = "false"
os.environ.pop("VOICE_DEBUG_STORE", None)
os.environ.pop("VOICE_DEBUG_DATABASE_URL", None)

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)
SCRATCH = tempfile.mkdtemp(prefix="voyageai_test_")
LOG_PATH = os.path.join(SCRATCH, "logs", "voice_errors.md")
os.environ["VOICE_ERROR_LOG_PATH"] = LOG_PATH
os.environ["VOICE_DEBUG_AUDIO_DIR"] = os.path.join(SCRATCH, "audio")

from sqlalchemy import MetaData, Table, create_engine, inspect, select, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402


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
CI_DB = "voice_errlog_ci"
CI_URL = make_url(ADMIN_URL).set(database=CI_DB).render_as_string(hide_password=False) if ADMIN_URL else None
admin = None
if ADMIN_URL:
    try:
        admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
        with admin.connect() as c:
            c.execute(text(f"DROP DATABASE IF EXISTS {CI_DB}"))
            c.execute(text(f"CREATE DATABASE {CI_DB}"))
    except Exception as err:
        print(f"SKIP debug-store DB checks: local Postgres not reachable ({type(err).__name__})")
        admin, CI_URL = None, None

import database  # noqa: E402

database.engine = create_engine(f"sqlite:///{os.path.join(SCRATCH, 'errlog.db')}", connect_args={"check_same_thread": False})
database.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=database.engine)

import main  # noqa: E402
import groq_client  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from redis_client import redis_conn  # noqa: E402
from voice import agent, debug_store, error_log, pipeline  # noqa: E402
from voice.stt import STTResult  # noqa: E402
from voice.tools import lookups  # noqa: E402

main.SessionLocal = database.SessionLocal
database.Base.metadata.create_all(bind=database.engine)
for key in redis_conn.scan_iter("rl:*"):
    redis_conn.delete(key)

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail != "" else ""), flush=True)


# Words that must never reach the log file, the DB row or the server log.
USER_WORDS = "Zorbaflux"      # in every transcript
ARG_WORDS = "Quixplendor"     # in tool arguments
BODY_WORDS = "Blorptastic"    # in Groq's error body
SECRETS = (USER_WORDS, ARG_WORDS, BODY_WORDS)
USER = f"usr_el_{uuid.uuid4().hex[:8]}"
PCM = b"\x00\x00" * 16000


class FakeGroq:
    """queue items: ("http", status, code, headers) | ("tool", name, args) | ("rawargs", name, raw_string)"""
    queue = []

    def __call__(self, url, headers=None, json=None, timeout=None):
        kind = FakeGroq.queue.pop(0) if FakeGroq.queue else ("tool", "navigate", {"page": "map"})
        resp = mock.Mock()
        resp.headers = CaseInsensitiveDict()
        if kind[0] == "http":
            resp.status_code = kind[1]
            resp.text = f'{{"error": {{"message": "{BODY_WORDS} {USER_WORDS}", "code": "{kind[2]}"}}}}'
            resp.json.return_value = {"error": {"message": f"{BODY_WORDS} said {USER_WORDS}", "code": kind[2]}}
            resp.headers = CaseInsensitiveDict(kind[3] or {})
            return resp
        resp.status_code = 200
        raw = kind[2] if kind[0] == "rawargs" else json_dumps(kind[2])
        msg = {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": kind[1], "arguments": raw}}]}
        resp.json.return_value = {"choices": [{"message": msg, "finish_reason": "tool_calls"}]}
        return resp


import json  # noqa: E402

json_dumps = json.dumps


class Capture(logging.Handler):
    lines = []

    def emit(self, record):
        Capture.lines.append(record.getMessage())


voice_logger = logging.getLogger("voice")
voice_logger.setLevel(logging.INFO)
voice_logger.addHandler(Capture())


def log_text():
    return Path(LOG_PATH).read_text(encoding="utf-8") if os.path.exists(LOG_PATH) else ""


def db_row(turn_id):
    if not debug_store.enabled():
        return None
    with debug_store._engine_or_create().connect() as c:
        row = c.execute(select(debug_store.voice_speeches).where(debug_store.voice_speeches.c.speech_id == turn_id)).mappings().first()
    return dict(row) if row else None


SESSION = f"vs_el_{uuid.uuid4().hex[:8]}"
TURN_NO = [0]


def run_case(transcript, queue, stt_ok=True):
    """One turn through the real pipeline stages: agent (+ server log), then after_turn (store + error log)."""
    TURN_NO[0] += 1
    ctx = pipeline.TurnContext(turn_id=pipeline.new_turn_id(), user_id=USER, session_id=SESSION,
                               conversation_id=f"conv_el_{uuid.uuid4().hex[:6]}", screen="/home", turn_number=TURN_NO[0])
    before_log, before_lines = log_text(), len(Capture.lines)
    if stt_ok:
        result = pipeline.TurnResult(turn_id=ctx.turn_id, ok=True, text=transcript, language="hi", duration_ms=1000,
                                     stt_ms=462, stt_provider="groq", stt_model="whisper-large-v3-turbo")
        FakeGroq.queue = list(queue)
        pipeline.make_reply(ctx, result)
    else:
        result = pipeline.TurnResult(turn_id=ctx.turn_id, ok=False, duration_ms=1000, error_code="stt_failed",
                                     error_detail="Groq HTTP 500", stt_model="whisper-large-v3-turbo")
    pipeline.after_turn(PCM, ctx, result, 2327)
    after = log_text()
    entry = after[len(before_log):] if after.startswith(before_log) else after
    return ctx, result, entry, Capture.lines[before_lines:], db_row(ctx.turn_id)


def no_secrets(*things):
    """The DB row's error columns only: its transcription column holds the words on purpose (that's the store's job)."""
    things = [{k: t.get(k) for k in ("agent_action", "agent_error_code", "agent_error_detail", "error")}
              if isinstance(t, dict) else t for t in things]
    blob = " ".join(str(t) for t in things)
    return not any(s in blob for s in SECRETS)


def boom(*a, **k):
    raise KeyError(f"{USER_WORDS} trip")   # the message holds "user words": it must not be logged


# ---------------- debug store on (test mode), with an OLD voice_speeches table missing the new columns
os.environ["VOICE_DEBUG_STORE"] = "true"
if CI_URL:
    os.environ["VOICE_DEBUG_DATABASE_URL"] = CI_URL
    old = MetaData()
    Table("voice_speeches", old, *[col._copy() for col in debug_store.voice_speeches.columns
                                  if col.name not in ("agent_error_code", "agent_error_detail")])
    eng = create_engine(CI_URL)
    old.create_all(eng)
    eng.dispose()
    debug_store._engine = None
    check("debug store on", debug_store.enabled() and debug_store.init())
    cols = {c["name"] for c in inspect(debug_store._engine).get_columns("voice_speeches")}
    check("ALTER TABLE adds agent_error_code / agent_error_detail to an existing table",
          {"agent_error_code", "agent_error_detail"} <= cols)
else:
    print("SKIP debug-store DB checks: no local Postgres admin URL (see the docstring)")
check("test mode on", debug_store.test_mode())

with mock.patch.object(groq_client.requests, "post", FakeGroq()):
    model = groq_client.groq_model()

    # 1. Groq 429 with Retry-After
    ctx, r, entry, lines, row = run_case(f"{USER_WORDS} map kholo", [("http", 429, "rate_limit_exceeded", {"Retry-After": "7"})])
    check("429: error_code rate_limited", r.action == "error" and r.agent_error_code == "rate_limited", r.agent_error_code)
    check("429: detail = HTTP 429, code, Retry-After, model, attempt 1 of 2",
          r.agent_error_detail == f"HTTP 429, code=rate_limit_exceeded, retry_after=7s, model={model}, attempt 1 of 2",
          r.agent_error_detail)
    check("429: log entry appended (header, stage, detail, timings)",
          entry.count("\n## ") + entry.startswith("## ") == 1
          and f"| turn {row['turn_index'] if row else TURN_NO[0]} | error | rate_limited" in entry
          and f"- stage: agent (attempt 1 of 2)   model: {model}" in entry
          and "- detail: HTTP 429, code=rate_limit_exceeded, retry_after=7s" in entry
          and "- timings: stt 462 ms, llm " in entry and "total 2327 ms" in entry
          and "- tool in progress: none" in entry and ctx.turn_id in entry and SESSION in entry, entry)
    check("429: one server log line with turn, code, status, attempt",
          any(f"turn={ctx.turn_id} agent_error=rate_limited status=429 attempt=1/2" in ln for ln in lines), lines)
    if row is not None:
        check("429: DB row has agent_error_code / detail",
              row["agent_action"] == "error" and row["agent_error_code"] == "rate_limited"
              and row["agent_error_detail"] == r.agent_error_detail, row)
    check("429: no user words / body anywhere", no_secrets(entry, lines, row, r.agent_error_detail))

    # 2. 400 tool_use_failed twice
    ctx, r, entry, lines, row = run_case(f"{USER_WORDS} kholo", [("http", 400, "tool_use_failed", None)] * 2)
    check("400 x2: groq_transient_twice, attempt 2 of 2",
          r.agent_error_code == "groq_transient_twice"
          and r.agent_error_detail == f"HTTP 400, code=tool_use_failed, model={model}, attempt 2 of 2", r.agent_error_detail)
    check("400 x2: log entry", "| error | groq_transient_twice" in entry and "- stage: agent (attempt 2 of 2)" in entry
          and "- detail: HTTP 400, code=tool_use_failed" in entry, entry)
    check("400 x2: server log line", any(f"turn={ctx.turn_id} agent_error=groq_transient_twice status=400 attempt=2/2" in ln
                                         for ln in lines), lines)
    if row is not None:
        check("400 x2: DB row", row["agent_error_code"] == "groq_transient_twice" and "attempt 2 of 2" in row["agent_error_detail"], row)
    check("400 x2: no user words / body anywhere", no_secrets(entry, lines, row))

    # 3. 500 (twice: 5xx is retried once)
    ctx, r, entry, lines, row = run_case(f"{USER_WORDS} kholo", [("http", 500, "", None)] * 2)
    check("500 x2: groq_transient_twice, HTTP 500 without a code",
          r.agent_error_code == "groq_transient_twice" and r.agent_error_detail == f"HTTP 500, model={model}, attempt 2 of 2",
          r.agent_error_detail)
    check("500 x2: log entry + server line", "- detail: HTTP 500\n" in entry
          and any(f"turn={ctx.turn_id} agent_error=groq_transient_twice status=500 attempt=2/2" in ln for ln in lines), entry)
    check("500 x2: no user words / body anywhere", no_secrets(entry, lines, row))

    # 3b. 500, then 429 on the retry -> rate_limited on attempt 2
    ctx, r, entry, lines, row = run_case(f"{USER_WORDS} kholo", [("http", 500, "", None), ("http", 429, "rate_limit_exceeded",
                                                                                           {"Retry-After": "12"})])
    check("500 then 429: rate_limited, attempt 2 of 2, retry_after=12s",
          r.agent_error_code == "rate_limited" and "retry_after=12s" in r.agent_error_detail
          and r.agent_error_detail.endswith("attempt 2 of 2"), r.agent_error_detail)

    # 3c. 401 (not retried) -> groq_error, attempt 1
    ctx, r, entry, lines, row = run_case(f"{USER_WORDS} kholo", [("http", 401, "invalid_api_key", None)])
    check("401: groq_error, code=invalid_api_key, attempt 1 of 2",
          r.agent_error_code == "groq_error" and r.agent_error_detail == f"HTTP 401, code=invalid_api_key, model={model}, attempt 1 of 2",
          r.agent_error_detail)

    # 4. bad tool args: arguments not an object (Groq client), malformed JSON twice, and the agent's own check
    ctx, r, entry, lines, row = run_case(f"{USER_WORDS} kholo", [("tool", "navigate", [ARG_WORDS])])
    check("args not an object: groq_error code=tool_args_not_object",
          r.agent_error_code == "groq_error" and "code=tool_args_not_object" in r.agent_error_detail, r.agent_error_detail)
    check("args not an object: no tool arguments anywhere", no_secrets(entry, lines, row, r.agent_error_detail))
    ctx, r, entry, lines, row = run_case(f"{USER_WORDS} kholo", [("rawargs", "navigate", f"{{page: {ARG_WORDS}")] * 2)
    check("malformed args twice: groq_transient_twice code=malformed_tool_args, attempt 2",
          r.agent_error_code == "groq_transient_twice" and "code=malformed_tool_args" in r.agent_error_detail
          and "attempt 2 of 2" in r.agent_error_detail, r.agent_error_detail)
    check("malformed args: no tool arguments anywhere", no_secrets(entry, lines, row))
    with mock.patch.object(groq_client, "groq_chat_tools",
                           lambda *a, **k: {"content": None, "tool_calls": [{"name": "navigate", "arguments": [ARG_WORDS]}]}):
        ctx, r, entry, lines, row = run_case(f"{USER_WORDS} kholo", [])
    check("agent check: bad_tool_args with tool name and type only",
          r.agent_error_code == "bad_tool_args" and r.agent_error_detail == "arguments were list, not an object, tool=navigate",
          r.agent_error_detail)
    check("bad_tool_args: log entry names the tool", "| error | bad_tool_args" in entry and "- stage: tool" in entry
          and "- tool in progress: navigate" in entry, entry)
    if row is not None:
        check("bad_tool_args: DB row", row["agent_error_code"] == "bad_tool_args", row)
    check("bad_tool_args: no tool arguments anywhere", no_secrets(entry, lines, row))

    # 5. a KeyError raised inside a tool
    with mock.patch.object(lookups, "list_my_trips", boom):
        ctx, r, entry, lines, row = run_case(f"{USER_WORDS} meri trips", [("tool", "list_my_trips", {"include_past": False})])
    raise_line = boom.__code__.co_firstlineno + 1
    check("KeyError in a tool: code KeyError, class + file:line + tool",
          r.agent_error_code == "KeyError"
          and r.agent_error_detail == f"KeyError at tests/test_voice_errorlog.py:{raise_line} in boom, tool=list_my_trips",
          r.agent_error_detail)
    check("KeyError: log entry (stage tool, tool in progress)", "| error | KeyError" in entry and "- stage: tool" in entry
          and f"- detail: KeyError at tests/test_voice_errorlog.py:{raise_line} in boom" in entry
          and "- tool in progress: list_my_trips" in entry, entry)
    check("KeyError: server log line", any(f"turn={ctx.turn_id} agent_error=KeyError status=- attempt=-" in ln for ln in lines), lines)
    if row is not None:
        check("KeyError: DB row", row["agent_error_code"] == "KeyError" and "tool=list_my_trips" in row["agent_error_detail"], row)
    check("KeyError: the exception's message (user words) is not logged", no_secrets(entry, lines, row, r.agent_error_detail))

    # 6. no_user (the agent's own check) and a crash outside run_agent's try
    res = agent._decide([{"name": "list_my_trips", "arguments": {}}], None, "hi", False, user_id=None)
    check("no_user: code + detail", res.error_code == "no_user" and res.error_detail == "missing user_id, tool=list_my_trips",
          res.error_detail)
    res = agent._decide([{"name": "update_trip_draft", "arguments": {}}], None, "hi", False, user_id="u1")
    check("no_user (draft): names what's missing", res.error_code == "no_user"
          and res.error_detail == "missing conversation_id/redis, tool=update_trip_draft", res.error_detail)
    with mock.patch.object(pipeline, "run_agent", boom):
        ctx, r, entry, lines, row = run_case(f"{USER_WORDS} kholo", [])
    check("agent crash: agent_crashed with class + file:line", r.action == "error" and r.agent_error_code == "agent_crashed"
          and r.agent_error_detail.startswith("KeyError at tests/test_voice_errorlog.py:"), r.agent_error_detail)
    check("agent crash: log entry + no user words", "| error | agent_crashed" in entry and no_secrets(entry, lines, row))

    # 7. an answer turn with an error_code (fallback answer): logged and stored, action stays "answer"
    import tour_guide_service
    with mock.patch.object(tour_guide_service, "voice_answer",
                           lambda *a, **k: {"status": "ok", "source": "groq", "fallback_code": "gemini_timeout",
                                            "spoken": f"{USER_WORDS} answer", "note": None}):
        ctx, r, entry, lines, row = run_case(f"{USER_WORDS} kya hai", [("tool", "answer_question", {"question": ARG_WORDS})])
    check("answer turn: answered_by_groq:<code>", r.action == "answer" and r.agent_error_code == "answered_by_groq:gemini_timeout",
          r.agent_error_code)
    check("answer turn: log entry", "| answer | answered_by_groq:gemini_timeout" in entry, entry)
    if row is not None:
        check("answer turn: DB row has the code", row["agent_action"] == "answer"
              and row["agent_error_code"] == "answered_by_groq:gemini_timeout", row)
    check("answer turn: log entry has no reply or question words", no_secrets(entry, lines))

    # 8. a good turn: nothing logged, no code stored
    ctx, r, entry, lines, row = run_case("map kholo", [("tool", "navigate", {"page": "map"})])
    check("good turn: no error code, no log entry", r.agent_error_code is None and entry == "", entry)
    if row is not None:
        check("good turn: DB row has no error code", row["agent_error_code"] is None and row["agent_error_detail"] is None, row)

    # 9. STT failure: logged with stage stt
    ctx, r, entry, lines, row = run_case("", [], stt_ok=False)
    check("STT failure: log entry, stage stt", "| stt_failed | stt_failed" in entry and "- stage: stt   model: whisper-large-v3-turbo" in entry
          and "- detail: Groq HTTP 500" in entry, entry)

    # 10. a log write failure never breaks the turn
    with mock.patch.object(error_log, "append", mock.Mock(side_effect=OSError("disk full"))):
        try:
            ctx, r, entry, lines, row = run_case(f"{USER_WORDS} kholo", [("http", 429, "rate_limit_exceeded", None)])
            check("log write failure (append raises): after_turn doesn't raise", True)
            check("log write failure: warned without words", any("error log write failed" in ln and "OSError" in ln for ln in lines))
        except Exception as err:
            check("log write failure (append raises): after_turn doesn't raise", False, type(err).__name__)
    os.environ["VOICE_ERROR_LOG_PATH"] = SCRATCH  # a folder: open() fails for real
    try:
        run_case(f"{USER_WORDS} kholo", [("http", 429, "rate_limit_exceeded", None)])
        check("log write failure (path is a folder): turn still finishes", True)
    except Exception as err:
        check("log write failure (path is a folder): turn still finishes", False, type(err).__name__)
    os.environ["VOICE_ERROR_LOG_PATH"] = LOG_PATH

    # 11. rotation over 1 MB
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write("x" * (error_log.MAX_BYTES + 10))
    ctx, r, entry, lines, row = run_case(f"{USER_WORDS} kholo", [("http", 429, "rate_limit_exceeded", None)])
    rotated = [p for p in os.listdir(os.path.dirname(LOG_PATH)) if p.startswith("voice_errors.") and p != "voice_errors.md"]
    new_text = log_text()
    check("rotation: old file renamed voice_errors.<date>.md, new file starts fresh",
          len(rotated) == 1 and rotated[0].startswith(f"voice_errors.{datetime.now(error_log.IST):%Y-%m-%d}")
          and new_text.startswith("## ") and new_text.count("\n## ") == 0 and ctx.turn_id in new_text, rotated)

    # 12. test mode off: no log file entry
    os.environ["VOICE_DEBUG_STORE"] = "false"
    ctx, r, entry, lines, row = run_case(f"{USER_WORDS} kholo", [("http", 429, "rate_limit_exceeded", None)])
    check("test mode off: no log entry (the server line stays)", entry == "" and r.agent_error_code == "rate_limited"
          and any(f"turn={ctx.turn_id} agent_error=rate_limited" in ln for ln in lines))
    os.environ["VOICE_DEBUG_STORE"] = "true"

    # 13. over the socket: the reply carries error_code only in test mode
    client = TestClient(main.app)
    client.__enter__()
    reg = client.post("/api/auth/register", json={"name": "Err Log", "email": f"errlog_{uuid.uuid4().hex[:6]}@example.com",
                                                 "password": "secret123"}).json()
    client.cookies.clear()
    tok, uid = reg["token"], reg["authUser"]["id"]

    class FakeSTT:
        def transcribe(self, audio):
            return STTResult(text=f"{USER_WORDS} kholo", language="hi", duration_ms=1000, latency_ms=100,
                             provider="groq", model="whisper-large-v3-turbo")

    def sine(seconds):
        return b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / 16000))) for i in range(int(16000 * seconds)))

    def recv_until(ws, kinds):
        while True:
            msg = ws.receive_json()
            if msg.get("type") in kinds:
                return msg

    def ws_turn(ws):
        ws.send_json({"type": "start", "conversation_id": f"conv_el_{uuid.uuid4().hex[:6]}", "screen": "/home"})
        recv_until(ws, {"recording"})
        ws.send_bytes(sine(1.0))
        ws.send_json({"type": "stop"})
        recv_until(ws, {"transcript"})
        return recv_until(ws, {"reply"})

    with mock.patch.object(pipeline, "get_stt", lambda: FakeSTT()):
        with client.websocket_connect("/ws/voice", headers={"origin": "http://localhost:5173"}) as ws:
            ws.send_json({"type": "auth", "token": tok})
            recv_until(ws, {"ready"})
            FakeGroq.queue = [("http", 400, "tool_use_failed", None)] * 2
            rep = ws_turn(ws)
            check("socket, test mode: reply has error_code", rep.get("error_code") == "groq_transient_twice"
                  and rep["action"] == "error" and rep["reply_text"] == agent.FALLBACK_REPLY, rep.get("error_code"))
            FakeGroq.queue = [("tool", "navigate", {"page": "map"})]
            rep = ws_turn(ws)
            check("socket, good turn: no error_code field", "error_code" not in rep)
            with mock.patch.object(error_log, "append", mock.Mock(side_effect=OSError("disk full"))):
                FakeGroq.queue = [("http", 429, "rate_limit_exceeded", None)]
                rep = ws_turn(ws)
                check("socket, log write fails: reply still sent", rep.get("action") == "error")
            os.environ["VOICE_DEBUG_STORE"] = "false"
            FakeGroq.queue = [("http", 400, "tool_use_failed", None)] * 2
            rep = ws_turn(ws)
            check("socket, test mode off: no error_code field", rep["action"] == "error" and "error_code" not in rep)
            os.environ["VOICE_DEBUG_STORE"] = "true"
    client.__exit__(None, None, None)   # the throwaway account lives in the temp SQLite DB only

check("no user words / body / arguments in the whole log file",
      no_secrets(log_text(), *[Path(os.path.dirname(LOG_PATH), p).read_text(encoding="utf-8")
                               for p in os.listdir(os.path.dirname(LOG_PATH))]))
check("no user words / body / arguments in any server log line", no_secrets(Capture.lines))
ignored = subprocess.run(["git", "check-ignore", "-q", "logs/voice_errors.md"], cwd=BACKEND_DIR).returncode == 0
check("backend/logs/ is gitignored", ignored)

# ---------------- cleanup
for conv_key in redis_conn.scan_iter(f"voice:*:{USER}:*"):
    redis_conn.delete(conv_key)
for key in redis_conn.scan_iter("rl:*"):
    redis_conn.delete(key)
if debug_store._engine is not None:
    debug_store._engine.dispose()
if admin:
    with admin.connect() as c:
        c.execute(text(f"DROP DATABASE IF EXISTS {CI_DB} WITH (FORCE)"))
print(f"\n{sum(results)}/{len(results)} passed", flush=True)
sys.exit(0 if all(results) else 1)
