"""
Booking stage 2 checks (questions only; nothing saved, nothing sent). App DB = SQLite, Redis = local, model simulated.
Screen (WS booking:* and REST) and voice (run_agent) share one Redis state; every service combination; "aap decide
karo" at every service question; invalid names / ages / phones; child 25 and adult 10 asked to confirm; phone
read-back yes and no; change one part at the review; "abhi nahi" at every step; resume; TTL expiry; another user
refused; Devanagari / Hinglish / English; logs without names or numbers; the app database unchanged.
Run from backend/: python -m tests.test_booking_flow
"""
import hashlib
import io
import itertools
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

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)
SCRATCH = tempfile.mkdtemp(prefix="voyageai_test_")

from sqlalchemy import create_engine, text as sql  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

import database  # noqa: E402

database.engine = create_engine(f"sqlite:///{os.path.join(SCRATCH, 'booking.db')}", connect_args={"check_same_thread": False})
database.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=database.engine)

import main  # noqa: E402
import openai_client  # noqa: E402
import booking_flow as BF  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from models_trip import TripModel  # noqa: E402
from redis_client import redis_conn  # noqa: E402
from trip_lifecycle import today_ist  # noqa: E402
from voice import agent, booking_voice as V, pending as P  # noqa: E402

main.SessionLocal = database.SessionLocal


async def _no_ws_limit(*a, **k):   # this script sends a few hundred frames a minute; the limiter is tested elsewhere
    return None


main.check_ws_rate_limit = _no_ws_limit
database.Base.metadata.create_all(bind=database.engine)
for key in redis_conn.scan_iter("rl:*"):
    redis_conn.delete(key)

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail != "" else ""), flush=True)


TODAY = today_ist()
d = lambda n: (TODAY + timedelta(days=n)).isoformat()  # noqa: E731
NOW = datetime.now(timezone.utc).isoformat()

client = TestClient(main.app)
client.__enter__()
toks = {}
for who in ("A", "B"):
    r = client.post("/api/auth/register", json={"name": f"Asha {who}k", "email": f"bk{who.lower()}_{uuid.uuid4().hex[:6]}@example.com",
                                                "password": "secret123"})
    toks[who] = (r.json()["token"], r.json()["user"]["id"])
client.cookies.clear()
tok_a, uid_a = toks["A"]
tok_b, uid_b = toks["B"]


def make_trip(uid, adults, children, start=5, past=False):
    tid = f"trip_bk_{uuid.uuid4().hex[:8]}"
    travelers = [{"id": f"tr_{i}", "name": f"Adult {i}", "type": "ADULT"} for i in range(adults)] + \
                [{"id": f"tc_{i}", "name": f"Child {i}", "type": "CHILD"} for i in range(children)]
    with database.SessionLocal() as db:
        db.add(TripModel(id=tid, user_id=uid, title="Goa", status="PLANNING",
                         start_date=d(-6 if past else start), end_date=d(-3 if past else start + 2), total_days=3,
                         destination={"name": "Goa"}, travelers=travelers, budget={"targetAmount": 50000},
                         created_at=NOW, updated_at=NOW, itinerary_status="READY"))
        db.commit()
    return tid


T1 = make_trip(uid_a, 1, 0)        # one adult (the account holder)
T2 = make_trip(uid_a, 2, 1)        # two adults + one child
T_PAST = make_trip(uid_a, 1, 0, past=True)
T_B = make_trip(uid_b, 1, 0)


def db_snapshot():
    """Every table's rows, hashed: the booking flow must not change the database."""
    out = {}
    with database.engine.connect() as c:
        for table in sorted(database.Base.metadata.tables):
            rows = c.execute(sql(f'SELECT * FROM "{table}"')).fetchall()
            out[table] = hashlib.sha256(repr(sorted(map(repr, rows))).encode()).hexdigest()
    return out


def ws(token, action, payload):
    with client.websocket_connect("/ws/app") as sock:
        sock.send_json({"id": "x", "action": action, "payload": {**payload, "token": token}})
        while True:
            f = sock.receive_json()
            if f.get("id") == "x":
                return f


