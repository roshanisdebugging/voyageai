"""
BR-1006: after the trip is created and the booking is saved, a bare "haan" / "dhanyavaad" must not rebuild a trip draft
from the old turns. App DB = SQLite, Redis = local, the model and place search simulated (the fake model would call
update_trip_draft if it were reached).
Checks: the evidence order (draft -> confirm -> booking saved -> "हाँ, बिलकुल."), the conversation's voice memory cleared
on confirm_trip and on a voice booking save (another conversation untouched), and the old behaviour of "haan" at the
read-back, the Confirm card and a booking question; new trip requests and other requests still reach the model.
Run from backend/: python -m tests.test_voice_ack
"""
import io
import logging
import os
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import dotenv

dotenv.load_dotenv = lambda *a, **k: None
os.environ["DATABASE_URL"] = "postgresql://x:y@127.0.0.1:1/none"
os.environ["AI_PROVIDER"] = "mock"
os.environ["OPENAI_API_KEY"] = "test-key-not-real"
os.environ["VOICE_TTS_ENABLED"] = "false"
os.environ.pop("VOICE_DEBUG_STORE", None)
os.environ.pop("BOOKING_NOTIFY_ENABLED", None)

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)
SCRATCH = tempfile.mkdtemp(prefix="voyageai_test_")

from sqlalchemy import create_engine, text as sql  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

import database  # noqa: E402

database.engine = create_engine(f"sqlite:///{os.path.join(SCRATCH, 'ack.db')}", connect_args={"check_same_thread": False})
database.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=database.engine)

import main  # noqa: E402
import openai_client  # noqa: E402
import places  # noqa: E402
import booking_flow as BF  # noqa: E402
from models_trip import TripModel  # noqa: E402
from redis_client import redis_conn  # noqa: E402
from trip_lifecycle import today_ist  # noqa: E402
from voice import agent, draft as D, pending as P  # noqa: E402
from tests.purpose_helper import past_purpose  # noqa: E402  (feat/trip-purpose)

main.SessionLocal = database.SessionLocal
database.Base.metadata.create_all(bind=database.engine)

log_buf = io.StringIO()
_h = logging.StreamHandler(log_buf)
for name in ("voice", "booking"):
    logging.getLogger(name).addHandler(_h)
    logging.getLogger(name).setLevel(logging.INFO)

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail != "" else ""), flush=True)


TODAY = today_ist()
d = lambda n: (TODAY + timedelta(days=n)).isoformat()  # noqa: E731
NOW = datetime.now(timezone.utc)
USER = f"usr_ack_{uuid.uuid4().hex[:6]}"
PLACES = {
    "goa": [{"id": "ChIJgoa", "place_id": "ChIJgoa", "name": "Goa", "latitude": 15.29, "longitude": 74.12, "city": "Goa, India"}],
    "kolkata": [{"id": "ChIJkol", "place_id": "ChIJkol", "name": "Kolkata", "latitude": 22.57, "longitude": 88.36,
                 "city": "Kolkata, West Bengal, India"}],
    "delhi": [{"id": "ChIJdel", "place_id": "ChIJdel", "name": "New Delhi", "latitude": 28.61, "longitude": 77.21,
               "city": "New Delhi, Delhi, India"}],
    "jaipur": [{"id": "ChIJjpr", "place_id": "ChIJjpr", "name": "Jaipur", "latitude": 26.91, "longitude": 75.79,
                "city": "Jaipur, Rajasthan, India"}],
}
fake_search = lambda q: PLACES.get(q.strip().lower(), [])  # noqa: E731
DRAFT_ARGS = {"destination": "Goa", "origin_city": "Kolkata", "start_date": d(20), "end_date": d(22), "adults": 2,
              "children": 0, "budget_inr": 40000}


