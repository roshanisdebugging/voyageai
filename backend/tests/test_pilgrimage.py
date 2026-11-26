"""
Checked plans (backend/pilgrimage/*.json): loader, matching, the days rule, trip creation, the worker build
(Google and the AI simulated) and the voice offer ("... ka ek checked plan hai. Isse shuru karein?").
SQLite + local Redis, no real Google or AI calls. Run from backend/: python -m tests.test_pilgrimage
"""
import json
import os
import shutil
import sys
import tempfile
import uuid
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import dotenv

dotenv.load_dotenv = lambda *a, **k: None
os.environ["DATABASE_URL"] = "postgresql://x:y@127.0.0.1:1/none"
os.environ["AI_PROVIDER"] = "mock"

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)
SCRATCH = tempfile.mkdtemp(prefix="voyageai_test_")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

import database  # noqa: E402

database.engine = create_engine(f"sqlite:///{os.path.join(SCRATCH, 'app.db')}", connect_args={"check_same_thread": False})
database.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=database.engine)
import models_db, models_trip, models_itinerary, models_package, models_place  # noqa: E401,E402,F401
database.Base.metadata.create_all(bind=database.engine)

import pilgrimage  # noqa: E402
import plan_card_itinerary as PCI  # noqa: E402
import trip_lifecycle  # noqa: E402
import itinerary_service  # noqa: E402
from models import AuthUser  # noqa: E402
from models_itinerary import ItineraryActivityModel, ItineraryDayModel, ItineraryModel  # noqa: E402
from models_trip import TripModel  # noqa: E402
from redis_client import redis_conn  # noqa: E402

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail != "" and not cond else ""), flush=True)


# ---------------- 1. loader

real = pilgrimage.load_cards()
check("real folder: every card loads, none rejected", len(real.cards) >= 2 and not real.rejected, (list(real.cards), real.rejected))
check("real folder: Varanasi and Ayodhya present", {"varanasi-kashi-yatra", "ayodhya-ram-nagari"} <= set(real.cards))

tmp = Path(SCRATCH) / "cards"
tmp.mkdir()
shutil.copy(pilgrimage.CARDS_DIR / "varanasi-kashi-yatra.json", tmp / "good.json")
(tmp / "broken.json").write_text("{ not json", encoding="utf-8")
bad = json.loads((pilgrimage.CARDS_DIR / "ayodhya-ram-nagari.json").read_text(encoding="utf-8"))
bad["days"][0]["stops"][0]["priority"] = "maybe"
(tmp / "bad-schema.json").write_text(json.dumps(bad), encoding="utf-8")
gap = json.loads((pilgrimage.CARDS_DIR / "ayodhya-ram-nagari.json").read_text(encoding="utf-8"))
gap["id"] = "gap-card"
gap["days"][1]["day_number"] = 5
(tmp / "gap.json").write_text(json.dumps(gap), encoding="utf-8")
mixed = pilgrimage.load_cards(tmp)
check("broken files rejected, good one still loads", list(mixed.cards) == ["varanasi-kashi-yatra"]
      and set(mixed.rejected) == {"broken.json", "bad-schema.json", "gap.json"}, (list(mixed.cards), mixed.rejected))
check("rejection reasons name the problem, not the content", "not valid JSON" in mixed.rejected["broken.json"]
      and "days" in mixed.rejected["bad-schema.json"], mixed.rejected)
empty = Path(SCRATCH) / "empty"
empty.mkdir()
check("empty folder: no cards, no crash", pilgrimage.load_cards(empty).cards == {})
check("missing folder: no cards, no crash", pilgrimage.load_cards(Path(SCRATCH) / "nope").cards == {})
pilgrimage.init_cards()

# ---------------- 2. matching

for said in ["वाराणसी", "Varanasi", "Banaras", "Kashi", "  VARANASI ", "बनारस", "काशी"]:
    c = pilgrimage.match_card(said)
    check(f"match {said.strip()!r} -> Varanasi card", c is not None and c.id == "varanasi-kashi-yatra", c and c.id)
c = pilgrimage.match_card("अयोध्या")
check("match 'अयोध्या' -> Ayodhya card", c is not None and c.id == "ayodhya-ram-nagari")
check("'Goa' matches nothing", pilgrimage.match_card("Goa") is None)
check("'Jaipur' matches nothing", pilgrimage.match_card("Jaipur") is None)
check("empty text matches nothing", pilgrimage.match_card("") is None and pilgrimage.match_card(None) is None)

# ---------------- 3. days rule

