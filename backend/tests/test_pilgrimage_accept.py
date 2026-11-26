"""
Regression: an accepted checked plan (pilgrimage card) must reach the trip.

Bug (26 Nov 2026): the user answered "Kashi Yatra ka ek checked plan hai. Isse shuru karein?" with "हाँ, शुरू करो."
(Whisper's text). yes_or_no() does not treat "शुरू" as a yes word, so the offer counted as declined, the card id
never reached the review-page prefill, and the trip got a normal AI itinerary.

Full path here: voice offer -> answer -> draft filled -> prefill -> the wizard's create payload ->
create_trip_for_user -> itinerary. Google and the AI are simulated; SQLite + local Redis.
Run from backend/: python -m tests.test_pilgrimage_accept
"""
import contextlib
import io
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
import voice.tools.lookups as LK  # noqa: E402
from voice import agent as AG, draft as D  # noqa: E402
from models import AuthUser  # noqa: E402
from models_itinerary import ItineraryActivityModel, ItineraryDayModel, ItineraryModel  # noqa: E402
from models_trip import TripModel  # noqa: E402
from redis_client import redis_conn  # noqa: E402

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail != "" and not cond else ""), flush=True)


pilgrimage.init_cards()
V = pilgrimage.get_card("varanasi-kashi-yatra")
UID = f"usr_accept{uuid.uuid4().hex[:6]}"
USER = AuthUser(id=UID, provider="EMAIL", providerUserId=f"{UID}@example.com", email=f"{UID}@example.com", createdAt="t", lastLoginAt="t")
START = date.today() + timedelta(days=20)
VARANASI_HIT = {"place_id": "ChIJvaranasi", "name": "Varanasi", "displayName": "Varanasi, Uttar Pradesh, India",
                "latitude": 25.3176, "longitude": 82.9739}


def find_place(q, search_fn=None):
    return VARANASI_HIT if pilgrimage.match_card(q) is V or q.lower() == "varanasi" else None


def google(query):
    name, city = [x.strip() for x in query.rsplit(",", 1)]
    return SimpleNamespace(unavailable=False, ambiguous=False, results=[{
        "place_id": "ChIJ" + uuid.uuid5(uuid.NAMESPACE_DNS, name).hex[:16], "name": name,
        "displayName": f"{name}, {city}, Uttar Pradesh, India", "latitude": 25.3, "longitude": 83.0}])


ai_prompts = []


def ai(prompt):
    ai_prompts.append(prompt)
    return json.dumps({"days": [{"dayNumber": 4, "title": "Riverfront", "places": [{"name": "Assi Ghat", "description": "A ghat."}]}]})


def no_llm(*a, **k):
    raise AssertionError("the LLM must not be called for a yes / the date read-back")


def turn(text, cid):
    with mock.patch("openai_client.chat_tools", no_llm):
        return AG.run_agent(text, "hi", user_id=UID, conversation_id=cid, screen="/home", trip=None, redis_conn=redis_conn)


def wizard_payload(prefill):
    """What TripCreationWizard.handleProceed sends for a voice prefill (frontend/src/features/trip/screens)."""
    p = {"destination": prefill["destination"], "origin": prefill.get("origin"), "startDate": prefill["startDate"],
         "endDate": prefill["endDate"], "adultsCount": prefill["adultsCount"], "childrenCount": prefill["childrenCount"],
         "tripStyle": [], "budgetAmount": prefill["customBudgetAmount"], "clientRequestId": f"req_{uuid.uuid4().hex[:8]}"}
    if prefill.get("planCardId"):
        p["planCardId"] = prefill["planCardId"]
    return p


# Jobs are recorded, not pushed: a running worker would take them from the shared Redis queue.
ENQUEUED = []


def queued(trip_id):
    return [t for t in ENQUEUED if t == trip_id]


def items(db, trip_id):
    itin = db.query(ItineraryModel).filter(ItineraryModel.trip_id == trip_id).first()
    if not itin:
        return None, []
    days = db.query(ItineraryDayModel).filter(ItineraryDayModel.itinerary_id == itin.id).order_by(ItineraryDayModel.day_number).all()
    return itin, [[a.title for a in db.query(ItineraryActivityModel).filter(ItineraryActivityModel.day_id == d.id).all()] for d in days]


def voice_trip(days, answer):
    """Speak the trip, accept the card with `answer`, fill the rest, confirm the dates; returns (prefill, log)."""
    cid = f"conv_{uuid.uuid4().hex[:8]}"
    log = io.StringIO()
    with mock.patch.object(LK, "find_place", find_place), contextlib.redirect_stdout(log):
        r1 = AG.update_draft(redis_conn, UID, cid, {"destination": "वाराणसी", "days": days}, "hi")
        r2 = turn(answer, cid)
        AG.update_draft(redis_conn, UID, cid, {"start_date": START.isoformat(), "adults": 2, "children": 0, "budget_inr": 45000}, "hi")
        r3 = turn("सही है।", cid)
    d = D.load(redis_conn, UID, cid)
    prefill = D.prefill(d) if d else {}
    AG.clear_memory(redis_conn, UID, cid)
    D.delete(redis_conn, UID, cid)
    return r1, r2, r3, prefill, log.getvalue()


def create(prefill):
    log = io.StringIO()
    with mock.patch.object(PCI, "_default_search", google), mock.patch("ai_provider.complete_json", ai), \
            mock.patch("media_service.media_service.resolve_cover_media", lambda d: {}), contextlib.redirect_stdout(log), \
            mock.patch.object(trip_lifecycle, "enqueue_itinerary_generation", lambda tid: ENQUEUED.append(tid) or True), \
            database.SessionLocal() as db:
        out = trip_lifecycle.create_trip_for_user(db, USER, None, None, wizard_payload(prefill))
    return out, log.getvalue()


