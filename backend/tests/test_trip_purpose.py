"""
Trip purpose and base area, ask and save (feat/trip-purpose commit 2). Planning does not change yet.

Checks: the word lists map what was said to a type by CODE (Hindi, Hinglish, English); the free text rule; by voice the
full hackathon conversation (destination, dates, people, budget, starting city, then "hackathon ke liye", then
"Electronic City") fills purpose_type event and the base area, each asked once, and the read-back says
"hackathon ke liye, Electronic City ke paas" (the word said, not "event"); "bas ghoomna" -> leisure, no area question; "pata nahi" skips both (no model
call); a purpose said in the first sentence is not asked; an area not found near the destination is asked once more,
then dropped; trip creation keeps / checks the three fields and the response carries them (camelCase); old trips and
old clients without them behave as before.
App DB = SQLite, Redis = local, the model and place search simulated. No real AI or Google call.
Run from backend/: python -m tests.test_trip_purpose
"""
import contextlib
import io
import os
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
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

database.engine = create_engine(f"sqlite:///{os.path.join(SCRATCH, 'purpose.db')}", connect_args={"check_same_thread": False})
database.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=database.engine)
import models_db, models_trip, models_itinerary, models_package, models_place  # noqa: E401,E402,F401
database.Base.metadata.create_all(bind=database.engine)

import openai_client  # noqa: E402
import places  # noqa: E402
import trip_lifecycle  # noqa: E402
import trip_purpose as TP  # noqa: E402
from models_trip import TripModel  # noqa: E402
from redis_client import redis_conn  # noqa: E402
from trip_lifecycle import TripValidationError, today_ist  # noqa: E402
from voice import agent, draft as D, pending as P  # noqa: E402

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if (detail != "" and not cond) else ""), flush=True)


TODAY = today_ist()
day = lambda n: TODAY + timedelta(days=n)  # noqa: E731
iso = lambda n: day(n).isoformat()  # noqa: E731
say = lambda n: f"{day(n).day} {D.MONTHS[day(n).month - 1]}"  # noqa: E731
USER = f"usr_pur_{uuid.uuid4().hex[:6]}"
CONVS = []


def pl(pid, name, lat, lng, city):
    return [{"id": pid, "place_id": pid, "name": name, "latitude": lat, "longitude": lng, "city": city}]


BLR = pl("ChIJblr", "Bengaluru", 12.97, 77.59, "Bengaluru, Karnataka, India")
EC = pl("ChIJec", "Electronic City", 12.845, 77.66, "Bengaluru, Karnataka, India")
PLACES = {"bengaluru": BLR, "bangalore": BLR, "बेंगलुरु": BLR,
          "kolkata": pl("ChIJkol", "Kolkata", 22.57, 88.36, "Kolkata, West Bengal, India"),
          "goa": pl("ChIJgoa", "Goa", 15.29, 74.12, "Goa, India"),
          "electronic city, bengaluru": EC, "इलेक्ट्रॉनिक सिटी, bengaluru": EC,
          # speech-to-text heard a different place: Google's top result is far from Bengaluru (Delhi)
          "electric city, bengaluru": pl("ChIJfar", "Electric City Mall", 28.61, 77.21, "New Delhi, Delhi, India")}
GOOGLE = []


def fake_search(q):
    GOOGLE.append(q)
    return PLACES.get(q.strip().lower(), [])


class FakeTools:
    """The model: returns the update_trip_draft call queued for this turn; counts calls."""
    queue, calls = [], 0

    def __call__(self, messages, tools, **kw):
        FakeTools.calls += 1
        if not FakeTools.queue:
            return {"content": "Abhi samajh nahi paaya, phir se boliye.", "tool_calls": []}
        kind, payload = FakeTools.queue.pop(0)
        if kind == "text":
            return {"content": payload, "tool_calls": []}
        return {"content": None, "tool_calls": [{"name": "update_trip_draft", "arguments": payload}]}


def new_conv():
    c = f"conv_pur_{uuid.uuid4().hex[:6]}"
    CONVS.append(c)
    return c


def ra(text, conv, args=None, lang="hi"):
    FakeTools.queue = [("tool", args)] if args is not None else []
    return agent.run_agent(text, lang, user_id=USER, conversation_id=conv, screen="/home", trip=None, redis_conn=redis_conn)


