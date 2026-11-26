"""
Voice step 4 checks (create a trip by voice): app DB = SQLite, Redis = local, OpenAI + place search simulated.
Draft rules, date read-back, review page prefill, Confirm card (voice + button = one action, once only),
cancel, ownership, replacement, logging, clean-up on socket close.
Run from backend/: python -m tests.test_voice_step4
"""
import io
import json
import logging
import math
import os
import struct
import sys
import tempfile
import time
import uuid
from datetime import timedelta
from pathlib import Path
from unittest import mock

import dotenv

dotenv.load_dotenv = lambda *a, **k: None
os.environ["DATABASE_URL"] = "postgresql://x:y@127.0.0.1:1/none"
os.environ["AI_PROVIDER"] = "mock"
os.environ["OPENAI_API_KEY"] = "test-key-not-real"
os.environ["VOICE_TTS_ENABLED"] = "false"
os.environ.pop("VOICE_DEBUG_STORE", None)

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)
SCRATCH = tempfile.mkdtemp(prefix="voyageai_test_")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

import database  # noqa: E402

database.engine = create_engine(f"sqlite:///{os.path.join(SCRATCH, 'voice4.db')}", connect_args={"check_same_thread": False})
database.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=database.engine)

import main  # noqa: E402
import openai_client  # noqa: E402
import places  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from models_trip import TripModel  # noqa: E402
from redis_client import redis_conn  # noqa: E402
from trip_lifecycle import today_ist  # noqa: E402
from voice import agent, draft as D, pending as P, pipeline  # noqa: E402
from voice.stt import STTResult  # noqa: E402

main.SessionLocal = database.SessionLocal
database.Base.metadata.create_all(bind=database.engine)
for key in redis_conn.scan_iter("rl:*"):
    redis_conn.delete(key)

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail != "" else ""), flush=True)


TODAY = today_ist()
d = lambda n: (TODAY + timedelta(days=n)).isoformat()  # noqa: E731
USER_A = f"usr_s4a_{uuid.uuid4().hex[:6]}"
USER_B = f"usr_s4b_{uuid.uuid4().hex[:6]}"
PLACES = {
    "goa": [{"id": "ChIJgoa", "place_id": "ChIJgoa", "name": "Goa", "latitude": 15.29, "longitude": 74.12, "city": "Goa, India"}],
    "jaipur": [{"id": "ChIJjpr", "place_id": "ChIJjpr", "name": "Jaipur", "latitude": 26.91, "longitude": 75.79, "city": "Jaipur, Rajasthan, India"}],
    "delhi": [{"id": "ChIJdel", "place_id": "ChIJdel", "name": "New Delhi", "latitude": 28.61, "longitude": 77.21, "city": "New Delhi, Delhi, India"}],
    "paris": [{"id": "ChIJpar", "name": "Paris", "latitude": 48.85, "longitude": 2.35, "city": "Paris, France"}],
}
fake_search = lambda q: PLACES.get(q.strip().lower(), [])  # noqa: E731


class FakeTools:
    queue, calls = [], []

    def __call__(self, messages, tools, **kw):
        FakeTools.calls.append(messages)
        kind, payload = FakeTools.queue.pop(0)
        if kind == "tool":
            return {"content": None, "tool_calls": [{"name": payload[0], "arguments": payload[1]}]}
        return {"content": payload, "tool_calls": []}


fake = FakeTools()


def ra(text, user, conv, screen="/home", queue=None):
    if queue is not None:
        FakeTools.queue = list(queue)
    return agent.run_agent(text, "hi", user_id=user, conversation_id=conv, screen=screen, trip=None, redis_conn=redis_conn)


def trips_of(user):
    with database.SessionLocal() as db:
        return db.query(TripModel).filter(TripModel.user_id == user).count()