made = []

# ---------------- the reported case: "हाँ, शुरू करो." for Varanasi, 3 days

for answer in ("हाँ, शुरू करो.", "haan, shuru", "haan shuru karo", "हाँ", "haan"):
    r1, r2, r3, prefill, vlog = voice_trip(3, answer)
    check(f"offer asked for वाराणसी", r1.step == "plan_offer", r1.step)
    check(f"{answer!r} accepts the card", r2.reply_text.startswith(AG.PLAN_ACCEPTED["hi"]), r2.reply_text)
    check(f"{answer!r}: prefill carries planCardId", prefill.get("planCardId") == V.id, prefill.get("planCardId"))
    check(f"{answer!r}: accept log line (ids only)", f"[PILGRIMAGE] accepted card={V.id} draft=" in vlog
          and "शुरू" not in vlog and "shuru" not in vlog, vlog[-300:])
    check("draft reached the review page", r3.step == "ready", r3.step)

for answer in ("nahi", "नहीं"):
    r1, r2, r3, prefill, _ = voice_trip(3, answer)
    check(f"{answer!r} declines: no planCardId", "planCardId" not in prefill)
r1, r2, r3, prefill, _ = voice_trip(3, "shuru karo")
check("'shuru karo' without a yes word does not accept", "planCardId" not in prefill)

# ---------------- 3 days: the card exactly, no AI job queued, no AI call

_, _, _, prefill, _ = voice_trip(3, "हाँ, शुरू करो.")
ai_prompts.clear()
out, clog = create(prefill)
made.append(out["id"])
with database.SessionLocal() as db:
    itin, titles = items(db, out["id"])
    trip = db.query(TripModel).filter(TripModel.id == out["id"]).first()
    meta = (trip.preferences_snapshot or {}).get("planCard") or {}
check("3 days: trip stores card id/version/status/last_verified/booking notes", meta.get("id") == V.id and meta.get("version") == V.version
      and meta.get("status") == V.status and "lastVerified" in meta and meta.get("bookingNotes"), sorted(meta))
check("3 days: items are the card's stops, in order", titles == [[s.name for s in d.stops] for d in V.days], titles)
check("3 days: NO itinerary job queued", queued(out["id"]) == [], len(queued(out["id"])))
check("3 days: no AI call", ai_prompts == [])
check("3 days: trip READY at creation, days marked from the card", out.get("itineraryStatus") == "READY"
      and [d["source"] for d in meta.get("days", [])] == ["card"] * 3, (out.get("itineraryStatus"), meta.get("days")))
check("3 days: built log line (ids and counts only)", f"[PILGRIMAGE] built trip={out['id']} card={V.id} user_days=3 card_days=3 ai_days=0 unresolved_stops=0" in clog, clog[-400:])

# ---------------- 2 days: must stops kept, built at creation, no job

_, _, _, prefill, _ = voice_trip(2, "haan")
out, clog = create(prefill)
made.append(out["id"])
with database.SessionLocal() as db:
    itin, titles = items(db, out["id"])
check("2 days: days 1-2 of the card, optional Sarnath dropped", titles == [[s.name for s in V.days[0].stops], [s.name for s in V.days[1].stops]], titles)
check("2 days: NO itinerary job queued", queued(out["id"]) == [])

# ---------------- 4 days: card days now, the AI only for day 4 (in the worker)

_, _, _, prefill, _ = voice_trip(4, "हाँ, शुरू करो.")
ai_prompts.clear()
out, clog = create(prefill)
made.append(out["id"])
check("4 days: a job is queued (day 4 needs the AI)", len(queued(out["id"])) == 1)
with mock.patch.object(PCI, "_default_search", google), mock.patch("ai_provider.complete_json", ai), \
        mock.patch.object(itinerary_service, "get_cached_itinerary", side_effect=AssertionError("cache")), \
        contextlib.redirect_stdout(io.StringIO()) as wlog:
    status = itinerary_service.process_async_itinerary_generation(out["id"], database.SessionLocal)
with database.SessionLocal() as db:
    itin, titles = items(db, out["id"])
    meta = db.query(TripModel).filter(TripModel.id == out["id"]).first().preferences_snapshot["planCard"]
check("4 days: days 1-3 are the card exactly, day 4 from the AI", status == "READY"
      and titles[:3] == [[s.name for s in d.stops] for d in V.days] and titles[3] == ["Assi Ghat"], titles)
check("4 days: the AI was asked once, for day 4 only", len(ai_prompts) == 1 and "trip days 4 to 4" in ai_prompts[0])
check("4 days: sources card,card,card,ai", [d["source"] for d in meta["days"]] == ["card", "card", "card", "ai"])
check("4 days: built log line", f"card={V.id} user_days=4 card_days=3 ai_days=1" in wlog.getvalue(), wlog.getvalue()[-300:])

# ---------------- accepted but not used: the reason is logged

bad = dict(prefill)
bad["destination"] = {**prefill["destination"], "id": "ChIJgoa", "name": "Goa", "city": "Goa", "displayName": "Goa, India",
                      "latitude": 15.3, "longitude": 74.1}
out, clog = create(bad)
made.append(out["id"])
check("card id with a changed destination: not used, reason logged", "planCard" not in out["preferencesSnapshot"]
      and f"[PILGRIMAGE] card not used card={V.id} reason=destination_changed" in clog, clog[-300:])
check("not used: the normal job is queued as before", len(queued(out["id"])) == 1)

# ---------------- cleanup

for key in redis_conn.scan_iter("rl:*"):
    redis_conn.delete(key)
database.engine.dispose()
shutil.rmtree(SCRATCH, ignore_errors=True)
print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