V, A = pilgrimage.get_card("varanasi-kashi-yatra"), pilgrimage.get_card("ayodhya-ram-nagari")
p = pilgrimage.plan_days(V, 3)
check("Varanasi 3 days: the card exactly, no extra", [d.card_day for d in p.card_days] == [1, 2, 3] and p.extra_days == 0)
p = pilgrimage.plan_days(V, 4)
check("Varanasi 4 days: 3 card days + 1 extra", [d.card_day for d in p.card_days] == [1, 2, 3] and p.extra_days == 1)
p = pilgrimage.plan_days(V, 2)
names = [s.name for d in p.card_days for s in d.stops]
check("Varanasi 2 days: must stops kept, optional Sarnath dropped", [d.card_day for d in p.card_days] == [1, 2]
      and not any("Sarnath" in n for n in names) and p.extra_days == 0, names)
p = pilgrimage.plan_days(V, 1)
check("Varanasi 1 day: whole days dropped from the end", [d.card_day for d in p.card_days] == [1])
p = pilgrimage.plan_days(V, None)
check("no days: default_days (3)", len(p.card_days) == V.default_days == 3 and p.extra_days == 0)
p = pilgrimage.plan_days(A, 3)
check("Ayodhya 3 days: 2 card days + 1 extra", [d.card_day for d in p.card_days] == [1, 2] and p.extra_days == 1)
check("card content untouched by the rule", len(V.days[2].stops) == 1 and V.days[2].stops[0].priority == "optional")

# ---------------- simulated Google and AI

CITY = {"Varanasi": (25.31, 83.01), "Ayodhya": (26.79, 82.20)}


def fake_search(fail=(), unavailable=False, other_city=()):
    calls = []

    def search(query):
        calls.append(query)
        if unavailable:
            return SimpleNamespace(results=[], unavailable=True, ambiguous=False)
        name, city = [x.strip() for x in query.rsplit(",", 1)]
        if any(f in name for f in fail):
            return SimpleNamespace(results=[], unavailable=False, ambiguous=False)
        where = "Patna, Bihar" if any(o in name for o in other_city) else f"{city}, Uttar Pradesh"
        lat, lng = CITY.get(city, (25.0, 83.0))
        return SimpleNamespace(unavailable=False, ambiguous=False, results=[{
            "place_id": "ChIJtest" + uuid.uuid5(uuid.NAMESPACE_DNS, name).hex[:12], "name": name,
            "displayName": f"{name}, {where}, India", "latitude": lat + 0.001 * len(calls), "longitude": lng}])
    search.calls = calls
    return search


def no_ai(prompt):
    raise AssertionError("the AI must not be called")


START = (date.today() + timedelta(days=10)).isoformat()


def make_trip(card, days, dest_name):
    meta = trip_lifecycle._plan_card_meta(card.id, {"name": dest_name, "city": dest_name})
    t = TripModel(id=f"trip_t{uuid.uuid4().hex[:8]}", user_id="usr_pilg", title=f"{dest_name} Tour Package",
                  status="PLANNING", itinerary_status="GENERATING", start_date=START,
                  end_date=(date.fromisoformat(START) + timedelta(days=days - 1)).isoformat(), total_days=days,
                  destination_json=json.dumps({"name": dest_name, "city": dest_name, "region": "Uttar Pradesh"}),
                  travelers_json="[]", preferences_snapshot_json=json.dumps({"travelStyles": [], "planCard": meta}),
                  created_at="t", updated_at="t")
    return t


def saved(db, trip_id):
    itin = db.query(ItineraryModel).filter(ItineraryModel.trip_id == trip_id).first()
    days = db.query(ItineraryDayModel).filter(ItineraryDayModel.itinerary_id == itin.id).order_by(ItineraryDayModel.day_number).all()
    out = []
    for d in days:
        acts = db.query(ItineraryActivityModel).filter(ItineraryActivityModel.day_id == d.id).all()
        out.append((d, acts))
    return itin, out


def run_worker(trip, search, ai):
    """The real worker entry point, with Google and the AI simulated and the itinerary cache forbidden."""
    trip_id = trip.id
    with database.SessionLocal() as db:
        db.add(trip)
        db.commit()
    with mock.patch.object(PCI, "_default_search", search), mock.patch("ai_provider.complete_json", ai), \
            mock.patch.object(itinerary_service, "get_cached_itinerary", side_effect=AssertionError("cache used")), \
            mock.patch.object(itinerary_service, "set_cached_itinerary", side_effect=AssertionError("cache used")):
        status = itinerary_service.process_async_itinerary_generation(trip_id, database.SessionLocal)
    db = database.SessionLocal()
    t = db.query(TripModel).filter(TripModel.id == trip_id).first()
    return status, db, t