def wsd(action, trip, token=tok_a, **payload):
    f = ws(token, action, {"trip_id": trip, **payload})
    return f["data"] if f["status"] == 200 else {"_status": f["status"], "_error": f["error"]}


def ans(trip, value, token=tok_a):
    g = wsd("booking:get", trip, token)
    if "question" not in g:
        print("DEBUG get:", g)
    q = g["question"]
    return wsd("booking:answer", trip, token, question=q, value=value)


def key(uid, trip):
    return f"booking:flow:{uid}:{trip}"


log_buf = io.StringIO()
_h = logging.StreamHandler(log_buf)
for name in ("booking", "voice"):
    logging.getLogger(name).addHandler(_h)
    logging.getLogger(name).setLevel(logging.INFO)

BEFORE = db_snapshot()

# ---------------- pure rules
check("name: Roman letters and spaces", BF.clean_name("  Rahul   Sharma ") == "Rahul Sharma")
check("name: Devanagari with vowel marks", BF.clean_name("राहुल शर्मा") == "राहुल शर्मा")
check("name: digits / symbols / 1 letter / 61 chars refused",
      [BF.clean_name(x) for x in ("Rahul123", "Rahul_S", "R", "A" * 61, "", "R@hul")] == [None] * 6)
check("phone: 10 digits, +91, 0 prefix, spaces", [BF.normalize_phone(x) for x in
      ("9876543210", "+91 98765 43210", "09876543210", "919876543210", "98765-43210")] == ["9876543210"] * 5)
check("phone: letters, 9 digits, starts with 5, 11 digits refused", [BF.normalize_phone(x) for x in
      ("98765abc10", "987654321", "5876543210", "98765432101", "")] == [None] * 5)
check("age: whole numbers 0..110 only", [BF.parse_age(x) for x in (0, "34", 110, 111, -1, "3.5", "abc", True)]
      == [0, 34, 110, None, None, None, None, None])
check("read-back digit by digit", BF.spaced_digits("9876543210") == "9 8 7 6 5, 4 3 2 1 0")

# spoken words
check("phone words: Hinglish", V.phone_digits("nau aath saat chhe paanch chaar teen do ek shunya") == "9876543210")
check("phone words: Devanagari", V.phone_digits("नौ आठ सात छह पांच चार तीन दो एक शून्य") == "9876543210")
check("phone words: English + double", V.phone_digits("nine eight seven six double five four three two one") == "9876554321")
check("phone words: digits with +91 and filler", BF.normalize_phone(V.phone_digits("mera number hai +91 98765 43210")) == "9876543210")
check("phone words: Devanagari digits", BF.normalize_phone(V.phone_digits("९८७६५ ४३२१०")) == "9876543210")
check("phone words: other words -> not read by code", V.phone_digits("Rahul ka number") is None)
check("numbers: 34 / thirty four / चौंतीस / chaubees", [V.numbers_in(V.tokens(x)) for x in ("34 saal", "thirty four", "चौंतीस साल", "chaubees")]
      == [[34], [34], [34], [24]])
check("name+age: 'Mera naam Rahul Sharma hai, 34 saal'", V.name_and_age("Mera naam Rahul Sharma hai, 34 saal") == ("Rahul Sharma", 34, False))
check("name+age: 'प्रिया, उम्र तीस'", V.name_and_age("प्रिया, उम्र तीस") == ("प्रिया", 30, False))
check("name+age: an unknown number word next to 'saal' -> unsure", V.name_and_age("Rahul chautees saal")[2] is True)
check("trigger: Hinglish / Devanagari / English", all(V.is_trigger(x) for x in
      ("book karwana hai", "hotel book karo", "मुझे ट्रेन बुक करनी है", "book a flight please", "होटल बुक करो")))
check("trigger: cab / taxi / table bookings are not ours", not any(V.is_trigger(x) for x in
      ("cab book karo", "taxi book kar do", "restaurant mein table book karo", "कैब बुक करो", "Hawa Mahal kahan hai")))
check("cancel words", all(V.is_cancel(x) for x in ("abhi nahi", "chhodo", "cancel", "अभी नहीं", "रहने दो", "not now"))
      and not any(V.is_cancel(x) for x in ("nahi", "tatkal nahi chahiye", "नहीं")))
