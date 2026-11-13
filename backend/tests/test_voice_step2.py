"""
Voice step 2 checks (navigation agent): app DB = SQLite, Redis = local, Groq simulated at the HTTP
level (no real calls), STT simulated, TTS off.
Run from backend/: python -m tests.test_voice_step2
"""
import json
import math
import os
import struct
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import dotenv

dotenv.load_dotenv = lambda *a, **k: None
os.environ["DATABASE_URL"] = "postgresql://x:y@127.0.0.1:1/none"
os.environ["AI_PROVIDER"] = "mock"
os.environ["GROQ_API_KEY"] = "test-key-not-real"
os.environ["VOICE_TTS_ENABLED"] = "false"
os.environ.pop("VOICE_DEBUG_STORE", None)

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)
SCRATCH = tempfile.mkdtemp(prefix="voyageai_test_")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import database

database.engine = create_engine(f"sqlite:///{os.path.join(SCRATCH, 'voice2.db')}", connect_args={"check_same_thread": False})
database.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=database.engine)

import main  # noqa: E402
import groq_client  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from models_trip import TripModel  # noqa: E402
from redis_client import redis_conn  # noqa: E402
from voice import agent, pages, pipeline  # noqa: E402
from voice.stt import STTResult  # noqa: E402

main.SessionLocal = database.SessionLocal
database.Base.metadata.create_all(bind=database.engine)
for key in redis_conn.scan_iter("rl:*"):
    redis_conn.delete(key)

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail != "" else ""), flush=True)