class FakeLLM:
    """Every call rebuilds the old trip draft (what the real model did from the memory), unless a reply is queued."""
    queue, calls = [], []

    def __call__(self, messages, tools, **kw):
        FakeLLM.calls.append(messages)
        if FakeLLM.queue:
            kind, payload = FakeLLM.queue.pop(0)
            if kind == "text":
                return {"content": payload, "tool_calls": []}
            return {"content": None, "tool_calls": [{"name": payload[0], "arguments": payload[1]}]}
        return {"content": None, "tool_calls": [{"name": "update_trip_draft", "arguments": dict(DRAFT_ARGS)}]}


fake = FakeLLM()


def make_trip(adults=2):
    tid = f"trip_ack_{uuid.uuid4().hex[:8]}"
    with database.SessionLocal() as db:
        db.add(TripModel(id=tid, user_id=USER, title="Goa", status="PLANNING", start_date=d(20), end_date=d(22), total_days=3,
                         destination={"name": "Goa"}, travelers=[{"id": f"tr_{i}", "type": "ADULT"} for i in range(adults)],
                         budget={"targetAmount": 40000}, created_at=NOW, updated_at=NOW, itinerary_status="READY"))
        db.commit()
    return tid


def ra(text, conv, trip=None, queue=None, screen="/home", stt="hi"):
    if queue is not None:
        FakeLLM.queue = list(queue)
    r = agent.run_agent(text, stt, user_id=USER, conversation_id=conv, screen=screen, trip=trip, redis_conn=redis_conn)
    return past_purpose(r, conv, lambda: D.load(redis_conn, USER, conv), lambda t: agent.run_agent(
        t, stt, user_id=USER, conversation_id=conv, screen=screen, trip=trip, redis_conn=redis_conn))


def mem(conv):
    return agent.load_memory(redis_conn, USER, conv)


ACKS = ("हाँ, बिलकुल.", "हाँ, सही है", "धन्यवाद", "ok chalo", "haan", "thank you", "shukriya", "theek hai", "accha", "bas",
        "Okay.", "चलो", "ठीक है।", "thanks bhai", "हाँ")

