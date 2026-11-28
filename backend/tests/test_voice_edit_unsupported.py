"""
An open trip must not start a new trip draft, and voice must not claim to edit a trip (feat/trip-purpose commit 1).

Evidence: with a Kolkata -> Bengaluru trip open, "...hackathon ke liye ... mera trip plan karo ... Electronic City",
"route tour package jo tumne banaya hai, usmein hi ye fix karna hai", "terah tarikh ko mujhe ye add karna hai" and
"13 tarikh ko Electronic City ... optimize karke do" started new trip drafts, and the model said it was updating the
trip (voice has no tool that adds to an itinerary).
Checks: those four with a trip open and no draft -> the fixed reply, no model call, no draft, no navigation, action
edit_unsupported, not in the voice memory; the same words with a draft in progress still go to the draft; a new trip
request, map / open / back / home / booking and the existing trip tools (optimize a day, weather replan, budget,
expense, swap, regenerate, unsave) still reach the model or their own branch; with no trip open it is not this branch.
App DB = SQLite, Redis = local, the model and place search simulated.
Run from backend/: python -m tests.test_voice_edit_unsupported
"""
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

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

import database  # noqa: E402

database.engine = create_engine(f"sqlite:///{os.path.join(SCRATCH, 'edit.db')}", connect_args={"check_same_thread": False})
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

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail != "" else ""), flush=True)


TODAY = today_ist()
d = lambda n: (TODAY + timedelta(days=n)).isoformat()  # noqa: E731
NOW = datetime.now(timezone.utc)
USER = f"usr_edit_{uuid.uuid4().hex[:6]}"
PLACES = {
    "bengaluru": [{"id": "ChIJblr", "place_id": "ChIJblr", "name": "Bengaluru", "latitude": 12.97, "longitude": 77.59,
                   "city": "Bengaluru, Karnataka, India"}],
    "electronic city": [{"id": "ChIJec", "place_id": "ChIJec", "name": "Electronic City", "latitude": 12.84,
                         "longitude": 77.66, "city": "Bengaluru, Karnataka, India"}],
    "goa": [{"id": "ChIJgoa", "place_id": "ChIJgoa", "name": "Goa", "latitude": 15.29, "longitude": 74.12, "city": "Goa, India"}],
    "kolkata": [{"id": "ChIJkol", "place_id": "ChIJkol", "name": "Kolkata", "latitude": 22.57, "longitude": 88.36,
                 "city": "Kolkata, West Bengal, India"}],
}
fake_search = lambda q: PLACES.get(q.strip().lower(), [])  # noqa: E731


class FakeLLM:
    """What the real model did: every call starts a new trip draft for Electronic City, unless a reply is queued."""
    queue, calls = [], []

    def __call__(self, messages, tools, **kw):
        FakeLLM.calls.append(messages)
        if FakeLLM.queue:
            kind, payload = FakeLLM.queue.pop(0)
            if kind == "text":
                return {"content": payload, "tool_calls": []}
            return {"content": None, "tool_calls": [{"name": payload[0], "arguments": payload[1]}]}
        return {"content": None, "tool_calls": [{"name": "update_trip_draft", "arguments": {"destination": "Electronic City"}}]}


fake = FakeLLM()


def make_trip():
    tid = f"trip_edit_{uuid.uuid4().hex[:8]}"
    with database.SessionLocal() as db:
        db.add(TripModel(id=tid, user_id=USER, title="Bengaluru Tour Package", status="PLANNING", start_date=d(14),
                         end_date=d(17), total_days=4, destination={"name": "Bengaluru"},
                         travelers=[{"id": "tr_1", "type": "ADULT"}], budget={"targetAmount": 60000},
                         created_at=NOW, updated_at=NOW, itinerary_status="READY"))
        db.commit()
    return tid