check("services: one / several / all", [V.services_in(V.tokens(x)) for x in ("hotel", "flight aur train", "teeno", "ट्रेन और होटल")]
      == [["hotel"], ["flight", "train"], ["flight", "train", "hotel"], ["train", "hotel"]])
C = V.parse_choice
check("choices: times", [C("flight_time", x) for x in ("subah", "शाम को", "late night", "dopahar ke baad", "aap decide karo")]
      == ["morning", "evening", "night", "afternoon", "any"])
check("choices: two times -> no guess", C("train_time", "subah ya shaam") is None)
check("choices: train class", [C("train_class", x) for x in ("sleeper", "3AC", "third AC", "थर्ड एसी", "2 tier", "first class", "koi bhi")]
      == ["SL", "3A", "3A", "3A", "2A", "1A", "any"], [C("train_class", x) for x in ("sleeper", "3AC", "third AC", "थर्ड एसी", "2 tier", "first class", "koi bhi")])
check("choices: hotel type", [C("hotel_type", x) for x in ("budget", "3 star", "4-star se upar", "फाइव स्टार", "सस्ता", "aap dekh lo")]
      == ["budget", "3star", "4plus", "4plus", "budget", "any"])
check("choices: rooms", [C("hotel_rooms", x) for x in ("do kamre", "3", "एक कमरा", "aap decide karo")] == [2, 3, 1, "any"])
check("choices: yes / no / decide", [C("train_tatkal", x) for x in ("haan chalega", "nahi", "नहीं चाहिए", "aap decide karo")]
      == ["yes", "no", "no", "any"])
check("choices: elderly 'koi bhi nahi' is a no, not 'any'", C("hotel_elderly", "koi bhi nahi") == "no")
check("choices: airline", [C("flight_airline", x) for x in ("jo sasta mile", "IndiGo", "koi khaas airline", "you decide")]
      == ["cheapest", "Indigo", "__ask_airline__", "any"])

# ---------------- screen: every service combination, "aap decide karo" at every service question
combos = [list(c) for n in (1, 2, 3) for c in itertools.combinations(BF.SERVICES, n)]
for combo in combos:
    v = wsd("booking:start", T1)
    ok = v.get("question") == "services" and v["progress"]["label"] == "1 of %d" % 4 and v["testNote"].startswith("Test version")
    v = ans(T1, combo)
    asked = []
    while v.get("kind") == "choice":
        asked.append(v["question"])
        v = ans(T1, "any")
    want = [q for s_ in BF.SERVICES if s_ in combo for q in BF.SERVICE_QUESTIONS[s_]]
    ok = ok and asked == want
    ok = ok and v["question"] == "t0_name" and v["choices"] and v["choices"][0]["value"] == "yes"   # account name offered
    v = ans(T1, "yes")
    v = ans(T1, "34")
    v = ans(T1, "+91 98765 43210")
    ok = ok and v["question"] == "phone_ok" and "9 8 7 6 5, 4 3 2 1 0" in v["prompt"]
    v = ans(T1, "yes")
    ok = ok and v["question"] == "review" and v["consent"] == "Ye details hamare booking partner ko bheji jayengi."
    ok = ok and any(line["part"] == "travellers" and "Asha Ak (34)" in line["text"] for line in v["summary"])
    ok = ok and all(("bujurg" not in line["text"].lower() or "Aap decide karo" in line["text"]) for line in v["summary"])
    v = ans(T1, "yes")
    ok = ok and v.get("finished") and v["message"] == "Abhi ye test hai. Kuch bheja nahi gaya." and not redis_conn.exists(key(uid_a, T1))
    check(f"screen: {'+'.join(combo)} -> only its questions, 'any' accepted, review, test message, state deleted", ok, asked)