def no_llm(fn):
    before = FakeTools.calls
    r = fn()
    return r, FakeTools.calls == before


def dr(conv):
    return D.load(redis_conn, USER, conv)


Q_PURPOSE = D.QUESTIONS["purpose"]
Q_AREA = D.QUESTIONS["base_area"]

# ---------------------------------------------------------------- 1. code maps the words to a type
print("\n== 1. purpose words -> type (code, not the model)")
for said, want in [
    ("ghoomna hai", "leisure"), ("bas ghoomna", "leisure"), ("holiday", "leisure"), ("family trip hai", "leisure"),
    ("घूमने जा रहे हैं", "leisure"), ("sightseeing", "leisure"), ("vacation", "leisure"),
    ("kaam se", "business"), ("office ka kaam hai", "business"), ("client meeting", "business"), ("मीटिंग है", "business"),
    ("business trip", "business"), ("work", "business"),
    ("hackathon ke liye", "event"), ("हैकाथॉन के लिए", "event"), ("conference", "event"), ("shaadi hai", "event"),
    ("wedding", "event"), ("interview dene", "event"), ("exam hai", "event"), ("workshop", "event"),
    ("teerth yatra", "pilgrimage"), ("darshan karne", "pilgrimage"), ("puja ke liye", "pilgrimage"),
    ("दर्शन के लिए", "pilgrimage"),
    ("dost se milne", "other"), ("college admission ke liye", "other"),
]:
    ptype, ptext, skipped = TP.classify_purpose(said)
    check(f"'{said}' -> {want}", ptype == want and not skipped, (ptype, ptext, skipped))
for said in ("pata nahi", "kuch nahi", "पता नहीं", "कुछ नहीं", "skip", "I don't know"):
    check(f"'{said}' -> skipped", TP.classify_purpose(said) == (None, None, True), TP.classify_purpose(said))
check("other keeps the user's words", TP.classify_purpose("dost se milne")[1] == "dost se milne")
check("business / event keep the words, leisure / pilgrimage don't",
      TP.classify_purpose("hackathon ke liye")[1] == "hackathon" and TP.classify_purpose("kaam se")[1] == "kaam"
      and TP.classify_purpose("bas ghoomna")[1] is None and TP.classify_purpose("darshan karne")[1] is None)
check("an empty answer is not a purpose", TP.classify_purpose("") == (None, None, False))
for said, want in [("हैकथन", ("event", "hackathon")), ("हैकथन के लिए जा रहा हूँ", ("event", "hackathon")),
                   ("business meeting hai", ("business", "business meeting")), ("client meeting", ("business", "client meeting")),
                   ("event hai", ("event", "event")), ("kaam se", ("business", "kaam")), ("office ka kaam", ("business", "office ka kaam")),
                   ("शादी में जा रहे हैं", ("event", "shaadi")), ("conference ke liye", ("event", "conference"))]:
    got = TP.classify_purpose(said)[:2]
    check(f"spoken word kept: {said!r} -> {want}", got == want, got)
for ptype, text, hi, en in [("event", "hackathon", "hackathon ke liye", "for your hackathon"),
                            ("business", "business meeting", "business meeting ke liye", "for your business meeting"),
                            ("event", "event", "event ke liye", "for your event"),
                            ("event", None, "event ke liye", "for an event")]:
    dd = D.TripDraftState(purpose_type=ptype, purpose_text=text)
    check(f"read-back words for {ptype}/{text}: {hi!r} / {en!r}", D.purpose_words(dd, "hi") == f", {hi}"
          and D.purpose_words(dd, "en") == f", {en}", (D.purpose_words(dd, "hi"), D.purpose_words(dd, "en")))

print("\n== 2. the free text rule (one line, 120 characters, letters / digits / common punctuation)")
for raw, want in [("hackathon ke liye", "hackathon ke liye"), ("  Team   offsite, day 2 ", "Team offsite, day 2"),
                  ("line\nbreak", "line break"), ("x" * 121, None), ("x" * 120, "x" * 120), ('quote " inside', None),
                  ("<script>", None), ("{json}", None), ("12345", None), ("", None), (None, None), (42, None),
                  ("हैकाथॉन के लिए", "हैकाथॉन के लिए")]:
    check(f"clean_purpose_text({str(raw)[:20]!r}) -> {str(want)[:20]!r}", TP.clean_purpose_text(raw) == want,
          TP.clean_purpose_text(raw))