def ra(text, conv, trip=None, queue=None, screen="/trip", stt="hi"):
    if queue is not None:
        FakeLLM.queue = list(queue)
    return agent.run_agent(text, stt, user_id=USER, conversation_id=conv, screen=screen, trip=trip, redis_conn=redis_conn)


def fresh():
    conv = f"conv_{uuid.uuid4().hex[:8]}"
    agent.clear_memory(redis_conn, USER, conv)
    D.delete(redis_conn, USER, conv)
    P.clear(redis_conn, USER, conv)
    return conv


EVIDENCE = [
    "एक्चुअली मैं हैकाथॉन के लिए जा रहा हूँ, तो उस हिसाब से मेरा ट्रिप प्लान करो... इलेक्ट्रॉनिक सिटी...",
    "रूट टूर पैकेज जो तुमने बनाया है, उसमें ही ये फिक्स करना है...",
    "तेरह तारीख को मुझे ये ऐड करना है।",
    "मुझे 13 तारीख को इलेक्ट्रॉनिक सिटी बैंगलोर में ही जाना है... ऑप्टिमाइज़ करके दो।",
]
MORE_EDITS = [   # Hinglish and English forms of the same request
    ("isi trip mein Electronic City add karo", "hi"),
    ("jo plan banaya hai usme Electronic City jod do", "hi"),
    ("hackathon ke hisaab se mera itinerary badlo", "hi"),
    ("Add Electronic City to my trip", "en"),
    ("Please update the itinerary for my hackathon", "en"),
]
STILL_MODEL = [   # with a trip open and no draft: these must still reach the model
    "Nayi trip banao Goa ke liye",
    "नई ट्रिप बनानी है, गोवा के लिए, इसमें दो लोग",
    "new trip plan karo Goa ka, isme 2 log",
    "map par Electronic City dikhao",
    "trip kholo",
    "ट्रिप पे वापस चलो",
    "day 2 optimize karo",
    "aaj ka route chhota karo",
    "plan badlo",                    # test_voice_step6: weather_replan asks first
    "day 2 plan badlo",
    "kal ka plan mausam ke hisaab se karo",
    "relaxed karo day 2",
    "route chhota karo",
    "isko change karo",              # "this" alone may be the activity on screen
    "aaj baarish hai, plan badlo",
    "budget 25000 kar do",
    "budget badal ke 40 hazaar rakho",
    "budget mein fit karo, plan optimize karo",
    "auto ka 350 add karo",
    "Amber Fort ki jagah kuch aur",
    "trip ka plan dobara banao",
    "Hawa Mahal saved se hatao",
    "Electronic City kitni door hai",
]