# ---------------- pure draft rules
dr = D.TripDraftState()
check("missing fields: fixed order", dr.missing_fields() == ["destination", "start_date", "end_date", "adults", "children", "budget_inr"])
check("question asks at most 2 things (date pair counts once)", D.question_for(dr.missing_fields(), "hi") == "Kahan jaana hai? Kab se kab tak jaana hai?")
res = D.apply_update(D.TripDraftState(), {"destination": "goa", "start_date": d(-2), "end_date": d(1)}, "hi", TODAY, lambda q: fake_search(q)[0] if fake_search(q) else None)
check("past start date refused with a spoken reason", res.problems == ["Yeh tareekh beet chuki hai, aage ki tareekh boliye."] and res.draft.start_date is None, res.problems)
res = D.apply_update(D.TripDraftState(), {"start_date": d(10), "end_date": d(7)}, "en", TODAY, None)
check("end before start refused", res.problems == ["The end date is before the start date."] and res.draft.start_date is None, res.problems)
res = D.apply_update(D.TripDraftState(), {"start_date": d(10), "days": 31}, "hi", TODAY, None)
check("more than 30 days refused", res.problems and res.draft.end_date is None, res.problems)
res = D.apply_update(D.TripDraftState(), {"destination": "paris"}, "hi", TODAY, lambda q: None)
check("a place outside India is not found -> asks", res.problems == ["paris nahi mila, India mein kaunsi jagah?"] and res.draft.destination is None, res.problems)
check("budget words", [D.parse_budget(x) for x in ("50 hazaar", "1.5 lakh", "bees hazaar", 45000)] == [50000, 150000, 20000, 45000])
check("people words", [D.parse_int(x) for x in ("do", "teen", "koi nahi", 2)] == [2, 3, 0, 2])
res = D.apply_update(D.TripDraftState(), {"budget_inr": 500}, "hi", TODAY, None)
check("budget under ₹1,000 refused", res.problems and res.draft.budget_inr is None)
dd = D.TripDraftState(destination={"name": "Goa"}, start_date=d(28), end_date=d(31), adults=2, children=0, budget_inr=40000,
                      origin_skipped=True)   # booking step 1: the optional origin is asked once; skipped here
check("all fields but no read-back -> confirm_date, never ready", dd.next_step() == "confirm_date")
dd.dates_confirmed = True
check("after the read-back -> ready", dd.next_step() == "ready")