with mock.patch.object(openai_client, "chat_tools", fake), mock.patch.object(places, "search_places", fake_search):
    C = f"conv_ack_{uuid.uuid4().hex[:6]}"
    OTHER = f"conv_ack_other_{uuid.uuid4().hex[:6]}"
    ra("Mumbai mein kya dekhein?", OTHER, queue=[("text", "Gateway of India dekhiye.")])
    other_before = mem(OTHER)
    check("setup: another conversation has memory", len(other_before) == 2)

    # ---- the evidence order: trip draft by voice, read-back "haan", review page "haan" (= Confirm)
    r = ra("Kolkata se Goa jaana hai, 25 se 27, do log, budget 40 hazaar", C, queue=[("tool", ("update_trip_draft", dict(DRAFT_ARGS)))])
    check("draft: the dates are read back", r.step == "confirm_date" and r.reply_text.endswith("Sahi hai?"), r.reply_text)
    n = len(FakeLLM.calls)
    r = ra("haan", C)
    check("regression: 'haan' at the read-back -> ready, no model call", r.step == "ready" and len(FakeLLM.calls) == n
          and r.pending_confirmation, r.reply_text)
    r = ra("हाँ, बिलकुल", C)
    check("regression: a natural yes at the review page -> trip_confirm (submit_review)", r.action == "trip_confirm"
          and r.ui_actions == [{"type": "submit_review"}] and len(FakeLLM.calls) == n, r.action)
    check("confirm_trip: draft, pending and this conversation's memory cleared",
          D.load(redis_conn, USER, C) is None and P.get(redis_conn, USER, C) is None and mem(C) == [], mem(C))
    check("confirm_trip: another conversation's memory untouched", mem(OTHER) == other_before)

    # the trip the app created (the wizard's Proceed); then the booking by voice
    T = make_trip()
    TRIP = agent.TripInfo(title="Goa", start_date=d(20), end_date=d(22), id=T)
    ra("Aaj mausam kaisa hai?", C, trip=TRIP, queue=[("text", "Dhoop hai.")])   # one ordinary turn kept in the memory
    check("setup: the memory holds turns again before the booking", len(mem(C)) == 2)
    r = ra("hotel book karwana hai", C, trip=TRIP)
    check("booking: started", r.action == "booking" and r.reply_text.startswith("Hotel kaisa chahiye"), r.reply_text)
    n = len(FakeLLM.calls)
    for said in ("budget", "do kamre", "Roshan, 30 saal", "Mohan, 40 saal", "9876543210", "haan"):
        r = ra(said, C, trip=TRIP)
    check("regression: 'haan' at the booking phone read-back -> the review", r.reply_text.endswith("Sahi hai?")
          and BF.current_question(BF.load(redis_conn, USER, T)) == "review", r.reply_text)
    r = ra("हाँ", C, trip=TRIP)
    check("booking saved (BR-…)", r.action == "booking" and r.step == "done" and "BR-" in r.reply_text, r.reply_text)
    check("booking save: this conversation's memory, draft and pending cleared",
          mem(C) == [] and D.load(redis_conn, USER, C) is None and P.get(redis_conn, USER, C) is None, mem(C))
    check("booking save: another conversation's memory untouched", mem(OTHER) == other_before)
    check("booking: no model call in the whole booking", len(FakeLLM.calls) == n)

    # ---- BR-1006: acknowledgements afterwards
    for said in ACKS:
        r = ra(said, C, trip=TRIP)
        want = agent.ACK_REPLY[agent.template_language("hi", said)]      # the usual reply-language rule
        check(f"after the save: {said!r} -> {want!r}, action ack, no model call, no draft",
              r.reply_text == want and r.action == "ack" and len(FakeLLM.calls) == n and D.load(redis_conn, USER, C) is None
              and not r.ui_actions, (r.reply_text, r.action))
    check("acks are kept out of the voice memory", mem(C) == [])
    check("the four BR-1006 replies are exactly 'Theek hai.'", all(agent.ACK_REPLY[agent.template_language("hi", t)] == "Theek hai."
          for t in ("हाँ, बिलकुल.", "हाँ, सही है", "धन्यवाद")))
    r = ra("thank you", C, trip=TRIP, stt="en")
    check("English ack -> 'Okay.'", r.reply_text == "Okay." and r.action == "ack" and len(FakeLLM.calls) == n, r.reply_text)
    check("an ack with no draft but a different conversation behaves the same", ra("धन्यवाद", f"conv_ack_{uuid.uuid4().hex[:6]}").action == "ack")

    # ---- real requests still go to the model
    r = ra("Mujhe Delhi se Jaipur jana hai", C, trip=TRIP,
           queue=[("tool", ("update_trip_draft", {"destination": "Jaipur", "origin_city": "Delhi", "start_new": True}))])
    check("a new trip request after the created trip -> a fresh draft (the model is called)", len(FakeLLM.calls) == n + 1
          and r.action == "trip_draft" and D.load(redis_conn, USER, C).destination["name"] == "Jaipur"
          and D.load(redis_conn, USER, C).start_date is None, r.reply_text)
    n = len(FakeLLM.calls)
    r = ra("haan", C, trip=TRIP, queue=[("text", "Kab se jaana hai?")])
    check("regression: with an open draft a bare 'haan' still goes to the model as before", len(FakeLLM.calls) == n + 1
          and r.action != "ack", r.action)
    agent.cancel_trip(redis_conn, USER, C, "hi")
    n = len(FakeLLM.calls)
    r = ra("home page par chalo", C, trip=TRIP, queue=[("tool", ("navigate", {"page": "home"}))])
    check("'home page par chalo' -> the model (navigate)", len(FakeLLM.calls) == n + 1 and r.action != "ack", r.action)
    r = ra("Calangute beach kahan hai?", C, trip=TRIP, queue=[("text", "Calangute North Goa mein hai. Map par dikhaun?")])
    check("a question -> the model", len(FakeLLM.calls) == n + 2 and r.action != "ack", r.action)
    r = ra("haan theek hai, accha laga, ab Baga beach bhi batao", C, trip=TRIP, queue=[("text", "Baga beach Calangute ke paas hai.")])
    check("an ack word inside a real request -> the model", len(FakeLLM.calls) == n + 3 and r.action != "ack", r.action)

    # the model's own question is still answered through the model ("Kitna budget hai?" -> "haan" / "500 hai")
    agent.clear_memory(redis_conn, USER, C)
    n = len(FakeLLM.calls)
    ra("budget mein fit karo", C, trip=TRIP, queue=[("text", "Kitna budget hai?")])
    r = ra("500 hai", C, trip=TRIP, queue=[("text", "Budget kam se kam 1,000 rupaye hona chahiye. Kitna rakhein?")])
    check("'500 hai' after the model's question -> the model (digits are never an ack)", len(FakeLLM.calls) == n + 2 and r.action != "ack", r.action)
    r = ra("haan", C, trip=TRIP, queue=[("text", "Theek hai, kitna?")])
    check("'haan' right after the model asked something -> the model as before", len(FakeLLM.calls) == n + 3 and r.action != "ack", r.action)
    check("unit: acks / not acks", [agent.is_acknowledgement(t) for t in ("हाँ, बिलकुल.", "dhanyavaad ji", "ok", "500 hai",
          "trip bana do", "shuru karo", "home page par chalo", "haan theek hai Goa chalo")] == [True, True, True, False, False, False, False, False])
    agent.clear_memory(redis_conn, USER, C)

    # map follow-up: "... Map par dikhaun?" -> "haan" shows the kept map action (no model call, not an ack)
    agent.save_pending(redis_conn, USER, C, [{"type": "map_focus", "name": "Calangute Beach", "lat": 15.54, "lng": 73.75}])
    n = len(FakeLLM.calls)
    r = ra("haan", C, trip=TRIP)
    check("regression: 'haan' to 'Map par dikhaun?' -> map_focus", r.action == "map_focus" and len(FakeLLM.calls) == n, r.action)
    r = ra("map par dikhao", C, trip=TRIP, queue=[("tool", ("navigate", {"page": "map"}))])
    check("'map par dikhao' -> the model as before", len(FakeLLM.calls) == n + 1 and r.action != "ack", r.action)

    # a booking question open: "haan" is still the booking answer
    redis_conn.delete(f"booking:flow:{USER}:{T}")
    with database.engine.begin() as c:
        c.execute(sql("UPDATE booking_requests SET status = 'cancelled' WHERE status IN ('new', 'contacted')"))
    ra("hotel book karwana hai", C, trip=TRIP)
    for said in ("budget", "do kamre", "Roshan, 30 saal", "Mohan, 40 saal", "9876543210"):
        r = ra(said, C, trip=TRIP)
    r = ra("haan", C, trip=TRIP)
    check("regression: 'haan' at a booking question is the booking answer, not an ack", r.action == "booking"
          and BF.current_question(BF.load(redis_conn, USER, T)) == "review", r.action)
    BF.cancel(redis_conn, USER, T)

    # the Confirm card of another big action: "haan" still confirms it
    agent.clear_memory(redis_conn, USER, C)
    P.save(redis_conn, USER, C, "add_expense", "x", {})
    for said in ("haan", "धन्यवाद"):
        P.save(redis_conn, USER, C, "add_expense", "x", {})
        r = ra(said, C, trip=TRIP, queue=[("text", "Theek hai, expense nahi joda.")])
        check(f"regression: {said!r} with a pending confirmation is never an ack", r.action != "ack", r.action)
    agent.clear_memory(redis_conn, USER, C)

logs = log_buf.getvalue()
check("log: the ack action is logged", "action=ack" in logs)
leaks = [w for w in ("बिलकुल", "धन्यवाद", "Roshan", "Mohan", "9876543210", "98765", "Kolkata", "shukriya") if w in logs]
check("logs: no words, names or numbers", not leaks, leaks)

agent.clear_memory(redis_conn, USER)
for k in redis_conn.scan_iter(f"booking:flow:{USER}:*"):
    redis_conn.delete(k)
print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if results and all(results) else 1)