check("BASE_AREA_RADIUS_KM is 15, in trip_purpose only", TP.BASE_AREA_RADIUS_KM == 15.0)
check("only business / event / other are focused", TP.FOCUSED_PURPOSES == {"business", "event", "other"})

with mock.patch.object(openai_client, "chat_tools", FakeTools()), mock.patch.object(places, "search_places", fake_search):
    # ------------------------------------------------------------ 3. the hackathon conversation by voice
    print("\n== 3. the full hackathon conversation by voice")
    c = new_conv()
    r = ra("Bengaluru jaana hai", c, {"destination": "Bengaluru"})
    r = ra(f"{day(20).day} se {day(22).day} tak", c, {"start_date": iso(20), "end_date": iso(22)})
    r = ra("ek banda", c, {"adults": 1, "children": 0})
    check("budget + origin asked together", r.reply_text == "Kul budget kitna hai? Kahan se jaana hai?", r.reply_text)
    r = ra("40 hazaar, Kolkata se", c, {"budget_inr": 40000, "origin_city": "Kolkata"})
    check("then the purpose question, alone, once", r.reply_text == Q_PURPOSE["hi"] and dr(c).purpose_asked == 1
          and dr(c).purpose_pending and r.step == "ask", r.reply_text)
    r = ra("hackathon ke liye", c, {"purpose": "hackathon ke liye"})
    check("'hackathon ke liye' -> event (code), the words kept", dr(c).purpose_type == "event"
          and dr(c).purpose_text == "hackathon")
    check("event -> the area question, once", r.reply_text == Q_AREA["hi"] and dr(c).area_asked == 1 and dr(c).area_pending,
          r.reply_text)
    GOOGLE.clear()
    r = ra("Electronic City mein", c, {"base_area": "Electronic City"})
    area = dr(c).base_area or {}
    check("'Electronic City' -> base area looked up next to the destination", GOOGLE == ["Electronic City, Bengaluru"], GOOGLE)
    check("base area stored like the origin (id, name, city, lat, lng)", area.get("id") == "ChIJec"
          and area.get("name") == "Electronic City" and area.get("city") == "Bengaluru"
          and area.get("latitude") == 12.845 and area.get("longitude") == 77.66, area)
    check("read-back adds the purpose and the area",
          r.reply_text == f"Kolkata se Bengaluru, {say(20)} se {say(22)}, do raat, ek bada, hackathon ke liye, Electronic City ke paas. Sahi hai?",
          r.reply_text)
    r, quiet = no_llm(lambda: ra("haan", c))
    pre = next((a["prefill"] for a in r.ui_actions if a.get("type") == "open_review"), {})
    check("'haan' -> ready, prefill carries purposeType / purposeText / baseArea", quiet and r.step == "ready"
          and pre.get("purposeType") == "event" and pre.get("purposeText") == "hackathon"
          and (pre.get("baseArea") or {}).get("name") == "Electronic City", pre)
    check("the confirm card names the purpose", "hackathon ke liye, Electronic City ke paas" in (r.pending_confirmation or {}).get("summary", ""),
          (r.pending_confirmation or {}).get("summary"))
    check("each asked once only", dr(c).purpose_asked == 1 and dr(c).area_asked == 1)

    print("\n== 4. English")
    c = new_conv()
    ra("I want to go to Bengaluru", c, {"destination": "Bengaluru", "start_date": iso(20), "end_date": iso(22), "adults": 1,
                                        "children": 0, "budget_inr": 40000}, "en")
    r = ra("I don't know", c, lang="en")
    check("[en] origin skipped -> the purpose question", r.reply_text.endswith(Q_PURPOSE["en"]), r.reply_text)
    r = ra("for work", c, {"purpose": "for work"}, "en")
    check("[en] 'for work' -> business -> the area question", dr(c).purpose_type == "business" and r.reply_text == Q_AREA["en"],
          r.reply_text)
    r = ra("Electronic City", c, {"base_area": "Electronic City"}, "en")
    check("[en] read-back: for your work, near Electronic City",
          r.reply_text == f"{say(20)} to {say(22)}, 2 nights, for your work, near Electronic City. Is that right?", r.reply_text)

    print("\n== 5. 'bas ghoomna' -> leisure, no area question; planning as today")
    c = new_conv()
    ra("Goa jaana hai", c, {"destination": "Goa", "start_date": iso(20), "end_date": iso(22), "adults": 2, "children": 0,
                           "budget_inr": 40000, "origin_city": "Kolkata"})
    r = ra("bas ghoomna", c, {"purpose": "bas ghoomna"})
    check("leisure, no text, no area question, read-back next", dr(c).purpose_type == "leisure" and dr(c).purpose_text is None
          and dr(c).area_asked == 0 and r.step == "confirm_date", r.reply_text)
    check("read-back says 'ghoomne ke liye'", r.reply_text.endswith("do bade log, ghoomne ke liye. Sahi hai?"), r.reply_text)
    r, _ = no_llm(lambda: ra("haan", c))
    pre = next((a["prefill"] for a in r.ui_actions if a.get("type") == "open_review"), {})
    check("leisure prefill: no text, no area", pre.get("purposeType") == "leisure" and pre.get("purposeText") is None
          and pre.get("baseArea") is None, pre)

    print("\n== 6. 'pata nahi' skips both (no model call), read-back as today")
    for skip in ("pata nahi", "कुछ नहीं", "kuch nahi"):
        c = new_conv()
        ra("Goa jaana hai", c, {"destination": "Goa", "start_date": iso(20), "end_date": iso(22), "adults": 2, "children": 0,
                               "budget_inr": 40000, "origin_city": "Kolkata"})
        r, quiet = no_llm(lambda: ra(skip, c))
        check(f"'{skip}' -> no model call, purpose skipped, no area question", quiet and dr(c).purpose_skipped
              and dr(c).purpose_type is None and dr(c).area_asked == 0, r.reply_text)
        check(f"'{skip}' -> read-back exactly as today (no purpose words)",
              r.reply_text == f"Kolkata se Goa, {say(20)} se {say(22)}, do raat, do bade log. Sahi hai?", r.reply_text)
        r, _ = no_llm(lambda: ra("haan", c))
        pre = next((a["prefill"] for a in r.ui_actions if a.get("type") == "open_review"), {})
        check(f"'{skip}' -> prefill has no purpose keys (as before)", "purposeType" not in pre and r.step == "ready", pre)
    c = new_conv()   # a business trip, then "pata nahi" to the area question
    ra("Goa jaana hai", c, {"destination": "Goa", "start_date": iso(20), "end_date": iso(22), "adults": 2, "children": 0,
                           "budget_inr": 40000, "origin_city": "Kolkata"})
    ra("client meeting hai", c, {"purpose": "client meeting hai"})
    r, quiet = no_llm(lambda: ra("pata nahi", c))
    check("area 'pata nahi' -> no model call, no area, read-back with the word said ('client meeting ke liye')", quiet and dr(c).area_skipped
          and dr(c).base_area is None and r.reply_text.endswith("do bade log, client meeting ke liye. Sahi hai?"), r.reply_text)
    c = new_conv()   # asked, answered with something else: never asked again
    ra("Goa jaana hai", c, {"destination": "Goa", "start_date": iso(20), "end_date": iso(22), "adults": 2, "children": 0,
                           "budget_inr": 40000, "origin_city": "Kolkata"})
    r = ra("budget 45 hazaar kar do", c, {"budget_inr": 45000})
    check("purpose asked, not given -> skipped, read-back next", dr(c).purpose_skipped and r.step == "confirm_date"
          and dr(c).purpose_asked == 1, r.reply_text)

    print("\n== 7. a purpose already said is not asked again")
    c = new_conv()
    r = ra("Kolkata se Bengaluru hackathon ke liye, Electronic City mein", c, {
        "destination": "Bengaluru", "origin_city": "Kolkata", "purpose": "hackathon ke liye", "base_area": "Electronic City",
        "start_date": iso(20), "end_date": iso(22), "adults": 1, "children": 0, "budget_inr": 40000})
    check("first sentence with purpose + area -> straight to the read-back", r.step == "confirm_date"
          and dr(c).purpose_asked == 0 and dr(c).area_asked == 0 and "hackathon ke liye, Electronic City ke paas" in r.reply_text,
          r.reply_text)
    c = new_conv()
    r = ra("Bengaluru jaana hai kaam se", c, {"destination": "Bengaluru", "purpose": "kaam se"})
    check("purpose in the first sentence -> kept, never in the questions", dr(c).purpose_type == "business"
          and "Kis kaam" not in r.reply_text, r.reply_text)

    print("\n== 8. the area: not found -> once more, then without it; far from the destination = not found")
    c = new_conv()
    ra("Bengaluru", c, {"destination": "Bengaluru", "start_date": iso(20), "end_date": iso(22), "adults": 1, "children": 0,
                        "budget_inr": 40000, "origin_city": "Kolkata"})
    ra("hackathon", c, {"purpose": "hackathon"})
    r = ra("Electric City mein", c, {"base_area": "Electric City"})
    check("a hit 1,700 km away -> not this trip's area, asked once more", r.step == "ask_area"
          and r.reply_text == D.AREA_RETRY["hi"].format(name="Electric City", city="Bengaluru") and dr(c).base_area is None
          and dr(c).area_asked == 2, r.reply_text)
    r = ra("Whitefieldd mein", c, {"base_area": "Whitefieldd"})
    check("second miss -> goes on without it (never a third question)", dr(c).area_skipped and dr(c).base_area is None
          and r.reply_text.startswith(D.AREA_GIVE_UP["hi"].format(name="Whitefieldd")) and r.step == "confirm_date", r.reply_text)
    c = new_conv()
    ra("Bengaluru", c, {"destination": "Bengaluru", "start_date": iso(20), "end_date": iso(22), "adults": 1, "children": 0,
                        "budget_inr": 40000, "origin_city": "Kolkata"})
    ra("hackathon", c, {"purpose": "hackathon"})
    GOOGLE.clear()
    r = ra("pata", c, {"base_area": "pata"})
    check("'pata' as an area -> not a place, no Google call", GOOGLE == [] and dr(c).base_area is None, GOOGLE)

    print("\n== 9. corrections at the read-back, like the origin")
    c = new_conv()
    ra("Kolkata se Bengaluru, hackathon hai Electronic City mein", c, {"destination": "Bengaluru", "origin_city": "Kolkata",
                "purpose": "hackathon", "base_area": "Electronic City",
                "start_date": iso(20), "end_date": iso(22), "adults": 1, "children": 0, "budget_inr": 40000})
    r = ra("nahi, ghoomne ja raha hoon", c, {"purpose": "ghoomne ja raha hoon"})
    check("purpose changed to leisure -> the area is dropped, read back again", dr(c).purpose_type == "leisure"
          and dr(c).base_area is None and r.step == "confirm_date" and "ghoomne ke liye" in r.reply_text
          and "Electronic City" not in r.reply_text, r.reply_text)

    print("\n== 10. the prompt / tool tell the model only to pass the words")
    props = agent.UPDATE_DRAFT_TOOL["function"]["parameters"]["properties"]
    check("tool: purpose and base_area arguments", "purpose" in props and "base_area" in props)
    check("prompt: our code decides the type", "our code decides the type" in agent.SYSTEM_PROMPT)