with mock.patch.object(openai_client, "chat_tools", fake), mock.patch.object(places, "search_places", fake_search):
    # ---------------- a full conversation (section 6)
    C = f"conv_s4_{uuid.uuid4().hex[:6]}"
    r = ra("Delhi se Jaipur jaana hai 3 din ke liye, budget 20 hazaar", USER_A, C,
           queue=[("tool", ("update_trip_draft", {"destination": "Jaipur", "origin_city": "Delhi", "days": 3, "budget_inr": "20 hazaar"}))])
    check("turn 1: code asks for the missing start date + adults",
          r.reply_text == "Jaipur, 3 din. Kab se jaana hai? Kitne bade log jaa rahe hain?" and r.step == "ask" and r.missing_count == 3
          and r.ui_actions == [], r.reply_text)
    sys_prompt = FakeTools.calls[-1][0]["content"]
    r = ra("agle hafte se, 2 adults aur 2 bachche", USER_A, C,
           queue=[("tool", ("update_trip_draft", {"start_date": d(7), "adults": 2, "children": 2}))])
    s7, e9 = TODAY + timedelta(days=7), TODAY + timedelta(days=9)
    # booking step 1: with a starting city the read-back also says origin, destination and people
    want = f"New Delhi se Jaipur, {s7.day} {D.MONTHS[s7.month - 1]} se {e9.day} {D.MONTHS[e9.month - 1]}, do raat, do bade log, do bachche. Sahi hai?"
    check("turn 2: dates read back in words, nothing opened yet", r.reply_text == want and r.step == "confirm_date" and r.ui_actions == [], r.reply_text)
    check("the prompt carries the draft and what code says is missing", "still missing" in FakeTools.calls[-1][0]["content"])
    n = len(FakeTools.calls)
    r = ra("haan", USER_A, C)
    check("turn 3: 'haan' -> ready (code only, no LLM call)", r.step == "ready" and len(FakeTools.calls) == n and r.action == "trip_draft")
    check("ready: open_review with the exact prefill shape", r.ui_actions == [{"type": "open_review", "prefill": {
        "destination": {"id": "ChIJjpr", "name": "Jaipur", "city": "Jaipur", "region": "Rajasthan", "country": "India",
                        "latitude": 26.91, "longitude": 75.79, "displayName": "Jaipur"},
        "origin": {"id": "ChIJdel", "name": "New Delhi", "city": "New Delhi", "region": "Delhi", "country": "India",
                   "latitude": 28.61, "longitude": 77.21, "displayName": "New Delhi"},
        "startDate": s7.isoformat(), "endDate": e9.isoformat(), "adultsCount": 2, "childrenCount": 2, "customBudgetAmount": 20000}}],
          r.ui_actions)
    pc = r.pending_confirmation
    check("ready: one pending confirmation with a summary that says it can't be undone by voice",
          pc and pc["id"].startswith("pc_") and "undo nahi" in pc["summary"] and "Jaipur" in pc["summary"], pc)
    check("ready reply is one short line", r.reply_text == agent.READY_REPLY["hi"])
    check("nothing saved yet", trips_of(USER_A) == 0)

    # ---------------- confirm once only (voice "haan" == the button)
    r1 = ra("haan", USER_A, C)
    check("'haan' on the confirm card -> submit_review (the app presses Proceed)", r1.ui_actions == [{"type": "submit_review"}] and r1.action == "trip_confirm")
    check("confirm clears the draft and the pending", D.load(redis_conn, USER_A, C) is None and P.get(redis_conn, USER_A, C) is None)
    r2 = agent.confirm_trip(redis_conn, USER_A, C, "hi", pc["id"])
    check("a second confirm does nothing", r2.ui_actions == [] and r2.action == "trip_confirm_none")
    check("the voice side never creates a trip itself", trips_of(USER_A) == 0)

    # ---------------- a date correction after the read-back
    C2 = f"conv_s4_{uuid.uuid4().hex[:6]}"
    ra("Goa jaana hai", USER_A, C2, queue=[("tool", ("update_trip_draft", {"destination": "Goa", "start_date": d(20), "end_date": d(23),
                                                                           "adults": 2, "children": 0, "budget_inr": 50000}))])
    ra("pata nahi", USER_A, C2)   # "Kahan se jaana hai?" -> skipped: the read-back stays dates-only
    r = ra("nahi", USER_A, C2)
    check("'nahi' to the read-back -> dates cleared, asked again", r.reply_text == agent.DATE_AGAIN["hi"] and D.load(redis_conn, USER_A, C2).start_date is None)
    r = ra("21 se 24", USER_A, C2, queue=[("tool", ("update_trip_draft", {"start_date": d(21), "end_date": d(24)}))])
    check("the new dates are read back again", r.step == "confirm_date" and "Sahi hai?" in r.reply_text)
    r = ra("nahi, budget 60 hazaar kar do", USER_A, C2, queue=[("tool", ("update_trip_draft", {"budget_inr": 60000}))])
    check("a non-date correction during the read-back -> read back again (still not ready)", r.step == "confirm_date")
    r = ra("haan sahi hai", USER_A, C2)
    pc2 = r.pending_confirmation
    check("then ready with the new budget", r.step == "ready" and r.ui_actions[0]["prefill"]["customBudgetAmount"] == 60000)

    # ---------------- pending replaced on a new create request
    r = ra("ek aur trip banao Jaipur ke liye", USER_A, C2, queue=[("tool", ("update_trip_draft", {"destination": "Jaipur", "start_new": True}))])
    check("a new create request replaces the old draft + pending and says so",
          r.reply_text.startswith(agent.REPLACED_NOTE["hi"]) and P.get(redis_conn, USER_A, C2) is None
          and D.load(redis_conn, USER_A, C2).destination["name"] == "Jaipur" and D.load(redis_conn, USER_A, C2).budget_inr is None, r.reply_text)
    check("the old pending id no longer confirms", agent.confirm_trip(redis_conn, USER_A, C2, "hi", pc2["id"]).action == "trip_confirm_none")

    # ---------------- cancel saves nothing
    r = ra("cancel karo", USER_A, C2)
    check("'cancel karo' -> draft dropped, nothing saved", r.action == "trip_cancel" and D.load(redis_conn, USER_A, C2) is None and trips_of(USER_A) == 0,
          r.reply_text)
    C3 = f"conv_s4_{uuid.uuid4().hex[:6]}"
    ra("Goa", USER_A, C3, queue=[("tool", ("update_trip_draft", {"destination": "Goa", "start_date": d(5), "days": 2, "adults": 1,
                                                                 "children": 0, "budget_inr": 9000}))])
    ra("pata nahi", USER_A, C3)
    ra("haan", USER_A, C3)
    r = ra("nahi", USER_A, C3)
    check("'nahi' on the confirm card -> cancelled", r.action == "trip_cancel" and P.get(redis_conn, USER_A, C3) is None)
    ra("Goa", USER_A, C3, queue=[("tool", ("update_trip_draft", {"destination": "Goa", "start_date": d(5), "days": 2, "adults": 1,
                                                                 "children": 0, "budget_inr": 9000}))])
    ra("pata nahi", USER_A, C3)
    ra("haan", USER_A, C3)
    r = ra("map kholo", USER_A, C3, queue=[("tool", ("navigate", {"page": "map"}))])
    check("a new topic cancels the pending confirmation (draft kept)", P.get(redis_conn, USER_A, C3) is None and D.load(redis_conn, USER_A, C3) is not None)
    ra("cancel karo", USER_A, C3, queue=[("tool", ("cancel_trip_draft", {}))])
    check("cancel_trip_draft tool drops the draft", D.load(redis_conn, USER_A, C3) is None)

    # ---------------- ownership: another user's draft / pending is unreachable
    C4 = f"conv_s4_{uuid.uuid4().hex[:6]}"
    ra("Goa", USER_A, C4, queue=[("tool", ("update_trip_draft", {"destination": "Goa", "start_date": d(5), "days": 2, "adults": 1,
                                                                 "children": 0, "budget_inr": 9000}))])
    ra("pata nahi", USER_A, C4)
    pa = ra("haan", USER_A, C4).pending_confirmation
    check("user B can't confirm A's pending (same conversation id)", agent.confirm_trip(redis_conn, USER_B, C4, "hi", pa["id"]).action == "trip_confirm_none"
          and P.get(redis_conn, USER_A, C4) is not None)
    r = ra("haan", USER_B, C4, queue=[("text", "Kya karna hai?")])
    check("user B's 'haan' doesn't see A's draft", r.ui_actions == [] and D.load(redis_conn, USER_A, C4) is not None)
    check("a wrong pending id does nothing", agent.confirm_trip(redis_conn, USER_A, C4, "hi", "pc_wrong").action == "trip_confirm_none")
    check("update_trip_draft takes no user_id / trip_id", not any(k in json.dumps(agent.UPDATE_DRAFT_TOOL) for k in ("user_id", "trip_id")))

    # ---------------- logs: action, step, missing count, timings; never words, names or dates
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    logging.getLogger("voice").addHandler(h)
    C5 = f"conv_s4_{uuid.uuid4().hex[:6]}"
    ra("Zebrapur jaana hai", USER_A, C5, queue=[("tool", ("update_trip_draft", {"destination": "Goa", "start_date": d(30), "end_date": d(33)}))])
    logging.getLogger("voice").removeHandler(h)
    log = buf.getvalue()
    check("log: action, step, missing count, timings", "action=trip_draft" in log and "step=" in log and "missing=" in log and "llm_ms=" in log, log)
    check("log: no words, names or dates", "Zebrapur" not in log and "Goa" not in log and d(30) not in log and str((TODAY + timedelta(days=30)).day) + " " not in log, log)