# invalid answers + confirm-once ages + read-back no + change one part
v = wsd("booking:start", T2, services=["hotel"])
check("screen: the card's service starts straight at its questions", v["question"] == "hotel_type")
check("screen: progress '2 of 5' (services, hotel, travellers, phone, review)", v["progress"]["label"] == "2 of 5")
v = ans(T2, "5star")
check("screen: a value outside the choices is refused", v["errorCode"] == "choice_invalid" and v["question"] == "hotel_type")
v = ans(T2, "3star")
v = ans(T2, "12")
check("screen: rooms 12 refused (1 to 9)", v["errorCode"] == "rooms_invalid")
v = ans(T2, "2")
v = ans(T2, "no")
v = ans(T2, "no")          # not the account holder's name
check("screen: 'no' to the offered name asks for the name", v["question"] == "t0_name" and not v["choices"])
for bad in ("Rahul123", "R", "Rahul_S", "A" * 61):
    v = ans(T2, bad)
    check(f"screen: name {bad[:12]!r} refused", v["errorCode"] == "name_invalid" and v["question"] == "t0_name")
v = ans(T2, "any")
check("screen: 'aap decide karo' for a name is refused", v["errorCode"] == "decide_not_allowed")
v = ans(T2, "Rahul Sharma")
for bad in ("abc", "111", "-1", "3.5"):
    v = ans(T2, bad)
    check(f"screen: age {bad!r} refused", v["errorCode"] == "age_invalid")
v = ans(T2, "10")
check("screen: adult aged 10 -> asked to confirm", v["question"] == "t0_age_confirm" and "bade yatri" in v["prompt"])
v = ans(T2, "no")
check("screen: 'no' asks the age again", v["question"] == "t0_age")
v = ans(T2, "40")
v = ans(T2, "Priya")
v = ans(T2, "38")
v = ans(T2, "Aryan")
v = ans(T2, "25")
check("screen: child aged 25 -> asked to confirm", v["question"] == "t2_age_confirm" and "bachche" in v["prompt"])
v = ans(T2, "yes")
check("screen: 'yes' keeps 25 and moves on", v["question"] == "phone")
for bad in ("98765abc10", "987654321", "5876543210"):
    v = ans(T2, bad)
    check(f"screen: phone {bad} refused", v["errorCode"] == "phone_invalid")
v = ans(T2, "9876543210")
v = ans(T2, "no")
check("screen: read-back 'no' asks the phone again", v["question"] == "phone")
v = ans(T2, "07654321098")
check("screen: new number read back", v["question"] == "phone_ok" and "7 6 5 4 3, 2 1 0 9 8" in v["prompt"])
v = ans(T2, "yes")
check("screen: review lists the 3 travellers", v["question"] == "review" and "Aryan (25)" in v["summary"][1]["text"])
v = ans(T2, "change:hotel")
check("screen: change hotel -> only the hotel questions again", v["question"] == "hotel_type")
v = ans(T2, "4plus"); v = ans(T2, "1"); v = ans(T2, "yes")
check("screen: ...then straight back to the review (travellers and phone kept)", v["question"] == "review"
      and "Rahul Sharma (40)" in v["summary"][1]["text"] and "76543 21098" in v["summary"][2]["text"])
v = ans(T2, "no")
check("screen: 'no' at the review asks what to change", v["question"] == "change" and len(v["choices"]) == 6)
v = ans(T2, "change:flight")
check("screen: changing to a new service adds its questions", v["question"] == "flight_time" and v["progress"]["total"] == 6)
v = wsd("booking:back", T2)
check("screen: Back from the first service question shows the services again, still selected",
      v["question"] == "services" and v["selected"] == ["flight", "hotel"], (v.get("question"), v.get("selected")))
v = ans(T2, ["flight", "hotel"])
check("screen: ...and Next keeps going (hotel answers kept)", v["question"] == "flight_time")
v = wsd("booking:answer", T2, question="hotel_type", value="budget")
check("screen: an answer to a stale question is refused", v["errorCode"] == "stale")

# resume, TTL
ttl = redis_conn.ttl(key(uid_a, T2))
check("state: kept 2 hours in Redis", 7000 < ttl <= 7200, ttl)
q_before = wsd("booking:get", T2)["question"]
check("state: leaving and coming back resumes at the same step", wsd("booking:start", T2)["question"] == q_before)
redis_conn.delete(key(uid_a, T2))           # what the 2-hour TTL does
v = wsd("booking:get", T2)
check("state: after expiry the screen sees no flow (the card offers again)", v["active"] is False and v["offer"])
v = wsd("booking:answer", T2, question=q_before, value="x")
check("state: an answer after expiry is not applied", v["active"] is False and v.get("expired"))
check("state: starting again is fresh", wsd("booking:start", T2)["question"] == "services")