# ---------------- 4. worker: Varanasi 3 days (card only, no AI call)

s = fake_search()
status, db, t = run_worker(make_trip(V, 3, "Varanasi"), s, no_ai)
itin, days = saved(db, t.id)
meta = t.preferences_snapshot["planCard"]
check("Varanasi 3: READY, 3 days", status == "READY" and t.itinerary_status == "READY" and len(days) == 3)
check("Varanasi 3: one item per stop, card order", [[a.title for a in acts] for _, acts in days]
      == [[st.name for st in d.stops] for d in V.days])
check("Varanasi 3: every day from the card", [d["source"] for d in meta["days"]] == ["card"] * 3)
a0 = days[1][1][0]
check("item keeps the stop note, time 'Flexible', cost unknown", a0.description == V.days[1].stops[0].note
      and a0.time_slot == "Flexible" and a0.estimated_cost_inr is None)
check("resolved stops have coordinates and a place_id", all(x.latitude is not None for _, acts in days for x in acts)
      and all(v["placeId"] and not v["unresolved"] for v in meta["stops"].values()))
check("Google looked up with name + city", s.calls[0] == "Dashashwamedh Ghat, Varanasi", s.calls[:1])
check("trip keeps card id, version, status, last_verified, booking notes", meta["id"] == V.id and meta["version"] == 1
      and meta["status"] == "draft_unverified" and meta["lastVerified"] is None
      and meta["bookingNotes"][0]["officialUrl"] == "https://www.shrikashivishwanath.org/")
check("itinerary provider is PLAN_CARD", itin.provider_name == "PLAN_CARD", itin.provider_name)
db.close()

# ---------------- 5. Varanasi 4 days: card + 1 AI day (repeat and unfound places dropped)

ai_calls = []


def ai_one_day(prompt):
    ai_calls.append(prompt)
    return json.dumps({"days": [{"dayNumber": 4, "title": "Old city and riverfront", "places": [
        {"name": "Dashashwamedh Ghat", "description": "repeat"},
        {"name": "Assi Ghat", "description": "A ghat at the south end of the riverfront."},
        {"name": "Totally Made Up Temple", "description": "invented"}]}]})


status, db, t = run_worker(make_trip(V, 4, "Varanasi"), fake_search(fail=("Made Up",)), ai_one_day)
itin, days = saved(db, t.id)
meta = t.preferences_snapshot["planCard"]
check("Varanasi 4: 4 days, 3 card + 1 AI", [d["source"] for d in meta["days"]] == ["card", "card", "card", "ai"])
check("AI asked once, with the card's places as do-not-repeat", len(ai_calls) == 1 and "Dashashwamedh Ghat" in ai_calls[0]
      and "Kashi Vishwanath Temple" in ai_calls[0])
check("AI day: repeat dropped, unfound place dropped, real one kept", [a.title for a in days[3][1]] == ["Assi Ghat"],
      [a.title for a in days[3][1]])
check("provider PLAN_CARD+AI", itin.provider_name == "PLAN_CARD+AI", itin.provider_name)
db.close()

# AI fails: the extra day stays free, never filled with guesses
status, db, t = run_worker(make_trip(V, 4, "Varanasi"), fake_search(), lambda p: (_ for _ in ()).throw(RuntimeError("down")))
itin, days = saved(db, t.id)
meta = t.preferences_snapshot["planCard"]
check("AI fails: day 4 is a free day with no items", status == "READY" and meta["days"][3]["source"] == "free"
      and days[3][0].title == "Free day" and days[3][1] == [])
db.close()
status, db, t = run_worker(make_trip(V, 4, "Varanasi"), fake_search(), lambda p: json.dumps({"days": []}))
itin, days = saved(db, t.id)
check("AI returns nothing: free day", days[3][1] == [] and t.preferences_snapshot["planCard"]["days"][3]["source"] == "free")
db.close()

# ---------------- 6. Varanasi 2 days, Ayodhya 3 days

status, db, t = run_worker(make_trip(V, 2, "Varanasi"), fake_search(), no_ai)
itin, days = saved(db, t.id)
check("Varanasi 2: 2 days, Sarnath dropped, no AI", len(days) == 2
      and not any("Sarnath" in a.title for _, acts in days for a in acts))
db.close()
ai_calls.clear()


def ai_ayodhya(prompt):
    ai_calls.append(prompt)
    return json.dumps({"days": [{"dayNumber": 3, "title": "Guptar Ghat", "places": [{"name": "Guptar Ghat", "description": "A ghat on the Saryu."}]}]})