# ---------------- simulated Groq (HTTP level)
class FakeGroq:
    queue = []        # responses to hand out, in order: ("tool", page, day) | ("text", str) | ("badargs",) | ("http", code)
    requests = []     # request bodies sent

    def __call__(self, url, headers=None, json=None, timeout=None):
        FakeGroq.requests.append(json)
        kind = FakeGroq.queue.pop(0) if FakeGroq.queue else ("text", "Theek hai.")
        resp = mock.Mock()
        if kind[0] == "http":
            resp.status_code = kind[1]
            resp.text = "error body that must not be logged"
            return resp
        resp.status_code = 200
        if kind[0] == "tool":
            args = {"page": kind[1]} if kind[2] is None else {"page": kind[1], "day": kind[2]}
            msg = {"role": "assistant", "content": None, "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "navigate", "arguments": json_dumps(args)}}]}
            finish = "tool_calls"
        elif kind[0] == "badargs":
            msg = {"role": "assistant", "content": None, "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "navigate", "arguments": "{page: map"}}]}
            finish = "tool_calls"
        else:
            msg = {"role": "assistant", "content": kind[1]}
            finish = "stop"
        resp.json.return_value = {"choices": [{"message": msg, "finish_reason": finish}]}
        return resp


json_dumps = json.dumps
fake_groq = FakeGroq()

# ---------------- pages.resolve
for page in pages.PAGES:
    route, err = pages.resolve(page, None, has_trip=True)
    if err or route != pages.ROUTES[page]:
        check(f"page {page} resolves", False, (route, err))
check("every page resolves with a trip open", all(pages.resolve(p, None, True) == (pages.ROUTES[p], None) for p in pages.PAGES))
check("pages without a trip resolve except trip/itinerary",
      all(pages.resolve(p, None, False)[1] == ("no_trip" if p in pages.NEEDS_TRIP else None) for p in pages.PAGES))
check("unknown page rejected", pages.resolve("settings_page", None, True) == (None, "unknown_page") and pages.resolve(None, None, True)[1] == "unknown_page")
check("itinerary day 2 -> ?day=2", pages.resolve("itinerary", 2, True) == ("/trip/itinerary?day=2", None))
check("day only for itinerary", pages.resolve("map", 2, True) == (None, "bad_day"))
check("day must be 1-30", all(pages.resolve("itinerary", d, True) == (None, "bad_day") for d in (0, 31, -1, True, "2")))
check("day 1 and 30 allowed", pages.resolve("itinerary", 1, True)[1] is None and pages.resolve("itinerary", 30, True)[1] is None)
check("routes match the app (plan_trip /trips/new, saved_places /saved-places)",
      pages.ROUTES["plan_trip"] == "/trips/new" and pages.ROUTES["saved_places"] == "/saved-places" and pages.ROUTES["home"] == "/home")
check("a confirm pair for every page", all(pages.CONFIRM[p]["hi"] and pages.CONFIRM[p]["en"] for p in pages.PAGES))
check("day template", pages.confirm_text("itinerary", 3, "hi") == "Day 3 khol diya." and pages.confirm_text("itinerary", 3, "en") == "Opened day 3.")
check("tool enum == pages list", agent.NAVIGATE_TOOL["function"]["parameters"]["properties"]["page"]["enum"] == pages.PAGES)
check("template language: hi/ur -> hi, en -> en, else hi",
      [agent.template_language(x) for x in ("hi", "ur", "en", "is", None)] == ["hi", "hi", "en", "hi", "hi"])

# ---------------- groq_chat_tools / groq_chat
with mock.patch.object(groq_client.requests, "post", fake_groq):
    FakeGroq.queue = [("tool", "map", None)]
    out = groq_client.groq_chat_tools([{"role": "user", "content": "x"}], agent.TOOLS)
    check("groq_chat_tools parses a tool call", out == {"content": None, "tool_calls": [{"name": "navigate", "arguments": {"page": "map"}}]}, out)
    body = FakeGroq.requests[-1]
    check("groq_chat_tools sends tools + tool_choice", body.get("tools") == agent.TOOLS and body.get("tool_choice") == "auto")
    FakeGroq.queue = [("text", "Kaunsa page?")]
    check("groq_chat_tools returns plain text", groq_client.groq_chat_tools([{"role": "user", "content": "x"}], agent.TOOLS)
          == {"content": "Kaunsa page?", "tool_calls": []})
    FakeGroq.queue = [("badargs",)]
    try:
        groq_client.groq_chat_tools([{"role": "user", "content": "x"}], agent.TOOLS); check("malformed arguments -> GroqError", False)
    except groq_client.GroqError as e:
        check("malformed arguments -> GroqError", "arguments" in str(e))
    FakeGroq.queue = [("http", 429)]
    try:
        groq_client.groq_chat_tools([{"role": "user", "content": "x"}], agent.TOOLS); check("429 -> GroqRateLimited", False)
    except groq_client.GroqRateLimited:
        check("429 -> GroqRateLimited", True)
    FakeGroq.queue = [("http", 500)]
    try:
        groq_client.groq_chat_tools([{"role": "user", "content": "x"}], agent.TOOLS)
    except groq_client.GroqError as e:
        check("HTTP error message carries no response text", "error body" not in str(e), str(e))
    # groq_chat unchanged
    FakeGroq.queue = [("text", '{"ok": true}')]
    check("groq_chat still returns text", groq_client.groq_chat([{"role": "user", "content": "x"}]) == '{"ok": true}')
    check("groq_chat sends no tools", "tools" not in FakeGroq.requests[-1])
    FakeGroq.queue = [("tool", "map", None)]
    try:
        groq_client.groq_chat([{"role": "user", "content": "x"}]); check("groq_chat still rejects finish_reason tool_calls", False)
    except groq_client.GroqError:
        check("groq_chat still rejects finish_reason tool_calls", True)

# ---------------- run_agent (real local Redis for memory)
USER = f"usr_test_{uuid.uuid4().hex[:8]}"
CONV = "conv_test"
TRIP = agent.TripInfo(title="Jaipur Tour Package", start_date="2027-01-10", end_date="2027-01-12")


def ra(text, lang="hi", trip=TRIP, screen="/"):
    return agent.run_agent(text, lang, user_id=USER, conversation_id=CONV, screen=screen, trip=trip, redis_conn=redis_conn)


with mock.patch.object(groq_client.requests, "post", fake_groq):
    FakeGroq.queue = [("tool", "map", None)]
    n_before = len(FakeGroq.requests)
    r = ra("map dikha")
    n_calls = len(FakeGroq.requests) - n_before
    check("'map dikha' -> navigate /map + Hinglish template",
          r.ui_actions == [{"type": "navigate", "to": "/map"}] and r.reply_text == "Map khol diya." and r.action == "navigate:map", r)
    sysmsg = FakeGroq.requests[-1]["messages"][0]["content"]
    check("system prompt has screen and trip (title + dates)", "User is on page: /" in sysmsg
          and "Open trip: Jaipur Tour Package (2027-01-10 to 2027-01-12)" in sysmsg)
    check("one Groq call per turn (no second call after navigate)", n_calls == 1, n_calls)

    FakeGroq.queue = [("tool", "map", None)]
    r = ra("take me to the map", lang="en")
    check("English -> English template", r.reply_text == "Opened the map.")

    FakeGroq.queue = [("tool", "itinerary", 2)]
    r = ra("day 2 dikhao")
    check("itinerary day 2 -> /trip/itinerary?day=2 + 'Day 2 khol diya.'",
          r.ui_actions == [{"type": "navigate", "to": "/trip/itinerary?day=2"}] and r.reply_text == "Day 2 khol diya.")

    FakeGroq.queue = [("tool", "itinerary", None)]
    r = ra("itinerary kholo", trip=None)
    sysmsg = FakeGroq.requests[-1]["messages"][0]["content"]
    check("no trip: prompt says 'Open trip: none'", "Open trip: none" in sysmsg)
    check("itinerary with no trip -> /trips + no_trip reply",
          r.ui_actions == [{"type": "navigate", "to": "/trips"}] and r.reply_text == pages.NO_TRIP_REPLY["hi"] and r.action == "navigate:my_trips")

    FakeGroq.queue = [("text", "Main sirf aapki trip mein madad kar sakta hoon. Koi aur sawaal? Teesra vaakya.")]
    r = ra("ek joke sunao")
    check("off-topic -> no ui_actions, reply trimmed to 2 sentences",
          r.ui_actions == [] and r.action == "reply" and r.reply_text == "Main sirf aapki trip mein madad kar sakta hoon. Koi aur sawaal?", r.reply_text)

    FakeGroq.queue = [("tool", "settings_page", None)]
    r = ra("woh kholo")
    check("unknown page -> 'Kaunsa page kholun?', no navigation", r.ui_actions == [] and r.reply_text == "Kaunsa page kholun?")
    FakeGroq.queue = [("tool", "map", 5)]
    r = ra("map day 5")
    check("day on a non-itinerary page -> question, no navigation", r.ui_actions == [] and r.reply_text == "Kaunsa page kholun?")

    FakeGroq.queue = [("badargs",)]
    r = ra("map dikha")
    check("malformed tool args -> fallback reply", r.reply_text == agent.FALLBACK_REPLY and r.action == "error" and r.ui_actions == [])
    FakeGroq.queue = [("http", 500)]
    r = ra("map dikha")
    check("Groq error -> fallback reply", r.reply_text == agent.FALLBACK_REPLY and r.action == "error")
    FakeGroq.queue = [("http", 429)]
    r = ra("map dikha")
    check("Groq rate limit -> fallback reply", r.reply_text == agent.FALLBACK_REPLY and r.error_code == "rate_limited")

    # memory: capped at 10 turns, TTL, sent to Groq
    redis_conn.delete(f"voice:mem:{USER}:{CONV}")
    for i in range(12):
        FakeGroq.queue = [("text", f"Jawab {i}.")]
        ra(f"sawaal {i}")
    mem = json.loads(redis_conn.get(f"voice:mem:{USER}:{CONV}"))
    ttl = redis_conn.ttl(f"voice:mem:{USER}:{CONV}")
    check("memory keeps the last 10 turns (20 messages)", len(mem) == 20 and mem[0]["content"] == "sawaal 2" and mem[-1]["content"] == "Jawab 11.", len(mem))
    check("memory has a 30-minute TTL", 0 < ttl <= 1800, ttl)
    FakeGroq.queue = [("text", "Ok.")]
    ra("aur?")
    sent = FakeGroq.requests[-1]["messages"]
    check("memory is sent to Groq (system + 20 + user)", len(sent) == 22 and sent[-1] == {"role": "user", "content": "aur?"})
    agent.clear_memory(redis_conn, USER, CONV)
    check("clear_memory deletes it", redis_conn.get(f"voice:mem:{USER}:{CONV}") is None)

# ---------------- over the socket: trip_id ownership, reply shape, errors, end_session
client = TestClient(main.app)
client.__enter__()


def register(email):
    r = client.post("/api/auth/register", json={"name": "Voice Two", "email": email, "password": "secret123"})
    return r.json()["token"], r.json()["user"]["id"]


tok_a, uid_a = register("voice2a@example.com")
tok_b, uid_b = register("voice2b@example.com")
client.cookies.clear()
now = datetime.now(timezone.utc).isoformat()
with database.SessionLocal() as db:
    for tid, uid, title in (("trip_v2_a", uid_a, "Goa Escape"), ("trip_v2_b", uid_b, "Secret Trip Of B")):
        db.add(TripModel(id=tid, user_id=uid, title=title, status="PLANNING", start_date="2027-02-01", end_date="2027-02-03",
                         total_days=3, destination={"name": title}, travelers=[], budget={}, created_at=now, updated_at=now))
    db.commit()


def pcm(seconds):
    n = int(16000 * seconds)
    return b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / 16000))) for i in range(n))