# ---------------- socket: Confirm button (same action), second confirm, cancel, another user's, socket close clears
client = TestClient(main.app)
client.__enter__()
toks = {}
for name, email in (("A", "s4a@example.com"), ("B", "s4b@example.com")):
    r = client.post("/api/auth/register", json={"name": f"Voice {name}", "email": email, "password": "secret123"})
    toks[name] = (r.json()["token"], r.json()["user"]["id"])
client.cookies.clear()


def pcm(seconds):
    return b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / 16000))) for i in range(int(16000 * seconds)))


class FakeSTT:
    text = "haan"

    def transcribe(self, audio):
        return STTResult(text=FakeSTT.text, language="hi", duration_ms=1000, latency_ms=50, provider="openai", model="w")


def recv_until(ws, kinds):
    while True:
        m_ = ws.receive_json()
        if m_.get("type") in kinds:
            return m_


def voice_turn(ws, conv, text):
    FakeSTT.text = text
    ws.send_json({"type": "start", "conversation_id": conv, "screen": "/trips/new#review"})
    recv_until(ws, {"recording"})
    ws.send_bytes(pcm(0.5))
    ws.send_json({"type": "stop"})
    recv_until(ws, {"transcript"})
    return recv_until(ws, {"reply"})


uid_a, uid_b = toks["A"][1], toks["B"][1]
with mock.patch.object(pipeline, "get_stt", lambda: FakeSTT()), mock.patch.object(openai_client, "chat_tools", fake), \
        mock.patch.object(places, "search_places", fake_search):
    with client.websocket_connect("/ws/voice", headers={"origin": "http://localhost:5173"}) as ws:
        ws.send_json({"type": "auth", "token": toks["A"][0]})
        recv_until(ws, {"ready"})
        CW = "conv_s4_ws"
        FakeTools.queue = [("tool", ("update_trip_draft", {"destination": "Goa", "start_date": d(12), "days": 3, "adults": 2,
                                                            "children": 0, "budget_inr": 30000, "origin_city": "Delhi"}))]
        voice_turn(ws, CW, "Goa jaana hai")
        rep = voice_turn(ws, CW, "haan")
        pcid = (rep.get("pending_confirmation") or {}).get("id")
        check("socket: reply carries pending_confirmation + open_review", pcid and rep["ui_actions"][0]["type"] == "open_review", rep.get("pending_confirmation"))
        ws.send_json({"type": "confirm", "conversation_id": CW, "pending_id": pcid})
        cr = recv_until(ws, {"confirm_result"})
        check("socket: Confirm button -> same action (submit_review)", cr["ok"] and cr["ui_actions"] == [{"type": "submit_review"}], cr)
        ws.send_json({"type": "confirm", "conversation_id": CW, "pending_id": pcid})
        cr2 = recv_until(ws, {"confirm_result"})
        check("socket: second Confirm does nothing", cr2["ok"] is False and cr2["ui_actions"] == [])
        FakeTools.queue = [("tool", ("update_trip_draft", {"destination": "Goa", "start_date": d(12), "days": 3, "adults": 2,
                                                            "children": 0, "budget_inr": 30000, "origin_city": "Delhi"}))]
        voice_turn(ws, CW, "Goa jaana hai")
        rep = voice_turn(ws, CW, "haan")
        pcid = rep["pending_confirmation"]["id"]
        ws.send_json({"type": "cancel", "conversation_id": CW, "pending_id": pcid})
        cr = recv_until(ws, {"confirm_result"})
        check("socket: Cancel -> nothing saved, draft gone", cr["ok"] and D.load(redis_conn, uid_a, CW) is None and trips_of(uid_a) == 0)
        ws.send_json({"type": "confirm", "conversation_id": "conv_not_mine", "pending_id": pcid})
        check("socket: a conversation not started on this socket is refused", recv_until(ws, {"confirm_result"})["ok"] is False)
        FakeTools.queue = [("tool", ("update_trip_draft", {"destination": "Goa", "start_date": d(12)}))]
        voice_turn(ws, CW, "Goa jaana hai")
        check("draft exists before the socket closes", D.load(redis_conn, uid_a, CW) is not None)
    deadline = time.time() + 5
    while D.load(redis_conn, uid_a, CW) is not None and time.time() < deadline:
        time.sleep(0.1)
    check("socket closed midway -> draft deleted", D.load(redis_conn, uid_a, CW) is None)

    with client.websocket_connect("/ws/voice", headers={"origin": "http://localhost:5173"}) as ws:
        ws.send_json({"type": "auth", "token": toks["A"][0]})
        recv_until(ws, {"ready"})
        FakeTools.queue = [("tool", ("update_trip_draft", {"destination": "Goa", "start_date": d(12), "days": 3, "adults": 2,
                                                            "children": 0, "budget_inr": 30000, "origin_city": "Delhi"}))]
        voice_turn(ws, "conv_s4_shared", "Goa jaana hai")
        a_pc = voice_turn(ws, "conv_s4_shared", "haan")["pending_confirmation"]["id"]
        with client.websocket_connect("/ws/voice", headers={"origin": "http://localhost:5173"}) as wsb:
            wsb.send_json({"type": "auth", "token": toks["B"][0]})
            recv_until(wsb, {"ready"})
            FakeTools.queue = [("text", "Kya?")]
            voice_turn(wsb, "conv_s4_shared", "kuch bhi")      # B uses the same conversation id
            wsb.send_json({"type": "confirm", "conversation_id": "conv_s4_shared", "pending_id": a_pc})
            check("socket: another user can't confirm A's pending", recv_until(wsb, {"confirm_result"})["ok"] is False
                  and P.get(redis_conn, uid_a, "conv_s4_shared") is not None)
        ws.send_json({"type": "draft_done", "conversation_id": "conv_s4_shared"})
        time.sleep(0.3)
        check("draft_done (Proceed tapped) clears the draft and pending", D.load(redis_conn, uid_a, "conv_s4_shared") is None
              and P.get(redis_conn, uid_a, "conv_s4_shared") is None)
client.__exit__(None, None, None)

for prefix in ("voice:mem", "voice:pending", "voice:draft", "voice:confirm"):
    for u in (USER_A, USER_B, uid_a, uid_b):
        for key in redis_conn.scan_iter(f"{prefix}:{u}:*"):
            redis_conn.delete(key)
print(f"\n{sum(results)}/{len(results)} passed", flush=True)
sys.exit(0 if all(results) else 1)