status, db, t = run_worker(make_trip(A, 3, "Ayodhya"), fake_search(), ai_ayodhya)
itin, days = saved(db, t.id)
meta = t.preferences_snapshot["planCard"]
check("Ayodhya 3: 2 card days + 1 AI day", [d["source"] for d in meta["days"]] == ["card", "card", "ai"]
      and len(days[0][1]) == 3 and [a.title for a in days[2][1]] == ["Guptar Ghat"])
db.close()

# ---------------- 7. Google fails or is paused: trip still made, stops flagged

status, db, t = run_worker(make_trip(V, 3, "Varanasi"), fake_search(unavailable=True), no_ai)
itin, days = saved(db, t.id)
meta = t.preferences_snapshot["planCard"]
check("Google paused: READY, every stop kept without coordinates and flagged", status == "READY"
      and all(a.latitude is None and a.longitude is None for _, acts in days for a in acts)
      and all(v["unresolved"] and v["placeId"] is None for v in meta["stops"].values()) and len(meta["stops"]) == 3)
db.close()
status, db, t = run_worker(make_trip(V, 3, "Varanasi"), fake_search(fail=("Sarnath",), other_city=("Dashashwamedh",)), no_ai)
itin, days = saved(db, t.id)
meta = t.preferences_snapshot["planCard"]
flags = {a.title: meta["stops"][a.id]["unresolved"] for _, acts in days for a in acts}
check("not found / found in another city: unresolved, never guessed", flags["Dashashwamedh Ghat"] and flags[V.days[2].stops[0].name]
      and not flags["Kashi Vishwanath Temple"], flags)
db.close()
t2 = make_trip(V, 3, "Varanasi")
check("search crash: unresolved", PCI.resolve("X Y", "Varanasi", lambda q: (_ for _ in ()).throw(TimeoutError()))[0] is None)

# ---------------- 8. trip creation: card kept only when it fits; old flow untouched

user = AuthUser(id="usr_pilg", provider="EMAIL", providerUserId="p@example.com", email="p@example.com",
                createdAt="t", lastLoginAt="t")
VAR = {"id": "ChIJvar", "name": "Varanasi", "city": "Varanasi", "region": "Uttar Pradesh", "country": "India",
       "latitude": 25.31, "longitude": 83.01, "displayName": "Varanasi, Uttar Pradesh, India"}
GOA = {"id": "ChIJgoa", "name": "Goa", "city": "Goa", "region": "Goa", "country": "India", "latitude": 15.3,
       "longitude": 74.1, "displayName": "Goa, India"}
made = []


def create(dest, **extra):
    data = {"destination": dest, "startDate": START, "endDate": (date.fromisoformat(START) + timedelta(days=3)).isoformat(),
            "adultsCount": 2, "childrenCount": 0, "budgetAmount": 40000, "clientRequestId": f"req_{uuid.uuid4().hex[:8]}", **extra}
    # jobs recorded, not pushed: a running worker would take them from the shared Redis queue
    with database.SessionLocal() as db, mock.patch("media_service.media_service.resolve_cover_media", lambda d: {}), \
            mock.patch.object(trip_lifecycle, "enqueue_itinerary_generation", lambda tid: True), \
            mock.patch.object(PCI, "_default_search", fake_search()):
        out = trip_lifecycle.create_trip_for_user(db, user, None, None, data)
    made.append(out["id"])
    return out


out = create(VAR, planCardId="varanasi-kashi-yatra")
check("trip with planCardId for Varanasi: card kept", (out["preferencesSnapshot"].get("planCard") or {}).get("id") == "varanasi-kashi-yatra")
out = create(GOA, planCardId="varanasi-kashi-yatra")
check("destination changed to Goa on the review page: card dropped", "planCard" not in out["preferencesSnapshot"])
out = create(VAR)
check("no planCardId: no card (old flow)", "planCard" not in out["preferencesSnapshot"])
out = create(VAR, planCardId="no-such-card")
check("unknown card id: ignored", "planCard" not in out["preferencesSnapshot"])

# ---------------- 9. voice: the offer, haan / nahi / anything else, Goa

from voice import agent as AG, draft as D  # noqa: E402
import voice.tools.lookups as LK  # noqa: E402

UID = f"usr_pilgvoice{uuid.uuid4().hex[:6]}"


def place_for(name):
    n = pilgrimage.normalise(name)
    if n in {pilgrimage.normalise(x) for x in V.match_names}:
        return {"place_id": "ChIJvar", "name": "Varanasi", "displayName": "Varanasi, Uttar Pradesh, India", "latitude": 25.31, "longitude": 83.01}
    if n == "goa":
        return {"place_id": "ChIJgoa", "name": "Goa", "displayName": "Goa, India", "latitude": 15.3, "longitude": 74.1}
    return None