with mock.patch.object(openai_client, "chat_tools", fake), mock.patch.object(places, "search_places", fake_search):
    trip = agent.TripInfo(title="Bengaluru Tour Package", start_date=d(14), end_date=d(17), id=make_trip())

    print("\n== 1. the four evidence transcripts, trip open, no draft: fixed reply, no model, no draft")
    for text in EVIDENCE:
        conv = fresh()
        before = len(FakeLLM.calls)
        r = ra(text, conv, trip=trip)
        short = text[:28]
        check(f"'{short}...' -> edit_unsupported", r.action == "edit_unsupported", r.action)
        check(f"'{short}...' -> no model call", len(FakeLLM.calls) == before)
        check(f"'{short}...' -> no draft", D.load(redis_conn, USER, conv) is None)
        check(f"'{short}...' -> no navigation, no Confirm card", not r.ui_actions and r.pending_confirmation is None)
        check(f"'{short}...' -> Hindi fixed reply", r.reply_text == agent.EDIT_UNSUPPORTED_REPLY["hi"], r.reply_text)
        check(f"'{short}...' -> not in the voice memory", agent.load_memory(redis_conn, USER, conv) == [])

    print("\n== 2. other wordings of an edit request")
    for text, lang in MORE_EDITS:
        conv = fresh()
        before = len(FakeLLM.calls)
        r = ra(text, conv, trip=trip, stt=lang)
        check(f"'{text}' -> edit_unsupported ({lang}), no model call",
              r.action == "edit_unsupported" and len(FakeLLM.calls) == before
              and r.reply_text == agent.EDIT_UNSUPPORTED_REPLY[lang], f"{r.action} | {r.reply_text}")

    print("\n== 3. the reply names only controls that exist and never claims a change")
    for lang, reply in agent.EDIT_UNSUPPORTED_REPLY.items():
        low = reply.lower()
        check(f"{lang}: names Swap, Optimize Day and Add to Itinerary", "swap" in low and "optimize day" in low
              and "add to itinerary" in low)
        check(f"{lang}: no 'update karta' / 'updating' claim", "karta hoon" not in low.replace("bana sakta hoon", "")
              and "updating" not in low)

    print("\n== 4. with a draft in progress the same words still go to the draft (the model is reached)")
    for text in EVIDENCE + ["20 नहीं 12 दिसंबर"]:
        conv = fresh()
        D.save(redis_conn, USER, conv, D.TripDraftState(destination=PLACES["goa"][0] | {"city": "Goa"}, start_date=d(20),
                                                       end_date=d(22), origin_skipped=True))
        before = len(FakeLLM.calls)
        r = ra(text, conv, trip=trip, queue=[("tool", ("update_trip_draft", {"start_day": 12, "start_month": 12}))])
        check(f"draft + '{text[:24]}...' -> model + draft", len(FakeLLM.calls) == before + 1 and r.action == "trip_draft",
              r.action)

    print("\n== 5. a trip open but other requests: the model (or their own branch) as before")
    for text in STILL_MODEL:
        conv = fresh()
        before = len(FakeLLM.calls)
        r = ra(text, conv, trip=trip, queue=[("text", "Theek hai.")])
        check(f"'{text}' -> reaches the model", r.action != "edit_unsupported" and len(FakeLLM.calls) == before + 1,
              r.action)
    conv = fresh()
    r = ra("home page par chalo", conv, trip=trip, queue=[("tool", ("navigate", {"page": "home"}))])
    check("'home page par chalo' -> navigate", r.action.startswith("navigate"), r.action)
    conv = fresh()
    before = len(FakeLLM.calls)
    r = ra("booking karwana hai", conv, trip=trip)
    check("'booking karwana hai' -> the booking branch, never edit_unsupported",
          r.action == "booking" and len(FakeLLM.calls) == before, r.action)

    print("\n== 6. no trip open: not this branch (the model decides, as before)")
    for text in ["trip mein Electronic City add karo", EVIDENCE[1]]:
        conv = fresh()
        before = len(FakeLLM.calls)
        r = ra(text, conv, trip=None, screen="/home")
        check(f"no trip + '{text[:24]}...' -> model", r.action != "edit_unsupported" and len(FakeLLM.calls) == before + 1,
              r.action)

    print("\n== 7. a pending confirmation open: not this branch")
    conv = fresh()
    P.save(redis_conn, USER, conv, "create_trip", "Goa trip")
    before = len(FakeLLM.calls)
    r = ra(EVIDENCE[1], conv, trip=trip, queue=[("text", "Theek hai.")])
    check("pending confirmation + edit words -> model", r.action != "edit_unsupported" and len(FakeLLM.calls) == before + 1,
          r.action)

    print("\n== 8. the system prompt has the new line")
    prompt = agent.build_system_prompt("/trip", trip)
    check("prompt: cannot edit an existing itinerary", "You cannot edit, add to or optimise an existing itinerary. Never say "
          "you are updating or changing a trip. If the user asks for that, say it cannot be done by voice yet." in prompt)

    for conv_key in redis_conn.scan_iter(f"voice:*:{USER}:*"):
        redis_conn.delete(conv_key)

with database.SessionLocal() as db:
    db.query(TripModel).filter(TripModel.user_id == USER).delete()
    db.commit()

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