class FakeSTT:
    provider, model = "groq", "whisper-large-v3-turbo"
    text = "map dikha"

    def transcribe(self, audio):
        return STTResult(text=FakeSTT.text, language="hi", duration_ms=len(audio) * 1000 // 32000, latency_ms=100,
                         provider="groq", model=self.model)


def recv_until(ws, kinds):
    while True:
        m = ws.receive_json()
        if m.get("type") in kinds:
            return m


def turn(ws, trip_id=None, conv="conv_ws"):
    ws.send_json({"type": "start", "conversation_id": conv, "screen": "/home", "trip_id": trip_id})
    recv_until(ws, {"recording"})
    ws.send_bytes(pcm(1.0))
    ws.send_json({"type": "stop"})
    tr = recv_until(ws, {"transcript", "error"})
    rep = recv_until(ws, {"reply"}) if tr["type"] == "transcript" else None
    return tr, rep


with mock.patch.object(pipeline, "get_stt", lambda: FakeSTT()), mock.patch.object(groq_client.requests, "post", fake_groq):
    with client.websocket_connect("/ws/voice", headers={"origin": "http://localhost:5173"}) as ws:
        ws.send_json({"type": "auth", "token": tok_a})
        recv_until(ws, {"ready"})

        FakeGroq.queue = [("tool", "map", None)]
        tr, rep = turn(ws, trip_id="trip_v2_a")
        check("socket: transcript first, then reply", tr["type"] == "transcript" and rep is not None)
        check("socket: reply has ui_actions, action, llm_ms",
              rep["ui_actions"] == [{"type": "navigate", "to": "/map"}] and rep["action"] == "navigate:map"
              and isinstance(rep["llm_ms"], int) and rep["reply_text"] == "Map khol diya.", rep)
        sysmsg = FakeGroq.requests[-1]["messages"][0]["content"]
        check("own trip_id -> its title and dates in the prompt", "Open trip: Goa Escape (2027-02-01 to 2027-02-03)" in sysmsg)

        FakeGroq.queue = [("tool", "itinerary", None)]
        tr, rep = turn(ws, trip_id="trip_v2_b")
        sysmsg = FakeGroq.requests[-1]["messages"][0]["content"]
        check("another user's trip_id is ignored (treated as none)", "Open trip: none" in sysmsg and "Secret Trip Of B" not in sysmsg)
        check("... so itinerary -> /trips", rep["ui_actions"] == [{"type": "navigate", "to": "/trips"}])

        FakeGroq.queue = [("badargs",)]
        tr, rep = turn(ws, trip_id="trip_v2_a")
        check("socket: malformed tool args -> fallback reply", rep["reply_text"] == agent.FALLBACK_REPLY and rep["action"] == "error"
              and rep["ui_actions"] == [])
        FakeGroq.queue = [("http", 500)]
        tr, rep = turn(ws, trip_id="trip_v2_a")
        check("socket: Groq error -> fallback reply", rep["reply_text"] == agent.FALLBACK_REPLY)
        FakeGroq.queue = [("tool", "food", None)]
        tr, rep = turn(ws, trip_id="trip_v2_a")
        check("socket stays open after errors", rep["ui_actions"] == [{"type": "navigate", "to": "/food"}])

        FakeSTT.text = ""
        n = len(FakeGroq.requests)
        tr, rep = turn(ws)
        check("empty transcript -> fixed reply, no Groq call", rep["reply_text"] == pipeline.EMPTY_TRANSCRIPT_REPLY and len(FakeGroq.requests) == n)
        FakeSTT.text = "map dikha"

        key = f"voice:mem:{uid_a}:conv_ws"
        check("memory stored for the conversation", redis_conn.get(key) is not None)
        ws.send_json({"type": "end_session"})
        ws.send_json({"type": "bogus"})
        recv_until(ws, {"error"})
        check("end_session deletes the conversation memory", redis_conn.get(key) is None)

client.__exit__(None, None, None)
for k in list(redis_conn.scan_iter(f"voice:mem:{USER}:*")) + list(redis_conn.scan_iter("rl:*")):
    redis_conn.delete(k)
print(f"\n{sum(results)}/{len(results)} passed")