# ---------------------------------------------------------------- 11. trip creation (form and voice prefill)
print("\n== 11. trip creation: kept, checked, returned in camelCase; old clients as before")
USR = SimpleNamespace(id=f"usr_pur_db_{uuid.uuid4().hex[:6]}")
DEST = {"name": "Bengaluru", "city": "Bengaluru", "country": "India", "latitude": 12.97, "longitude": 77.59}
AREA = {"id": "ChIJec", "name": "Electronic City", "city": "Bengaluru", "region": "Karnataka", "country": "India",
        "latitude": 12.845, "longitude": 77.66}


def create(**extra):
    payload = {"destination": DEST, "startDate": iso(20), "endDate": iso(22), "adultsCount": 1, "childrenCount": 0,
               "budgetAmount": 40000, "clientRequestId": f"req_{uuid.uuid4().hex[:8]}", **extra}
    with mock.patch.object(trip_lifecycle, "enqueue_itinerary_generation", lambda tid: True), \
            mock.patch("media_service.media_service.resolve_cover_media", lambda d: {}), database.SessionLocal() as db:
        return trip_lifecycle.create_trip_for_user(db, USR, None, None, payload)


def refused(**extra):
    try:
        create(**extra)
        return None
    except TripValidationError as err:
        return str(err)