# "abhi nahi" at every step (screen)
wsd("booking:cancel", T2)
steps_seen = []
for stop_at in range(0, 12):
    wsd("booking:start", T2)
    vals = [["train", "hotel"], "any", "any", "yes", "budget", "2", "no", "no", "Rahul", "40", "Priya", "38"]
    for val in vals[:stop_at]:
        ans(T2, val)
    steps_seen.append(wsd("booking:get", T2)["question"])
    r = wsd("booking:cancel", T2)
    if r.get("cancelled") is not True or redis_conn.exists(key(uid_a, T2)):
        break
check("screen: 'Abhi nahi' at every step discards the state", len(steps_seen) == 12 and not redis_conn.exists(key(uid_a, T2)), steps_seen)

# another user, past trip, REST
wsd("booking:start", T1)
f = ws(tok_b, "booking:get", {"trip_id": T1})
check("another user: WS booking:get on A's trip refused", f["status"] == 404 and f["data"] is None, f["status"])
f = ws(tok_b, "booking:answer", {"trip_id": T1, "question": "services", "value": ["hotel"]})
check("another user: WS booking:answer on A's trip refused, A's state untouched", f["status"] == 404
      and wsd("booking:get", T1)["question"] == "services")
f = ws(tok_b, "booking:cancel", {"trip_id": T1})
check("another user: WS booking:cancel refused, A's state kept", f["status"] == 404 and redis_conn.exists(key(uid_a, T1)))
H = lambda t: {"Authorization": f"Bearer {t}"}  # noqa: E731
check("another user: REST GET refused", client.get(f"/api/trips/{T1}/booking", headers=H(tok_b)).status_code == 404)
check("another user: REST answer refused", client.post(f"/api/trips/{T1}/booking/answer", headers=H(tok_b),
                                                       json={"question": "services", "value": ["hotel"]}).status_code == 404)
check("another user: REST cancel refused", client.delete(f"/api/trips/{T1}/booking", headers=H(tok_b)).status_code == 404
      and redis_conn.exists(key(uid_a, T1)))
check("logged out: REST refused", client.get(f"/api/trips/{T1}/booking").status_code == 401)
r = client.post(f"/api/trips/{T1}/booking/answer", headers=H(tok_a), json={"question": "services", "value": ["train"]})
check("REST: the owner can answer (same state as WS)", r.status_code == 200 and r.json()["question"] == "train_class"
      and wsd("booking:get", T1)["question"] == "train_class")
r = client.post(f"/api/trips/{T1}/booking/back", headers=H(tok_a))
check("REST: Back", r.status_code == 200 and r.json()["question"] == "services")
r = client.delete(f"/api/trips/{T1}/booking", headers=H(tok_a))
check("REST: cancel deletes the state", r.status_code == 200 and not redis_conn.exists(key(uid_a, T1)))
r = client.post(f"/api/trips/{T_PAST}/booking/start", headers=H(tok_a), json={})
check("past trip: refused", r.status_code == 400 and r.json()["detail"]["code"] == "trip_past")

# ---------------- voice
TRIP1 = agent.TripInfo(title="Goa", start_date=d(5), end_date=d(7), id=T1)
TRIP2 = agent.TripInfo(title="Goa", start_date=d(5), end_date=d(7), id=T2)


class FakeTools:
    queue, calls = [], []

    def __call__(self, messages, tools, **kw):
        FakeTools.calls.append([t["function"]["name"] for t in tools])
        if not FakeTools.queue:
            return {"content": "Model reply.", "tool_calls": []}
        name, args = FakeTools.queue.pop(0)
        return {"content": None, "tool_calls": [{"name": name, "arguments": args}]}


fake = FakeTools()


def say(text, conv, trip=TRIP2, user=None, stt="hi"):
    return agent.run_agent(text, stt, user_id=user or uid_a, conversation_id=conv, screen="/trip", trip=trip,
                           redis_conn=redis_conn)