def llm_forbidden(*a, **k):
    raise AssertionError("LLM must not be called")


def conv():
    return f"conv_{uuid.uuid4().hex[:8]}"


def turn(text, cid, llm=llm_forbidden):
    with mock.patch("openai_client.chat_tools", llm):
        return AG.run_agent(text, "hi", user_id=UID, conversation_id=cid, screen="/home", trip=None, redis_conn=redis_conn)


with mock.patch.object(LK, "find_place", lambda q, search_fn=None: place_for(q)):
    c1 = conv()
    r = AG.update_draft(redis_conn, UID, c1, {"destination": "वाराणसी", "days": 4}, "hi")
    d = D.load(redis_conn, UID, c1)
    check("वाराणसी + 4 days: the card is offered once", r.step == "plan_offer"
          and "Kashi Yatra ka ek checked plan hai. Isse shuru karein?" in r.reply_text and d.awaiting == "card", r.reply_text)
    r = turn("हाँ।", c1)
    d = D.load(redis_conn, UID, c1)
    check("'हाँ' accepts (no LLM call), days kept at 4", d.plan_card_id == "varanasi-kashi-yatra" and d.days == 4
          and d.awaiting is None and r.reply_text.startswith(AG.PLAN_ACCEPTED["hi"]), (d.plan_card_id, d.days, r.reply_text))
    check("after yes the normal next question follows", "Kab se jaana hai?" in r.reply_text, r.reply_text)
    r = AG.update_draft(redis_conn, UID, c1, {"destination": "Varanasi", "start_date": START}, "hi")
    d = D.load(redis_conn, UID, c1)
    check("same destination said again: not offered twice, card kept", r.step != "plan_offer"
          and d.plan_card_id == "varanasi-kashi-yatra", r.step)
    check("prefill carries planCardId", D.prefill(d).get("planCardId") == "varanasi-kashi-yatra")

    c2 = conv()
    AG.update_draft(redis_conn, UID, c2, {"destination": "Kashi"}, "hi")
    r = turn("haan", c2)
    d = D.load(redis_conn, UID, c2)
    check("Kashi, no days, 'haan': default_days (3)", d.plan_card_id == V.id and d.days == V.default_days, d.days)

    c3 = conv()
    AG.update_draft(redis_conn, UID, c3, {"destination": "Banaras", "days": 4}, "hi")
    r = turn("nahi", c3)
    d = D.load(redis_conn, UID, c3)
    check("'nahi' declines: no card, normal next question, no LLM", d.plan_card_id is None and d.plan_offer == "declined"
          and "Kab se jaana hai?" in r.reply_text, r.reply_text)
    check("declined: prefill has no planCardId", "planCardId" not in D.prefill(d))

    c4 = conv()
    AG.update_draft(redis_conn, UID, c4, {"destination": "Varanasi", "days": 4}, "hi")
    llm_seen = []

    def fake_llm(messages, *a, **k):
        llm_seen.append(1)
        return {"tool_calls": [], "content": "Theek hai."}
    r = turn("kal subah ki train hai", c4, fake_llm)
    d = D.load(redis_conn, UID, c4)
    check("anything else: declined and handled as a normal turn", d.plan_card_id is None and d.plan_offer == "declined"
          and d.awaiting is None and llm_seen == [1])

    c5 = conv()
    r = AG.update_draft(redis_conn, UID, c5, {"destination": "Goa", "days": 4}, "hi")
    d = D.load(redis_conn, UID, c5)
    check("Goa: no offer, old flow (asks the start date)", r.step == "ask" and d.plan_offer is None
          and "checked plan" not in r.reply_text and "Kab se jaana hai?" in r.reply_text, r.reply_text)
    check("Goa prefill unchanged (no planCardId)", "planCardId" not in D.prefill(d))

    c6 = conv()
    AG.update_draft(redis_conn, UID, c6, {"destination": "Varanasi", "days": 3}, "hi")
    r = turn("cancel karo", c6)
    check("'cancel karo' while offered: cancels the trip draft as before", r.action == "trip_cancel"
          and D.load(redis_conn, UID, c6) is None, r.action)

    for cid in (c1, c2, c3, c4, c5, c6):
        AG.clear_memory(redis_conn, UID, cid)
        D.delete(redis_conn, UID, cid)

for key in redis_conn.scan_iter("rl:*"):
    redis_conn.delete(key)
database.engine.dispose()
shutil.rmtree(SCRATCH, ignore_errors=True)
print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