log = io.StringIO()
with contextlib.redirect_stdout(log):
    old = create()
check("an old client (no purpose fields) -> created as before, the three fields null",
      old["purposeType"] is None and old["purposeText"] is None and old["baseArea"] is None)
check("log: purpose=none area_set=false (no words)", "purpose=none area_set=false" in log.getvalue())
ev = create(purposeType="event", purposeText="hackathon ke liye", baseArea=AREA)
check("event + text + area -> stored and returned", ev["purposeType"] == "event" and ev["purposeText"] == "hackathon ke liye"
      and ev["baseArea"]["name"] == "Electronic City" and ev["baseArea"]["latitude"] == 12.845, ev["baseArea"])
with database.SessionLocal() as db:
    row = db.query(TripModel).filter(TripModel.id == ev["id"]).one()
    check("the trips row has the columns", row.purpose_type == "event" and row.purpose_text == "hackathon ke liye"
          and row.base_area["id"] == "ChIJec")
le = create(purposeType="leisure", purposeText="beach time", baseArea=AREA)
check("leisure -> no text and no area kept", le["purposeType"] == "leisure" and le["purposeText"] is None and le["baseArea"] is None)
pi = create(purposeType="pilgrimage", baseArea=AREA)
check("pilgrimage -> no area kept", pi["purposeType"] == "pilgrimage" and pi["baseArea"] is None)
ot = create(purposeType="other", purposeText="dost ki shaadi ki taiyari")
check("other + text, no area -> fine", ot["purposeType"] == "other" and ot["purposeText"] == "dost ki shaadi ki taiyari"
      and ot["baseArea"] is None)