with mock.patch.object(openai_client, "chat_tools", fake):
    for t in (T1, T2):
        redis_conn.delete(key(uid_a, t))
    FakeTools.calls = []
    r = say("book karwana hai", "conv_nt", trip=None)
    check("voice: no open trip -> 'Pehle trip kholiye' (no model call)", r.reply_text == "Pehle trip kholiye." and not FakeTools.calls)
    r = say("cab book karo", "conv_cab", trip=TRIP2)
    check("voice: 'cab book karo' is not ours (goes to the model as before)", r.action != "booking" and FakeTools.calls)

    # Hinglish, hotel, 2 adults + 1 child
    FakeTools.calls = []
    CV = f"conv_bk_{uuid.uuid4().hex[:6]}"
    agent.clear_memory(redis_conn, uid_a, CV)
    lines = []

    def turn(text, **kw):
        r = say(text, CV, **kw)
        lines.append((text, r.reply_text))
        print("   ", text, "->", r.reply_text)
        return r

    r = turn("hotel book karwana hai")
    check("voice hi: trigger with a service -> its first question", r.action == "booking"
          and r.reply_text.startswith("Hotel kaisa chahiye") and r.ui_actions == [{"type": "refresh", "what": "booking"}])
    check("voice hi: the screen sees the same state", wsd("booking:get", T2)["question"] == "hotel_type")
    r = turn("aap decide karo")
    check("voice hi: 'aap decide karo' -> next question", r.reply_text.startswith("Kitne kamre"))
    r = turn("do kamre")
    r = turn("nahi")
    check("voice hi: account name offered for traveller 1", "Pehle yatri Asha Ak hain?" in r.reply_text)
    r = turn("haan")
    check("voice hi: 'haan' takes the account name, asks the age", r.reply_text == "Asha Ak ki umar?")
    r = turn("10 saal")
    check("voice hi: adult aged 10 -> confirm once", "bade yatri ki jagah" in r.reply_text)
    r = turn("nahi")
    check("voice hi: 'nahi' asks the age again", r.reply_text == "Asha Ak ki umar?")
    r = turn("34 saal")
    r = turn("Priya, 30 saal")
    check("voice hi: name + age in one sentence fill both", r.reply_text == "Bachche 1 ka naam?", r.reply_text)
    r = turn("R")
    check("voice hi: a one-letter name -> the name rule + the question again",
          r.reply_text == "Naam mein sirf akshar ho sakte hain, 2 se 60 tak. Bachche 1 ka naam?", r.reply_text)
    r = turn("Aryan")
    r = turn("pachchees")
    check("voice hi: child aged 25 -> confirm once", "bachche ki jagah" in r.reply_text and "25" in r.reply_text)
    r = turn("haan")
    check("voice hi: phone asked", r.reply_text.startswith("Ek mobile number"))
    r = turn("paanch aath saat chhe paanch chaar teen do ek shunya")
    check("voice hi: number starting with 5 refused", r.reply_text.startswith("Ye number sahi nahi lagta"))
    r = turn("nau aath saat chhe paanch chaar teen do ek")
    check("voice hi: 9 digits refused", r.reply_text.startswith("Ye number sahi nahi lagta"))
    r = turn("nau aath saat chhe paanch chaar teen do ek shunya")
    check("voice hi: read back digit by digit", r.reply_text == "Number: 9 8 7 6 5, 4 3 2 1 0. Sahi hai?")
    r = turn("nahi, 9 1 2 3 4 5 6 7 8 9")
    check("voice hi: 'nahi' + a new number -> the new number read back", r.reply_text == "Number: 9 1 2 3 4, 5 6 7 8 9. Sahi hai?")
    r = turn("haan")
    check("voice hi: review read out short + consent", r.reply_text.startswith("Hotel:") and "3 yatri." in r.reply_text
          and "Ye details hamare booking partner ko bheji jayengi. Sahi hai?" in r.reply_text
          and "Priya" not in r.reply_text, r.reply_text)
    r = turn("nahi, hotel badalna hai")
    check("voice hi: a change at the review goes back to that part only", r.reply_text.startswith("Hotel kaisa chahiye"))
    r = turn("3 star"); r = turn("ek kamra"); r = turn("haan")
    check("voice hi: then the review again", "Sahi hai?" in r.reply_text and "Rooms" not in r.reply_text and "Kamre: 1" in r.reply_text, r.reply_text)
    r = turn("haan")
    check("voice hi: finish -> 'Abhi ye test hai. Kuch bheja nahi gaya.' and the state is deleted",
          r.reply_text == "Abhi ye test hai. Kuch bheja nahi gaya." and not redis_conn.exists(key(uid_a, T2)))
    check("voice hi: the model was called once only (for the one-letter name code couldn't accept)",
          FakeTools.calls == [["booking_answer"]], FakeTools.calls)
    mem = " ".join(m["content"] for m in agent.load_memory(redis_conn, uid_a, CV))
    check("voice: booking turns are not kept in the voice memory", "Priya" not in mem and "9123" not in mem and "Aryan" not in mem)

    # Devanagari, train, 1 adult
    CV = f"conv_bk_{uuid.uuid4().hex[:6]}"
    seq = [("मुझे ट्रेन बुक करनी है", "Train mein kaunsi class"), ("थर्ड एसी", "Train kis time"), ("शाम", "Tatkal chalega?"),
           ("नहीं", "Pehle yatri"), ("नहीं", "Yatri 1 ka naam?"), ("राहुल शर्मा", "राहुल शर्मा ki umar?"),
           ("चौंतीस साल", "Ek mobile number"), ("नौ आठ सात छह पांच चार तीन दो एक शून्य", "Number: 9 8 7 6 5, 4 3 2 1 0"),
           ("हां", "Train: Class: 3AC"), ("हां", "Abhi ye test hai")]
    bad = [(t, r.reply_text) for t, want in seq for r in [say(t, CV, trip=TRIP1)] if not r.reply_text.startswith(want)]
    check("voice Devanagari: train flow end to end", not bad and not redis_conn.exists(key(uid_a, T1)), bad)

    # English, flight + train, 1 adult
    CV = f"conv_bk_{uuid.uuid4().hex[:6]}"
    seq = [("I want to book a flight and a train", "What time for the flight"), ("morning", "Any particular airline"),
           ("IndiGo", "Which train class"), ("sleeper", "What time for the train"), ("you decide", "Is Tatkal okay"),
           ("yes", "Is the first traveller Asha Ak"), ("yes", "How old is Asha Ak"), ("thirty four", "Please give one mobile"),
           ("nine eight seven six five four three two one zero", "Number: 9 8 7 6 5, 4 3 2 1 0. Is that right?"),
           ("yes", "Flight:"), ("yes", "This is a test for now. Nothing was sent.")]
    bad = [(t, r.reply_text) for t, want in seq for r in [say(t, CV, trip=TRIP1, stt="en")] if not r.reply_text.startswith(want)]
    check("voice English: flight + train end to end", not bad and not redis_conn.exists(key(uid_a, T1)), bad)

    # "abhi nahi" at every step by voice
    answers = ["teeno", "subah", "jo sasta mile", "3AC", "raat", "haan", "budget", "do", "nahi", "haan", "34",
               "9876543210", "haan"]
    seen = []
    for stop in range(len(answers) + 1):
        CV = f"conv_bk_{uuid.uuid4().hex[:6]}"
        say("book karwana hai", CV, trip=TRIP1)
        for a in answers[:stop]:
            say(a, CV, trip=TRIP1)
        seen.append(BF.current_question(BF.load(redis_conn, uid_a, T1)))
        r = say(["abhi nahi", "chhodo", "अभी नहीं", "cancel"][stop % 4], CV, trip=TRIP1)
        if r.reply_text not in ("Theek hai.", "Okay.") or redis_conn.exists(key(uid_a, T1)):
            break
    check("voice: 'abhi nahi' / chhodo / अभी नहीं / cancel at every step discards the state",
          len(seen) == len(answers) + 1 and seen[-1] == "review", seen)

    # resume, other conversation, window
    CV = f"conv_bk_{uuid.uuid4().hex[:6]}"
    say("hotel book karo", CV, trip=TRIP1)
    say("budget", CV, trip=TRIP1)
    FakeTools.calls = []
    r = say("Hawa Mahal kahan hai?", "conv_other", trip=TRIP1)
    check("voice: another conversation's unrelated question goes to the model (not captured)", r.action != "booking" and FakeTools.calls)
    r = say("booking jaari rakho", "conv_other", trip=TRIP1)
    check("voice: asking to book again resumes where it stopped", r.reply_text.startswith("Booking wahin se: Kitne kamre"), r.reply_text)
    st = BF.load(redis_conn, uid_a, T1)
    st.voice_asked_at -= V.ANSWER_WINDOW_S + 5
    BF.save(redis_conn, uid_a, st)
    FakeTools.calls = []
    r = say("do", "conv_other", trip=TRIP1)
    check("voice: after the answer window a turn is not captured", r.action != "booking")
    redis_conn.delete(key(uid_a, T1))
    r = say("book karwana hai", "conv_other", trip=TRIP1)
    check("voice: after TTL expiry it starts fresh", r.reply_text.startswith("Train, flight ya hotel"))
    r = say("aap decide karo", "conv_other", trip=TRIP1)
    check("voice: services can't be 'aap decide karo' -> asked again", r.reply_text.startswith("Samajh nahi aaya. Train, flight ya hotel"))

    # model only extracts, its output checked by code
    say("hotel", "conv_other", trip=TRIP1)
    for a in ("budget", "1", "nahi", "nahi"):
        say(a, "conv_other", trip=TRIP1)
    FakeTools.queue = [("booking_answer", {"name": "Rahul", "age": None, "phone_digits": None})]
    FakeTools.calls = []
    r = say("Rahul chautees saal", "conv_other", trip=TRIP1)
    check("voice: a sentence code can't read -> the model extracts (name said by the user accepted)",
          FakeTools.calls == [["booking_answer"]] and r.reply_text == "Rahul ki umar?", r.reply_text)
    FakeTools.queue = [("booking_answer", {"name": None, "age": 34, "phone_digits": None})]
    r = say("chautees", "conv_other", trip=TRIP1)
    check("voice: an age word code doesn't know -> the model's number, range-checked", r.reply_text.startswith("Ek mobile number"))
    st = BF.load(redis_conn, uid_a, T1)
    st.travellers[0]["name"] = None
    st.travellers[0]["age"] = None
    BF.save(redis_conn, uid_a, st)
    FakeTools.queue = [("booking_answer", {"name": "Rohit Verma", "age": None, "phone_digits": None})]
    r = say("Rahul chautees saal", "conv_other", trip=TRIP1)
    check("voice: a name the user did NOT say is never accepted from the model", BF.load(redis_conn, uid_a, T1).travellers[0]["name"] != "Rohit Verma")
    BF.cancel(redis_conn, uid_a, T1)

    # another user's voice can't touch A's flow
    wsd("booking:start", T1)
    r = say("book karwana hai", "conv_b", trip=agent.TripInfo(title="Goa", start_date=d(5), end_date=d(7), id=T1), user=uid_b)
    check("another user: voice with A's trip id never reads A's flow", not redis_conn.exists(key(uid_b, T1))
          and wsd("booking:get", T1)["question"] == "services")
    BF.cancel(redis_conn, uid_a, T1)

    # a waiting Confirm card no longer takes the booking's "haan"
    CV = f"conv_bk_{uuid.uuid4().hex[:6]}"
    P.save(redis_conn, uid_a, CV, "create_trip", "Goa trip")
    say("train book karo", CV, trip=TRIP1)
    check("voice: starting a booking drops a waiting Confirm card", P.get(redis_conn, uid_a, CV) is None)
    BF.cancel(redis_conn, uid_a, T1)

logs = log_buf.getvalue()
check("logs: [BOOKING FLOW] lines with flags", "[BOOKING FLOW] event=answer" in logs and "skipped=true" in logs)
leaks = [w for w in ("Rahul", "Priya", "Aryan", "Asha", "राहुल", "98765", "9876543210", "91234", "chautees", "Sharma") if w in logs]
check("logs: no names, numbers or words", not leaks, leaks)
check("database: unchanged by the whole booking flow", db_snapshot() == BEFORE)
check("redis: no booking keys left for these users", not list(redis_conn.scan_iter(f"booking:flow:{uid_a}:*"))
      and not list(redis_conn.scan_iter(f"booking:flow:{uid_b}:*")))

client.__exit__(None, None, None)
print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
