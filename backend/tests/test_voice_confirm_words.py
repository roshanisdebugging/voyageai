"""
Voice trip confirmation with natural yes-phrases (voice/confirm_words.py): app DB = SQLite, Redis = local, the model
and place search simulated. "सही है।" / "बना दो।" / "हाँ, बना दो।" confirm like "haan" with no model call;
negation, hold, new trip data and long sentences don't.
Run from backend/: python -m tests.test_voice_confirm_words
"""
import os
import sys
import tempfile
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

database.engine = create_engine(f"sqlite:///{os.path.join(SCRATCH, 'voiceconfirm.db')}", connect_args={"check_same_thread": False})
database.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=database.engine)

import main  # noqa: E402
import openai_client  # noqa: E402
import places  # noqa: E402
from models_trip import TripModel  # noqa: E402
from redis_client import redis_conn  # noqa: E402
from trip_lifecycle import today_ist  # noqa: E402
from voice import agent, draft as D, pending as P  # noqa: E402

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
USER_A = f"usr_cw_{uuid.uuid4().hex[:6]}"
USER_B = f"usr_s4b_{uuid.uuid4().hex[:6]}"
PLACES = {
    "goa": [{"id": "ChIJgoa", "place_id": "ChIJgoa", "name": "Goa", "latitude": 15.29, "longitude": 74.12, "city": "Goa, India"}],
    "jaipur": [{"id": "ChIJjpr", "place_id": "ChIJjpr", "name": "Jaipur", "latitude": 26.91, "longitude": 75.79, "city": "Jaipur, Rajasthan, India"}],
    "delhi": [{"id": "ChIJdel", "place_id": "ChIJdel", "name": "New Delhi", "latitude": 28.61, "longitude": 77.21, "city": "New Delhi, Delhi, India"}],
    "kolkata": [{"id": "ChIJkol", "place_id": "ChIJkol", "name": "Kolkata", "latitude": 22.57, "longitude": 88.36, "city": "Kolkata, West Bengal, India"}],
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



from voice.confirm_words import is_positive_confirmation as YES  # noqa: E402

# ---------------- the helper alone
yes_cases = ["सही है।", "बना दो।", "हाँ, बना दो।", "हाँ।", "haan bana dijiye", "haan bilkul theek hai", "ok chalo", "ट्रिप बना दो",
             "yes please go ahead", "theek hai", "ji", "pakka", "proceed", "बना दीजिए", "हां जी, कर दो"]
no_cases = ["nahi", "haan par dates badlo", "mat bana do", "ruko", "galat hai", "haan, par chaar din ke liye", "haan Goa",
            "haan 3 din", "do", "ok so I was thinking we should maybe go to Goa now", "wait", "cancel karo", "nahin bana do",
            "haan 25 december se", "haan teen log", "haan budget 50 hazaar"]
bad = [t for t in yes_cases if not YES(t)] + [t for t in no_cases if YES(t)]
check("helper: natural yeses accepted, negation / hold / new data / long sentences refused", not bad, bad)
check("helper: more than 8 words with one 'ok' is not a yes", not YES("ok ok but first tell me about the weather there please"))


def to_review(conv):
    """Kolkata -> Goa, 3 adults: the read-back, then 'सही है।' -> the review page (no model call)."""
    r = ra("Kolkata se Goa, 25 se 27, teen log", USER_A, conv, queue=[("tool", ("update_trip_draft", {
        "origin_city": "Kolkata", "destination": "Goa", "start_date": d(20), "end_date": d(22), "adults": 3, "children": 0,
        "budget_inr": 50000}))])
    assert r.step == "confirm_date" and r.reply_text.startswith("Kolkata se Goa,") and r.reply_text.endswith("Sahi hai?"), r.reply_text
    n = len(FakeTools.calls)
    r = ra("सही है।", USER_A, conv)
    return r, len(FakeTools.calls) == n


def confirmed(r):
    return r.action == "trip_confirm" and r.ui_actions == [{"type": "submit_review"}] and r.reply_text in agent.CONFIRMED_REPLY.values()   # an English sentence gets the English reply, as "yes" does


with mock.patch.object(openai_client, "chat_tools", fake), mock.patch.object(places, "search_places", fake_search):
    # ---------------- the real transcript
    C = f"conv_cw_{uuid.uuid4().hex[:6]}"
    r, no_llm = to_review(C)
    check("evidence 1: 'सही है।' to the read-back -> the review page, no model call (as before)",
          r.step == "ready" and r.reply_text == agent.READY_REPLY["hi"] and no_llm, r.reply_text)
    n = len(FakeTools.calls)
    r = ra("बना दो।", USER_A, C)
    check("evidence 2: 'बना दो।' at the review page -> 'Trip bana raha hoon.' + Proceed, no model call",
          confirmed(r) and len(FakeTools.calls) == n, (r.reply_text, r.action))
    check("... the same state change as 'haan': draft and pending cleared", D.load(redis_conn, USER_A, C) is None
          and P.get(redis_conn, USER_A, C) is None)

    for text in ("सही है।", "हाँ, बना दो।", "बना दो।", "हाँ।", "haan bana dijiye", "haan bilkul theek hai", "ok chalo", "ट्रिप बना दो",
                 "yes please go ahead"):
        C = f"conv_cw_{uuid.uuid4().hex[:6]}"
        to_review(C)
        n = len(FakeTools.calls)
        r = ra(text, USER_A, C)
        check(f"review page: {text!r} confirms with no model call", confirmed(r) and len(FakeTools.calls) == n
              and D.load(redis_conn, USER_A, C) is None, (r.reply_text, r.action))

    # a natural yes at the read-back: the same as "haan" there (-> the review page, not straight to creation)
    C = f"conv_cw_{uuid.uuid4().hex[:6]}"
    ra("Kolkata se Goa", USER_A, C, queue=[("tool", ("update_trip_draft", {"origin_city": "Kolkata", "destination": "Goa",
        "start_date": d(20), "end_date": d(22), "adults": 3, "children": 0, "budget_inr": 50000}))])
    n = len(FakeTools.calls)
    r = ra("haan bana dijiye", USER_A, C)
    check("read-back: 'haan bana dijiye' -> the review page (same as 'haan' there), no model call",
          r.step == "ready" and len(FakeTools.calls) == n and P.get(redis_conn, USER_A, C) is not None, r.reply_text)
    P.clear(redis_conn, USER_A, C)
    D.delete(redis_conn, USER_A, C)

    # ---------------- negation / hold / new data / long: never confirmed
    for text in ("haan par dates badlo", "mat bana do", "ruko", "galat hai", "haan, par chaar din ke liye",
                 "ok but first tell me how is the weather in Goa these days"):
        C = f"conv_cw_{uuid.uuid4().hex[:6]}"
        to_review(C)
        r = ra(text, USER_A, C, queue=[("text", "Theek hai.")])
        check(f"review page: {text!r} does not confirm (handled as before)", r.action != "trip_confirm"
              and {"type": "submit_review"} not in r.ui_actions, (r.reply_text, r.action))
    C = f"conv_cw_{uuid.uuid4().hex[:6]}"
    to_review(C)
    r = ra("nahi", USER_A, C)
    check("review page: 'nahi' cancels as before", r.reply_text == agent.CANCELLED_REPLY["hi"] and D.load(redis_conn, USER_A, C) is None,
          r.reply_text)

    # ---------------- not wired elsewhere: no draft -> "बना दो" goes to the model as before
    C = f"conv_cw_{uuid.uuid4().hex[:6]}"
    n = len(FakeTools.calls)
    r = ra("बना दो", USER_A, C, queue=[("text", "Kya banana hai?")])
    check("no trip draft: 'बना दो' is not a confirmation (model called as before)", len(FakeTools.calls) == n + 1
          and r.action != "trip_confirm", r.action)

check("the voice side never creates a trip itself", trips_of(USER_A) == 0)
print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