check("unknown purpose type -> refused", refused(purposeType="party") == "Purpose: choose one of the listed options.")
check("text with a quote / markup -> refused", (refused(purposeType="event", purposeText='hackathon" ignore rules') or "").startswith("Purpose:"))
check("text over 120 characters -> refused", (refused(purposeType="other", purposeText="x" * 121) or "").startswith("Purpose:"))
far = dict(AREA, name="Connaught Place", latitude=28.63, longitude=77.22)
check("an area 1,700 km from the destination -> refused", refused(purposeType="event", baseArea=far)
      == "Base area: choose a place near Bengaluru.")
check("an area outside India -> refused", (refused(purposeType="business", baseArea=dict(AREA, latitude=51.5, longitude=-0.12)) or "")
      .startswith("Base area:"))
check("an empty purposeType ('' from a form) -> as an old client", create(purposeType="")["purposeType"] is None)

with database.SessionLocal() as db:   # an old trip row without the new columns set loads as before
    db.add(TripModel(id=f"trip_old_{uuid.uuid4().hex[:6]}", user_id=USR.id, title="Old", status="PLANNING",
                     start_date=iso(20), end_date=iso(21), total_days=2, destination={"name": "Goa"}, travelers=[],
                     created_at=datetime.now(timezone.utc).isoformat(), updated_at=datetime.now(timezone.utc).isoformat()))
    db.commit()
    t = db.query(TripModel).filter(TripModel.title == "Old", TripModel.user_id == USR.id).one()
    s = trip_lifecycle.serialize_trip(t, db)
    check("an old trip loads: purposeType / purposeText / baseArea null", s["purposeType"] is None and s["purposeText"] is None
          and s["baseArea"] is None and s["title"] == "Old")

# ---------------------------------------------------------------- clean up
for conv in CONVS:
    agent.clear_memory(redis_conn, USER, conv)
    D.delete(redis_conn, USER, conv)
    P.clear(redis_conn, USER, conv)
with database.SessionLocal() as db:
    db.query(TripModel).filter(TripModel.user_id == USR.id).delete()
    db.commit()

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
