"""
Work / event trips: the generic blocks repeat across days without failing validation (feat/trip-purpose).
Fake LLM, fake Google, no real calls.

Evidence: Kolkata -> Bengaluru, purpose event, base area Electronic City. A 2-day trip FAILED after 4 attempts
("Duplicate activity detected across days: 'Your event, in the Electronic City area' at 'Electronic City area'" and
"'Work Session - Hotel Room' at 'Hotel near Electronic City'"); a 3-day trip passed only on the 4th attempt.
Checks:
  1. validate_and_sanitize_itinerary: on an event trip, the blocks marked planSlot EVENT / WORK / STAY may repeat
     (same title, same place, same coordinates on every day). The same plan on a leisure trip still fails; on an
     event trip, the same blocks WITHOUT the marker still fail (a structured marker, no text matching), and a real
     restaurant repeated on two days still fails.
  2. The real job (process_async_itinerary_generation) with a fake LLM returning the blocks on every day: READY on
     the first attempt (validate_output called once).
  3. place_verify: no Google look-up for the EVENT / WORK / STAY blocks; no verify_status on EVENT / WORK lines;
     WORK lines get the stay hotel's name and coordinates (no place id); real venues are still checked.
  4. The cache key of an event trip has no style part; leisure is unchanged.
Run from backend/: python -m tests.test_trip_purpose_repeat
"""
import io
import json
import os
import sys
import tempfile
import uuid
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import dotenv

dotenv.load_dotenv = lambda *a, **k: None
os.environ["DATABASE_URL"] = "postgresql://x:y@127.0.0.1:1/none"
os.environ["AI_PROVIDER"] = "mock"
os.environ["OPENAI_API_KEY"] = "test-key-not-real"

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)
SCRATCH = tempfile.mkdtemp(prefix="voyageai_test_")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

import database  # noqa: E402

database.engine = create_engine(f"sqlite:///{os.path.join(SCRATCH, 'repeat.db')}", connect_args={"check_same_thread": False})
database.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=database.engine)
import models_db, models_trip, models_itinerary, models_package, models_place  # noqa: E401,E402,F401
database.Base.metadata.create_all(bind=database.engine)

import ai_provider  # noqa: E402
import itinerary_service as I  # noqa: E402
import place_verify as PV  # noqa: E402
import plan_card_itinerary as PCI  # noqa: E402
import purpose_plan as PP  # noqa: E402
from itinerary_cache_service import build_itinerary_cache_key  # noqa: E402
from models_itinerary import ItineraryActivityModel, ItineraryDayModel, ItineraryModel  # noqa: E402
from models_trip import TripModel  # noqa: E402
from schemas_itinerary import GeneratedItinerarySchema  # noqa: E402

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if (detail != "" and not cond) else ""), flush=True)


BASE = (12.845, 77.66)
EC = {"id": "ChIJec", "name": "Electronic City", "city": "Bengaluru", "region": "Karnataka",
      "latitude": BASE[0], "longitude": BASE[1]}
DEST = {"name": "Bengaluru", "city": "Bengaluru", "country": "India", "latitude": 12.97, "longitude": 77.59}


def a(title, loc, kind="DINING", time="09:00 AM", slot=None, lat=None, lng=None):
    out = {"timeSlot": time, "title": title, "description": "x", "activityType": kind, "locationName": loc,
           "latitude": lat, "longitude": lng, "estimatedCostInr": 0}
    if slot:
        out["planSlot"] = slot
    return out


def day(n, acts):
    return {"dayNumber": n, "date": f"2026-12-{11 + n}", "title": f"Day {n}", "summary": "s", "activities": acts}


# The 2-day evidence: the event block and the hotel-room work block on both days, same title, same place, and
# (as models do) the base area's coordinates on every generic block.
def generic_plan(marked=True, meal2="Udupi Upahar, Electronic City Phase 1"):
    s = (lambda v: v) if marked else (lambda v: None)
    return {"title": "Plan", "days": [
        day(1, [a("Airport to Electronic City", "Kempegowda International Airport", kind="TRANSIT", time="07:00 AM"),
                a("Check in: Hotel near Electronic City", "Hotel near Electronic City", kind="RELAXATION",
                  time="08:30 AM", slot=s("STAY"), lat=BASE[0], lng=BASE[1]),
                a("Your event, in the Electronic City area", "Electronic City area", kind="SIGHTSEEING",
                  time="10:00 AM", slot=s("EVENT"), lat=BASE[0], lng=BASE[1]),
                a("Lunch at Neo Food Court", "Neo Food Court, Electronic City Phase 1", time="01:30 PM"),
                a("Work Session - Hotel Room", "Hotel near Electronic City", kind="RELAXATION", time="06:00 PM",
                  slot=s("WORK"), lat=BASE[0], lng=BASE[1])]),
        day(2, [a("Stay: Hotel near Electronic City", "Hotel near Electronic City", kind="RELAXATION",
                  time="08:00 AM", slot=s("STAY"), lat=BASE[0], lng=BASE[1]),
                a("Your event, in the Electronic City area", "Electronic City area", kind="SIGHTSEEING",
                  time="10:00 AM", slot=s("EVENT"), lat=BASE[0], lng=BASE[1]),
                a(f"Lunch at {meal2.split(',')[0]}", meal2, time="01:30 PM"),
                a("Work Session - Hotel Room", "Hotel near Electronic City", kind="RELAXATION", time="04:00 PM",
                  slot=s("WORK"), lat=BASE[0], lng=BASE[1]),
                a("Electronic City to the airport", "Kempegowda International Airport", kind="TRANSIT", time="07:00 PM")]),
    ], "transportSuggestions": []}


def validate(plan, purpose):
    return I.validate_and_sanitize_itinerary(GeneratedItinerarySchema.model_validate(plan), 2, "2026-12-12", purpose)


print("\n== 1. the duplicate check")
ok, msg = validate(generic_plan(), "event")
check("event: EVENT / WORK / STAY blocks repeated on every day -> valid", ok, msg)
for p in ("business", "other"):
    check(f"{p}: the same -> valid", validate(generic_plan(), p)[0])
for p in ("leisure", "pilgrimage", None):
    ok, msg = validate(generic_plan(), p)
    check(f"{p}: the same repeated structure still fails (strict as before)", not ok and "Duplicate activity" in msg, msg)
ok, msg = validate(generic_plan(marked=False), "event")
check("event, blocks WITHOUT planSlot: still a duplicate (marker, not text matching)",
      not ok and "Duplicate activity" in msg, msg)
ok, msg = validate(generic_plan(meal2="Neo Food Court, Electronic City Phase 1"), "event")
check("event: the same real restaurant on two days -> still rejected",
      not ok and "Duplicate activity" in msg and "Neo Food Court" in msg, msg)
fake_slot = generic_plan(meal2="Neo Food Court, Electronic City Phase 1")
fake_slot["days"][1]["activities"][2]["planSlot"] = "MEAL"
check("an unknown planSlot value is no exemption", not validate(fake_slot, "event")[0])
same_pt = generic_plan()
for i, nm in enumerate(("Cafe One, Electronic City", "Cafe Two, Electronic City", "Cafe Three, Electronic City")):
    same_pt["days"][0]["activities"].append(a(nm, nm, time=f"0{i + 2}:00 PM", lat=12.9, lng=77.6))
ok, msg = validate(same_pt, "event")
check("event: 3 real named places on one coordinate pair -> still rejected", not ok and "Coordinate pair" in msg, msg)

# ---------------------------------------------------------------- the real job
NOW = datetime.now(timezone.utc).isoformat()
USER = f"usr_rep_{uuid.uuid4().hex[:6]}"


def make_trip(purpose_type="event", text="hackathon", area=EC):
    tid = f"trip_rep_{uuid.uuid4().hex[:8]}"
    with database.SessionLocal() as db:
        db.add(TripModel(id=tid, user_id=USER, title="Bengaluru Tour Package", status="PLANNING", start_date="2026-12-12",
                         end_date="2026-12-13", total_days=2, destination=DEST, travelers=[{"id": "tr_1", "type": "ADULT"}],
                         budget={"level": "PREMIUM", "targetAmount": 15000},
                         preferences_snapshot={"travelStyles": ["LUXURY", "NIGHTLIFE"]},
                         purpose_type=purpose_type, purpose_text=text, base_area_json=json.dumps(area) if area else None,
                         created_at=NOW, updated_at=NOW, itinerary_status="GENERATING"))
        db.commit()
    return tid


ATTEMPTS = []
KEYS = []
VENUE_QUERIES = []
HOTEL_CALLS = []
VENUES = {"neo food court, electronic city phase 1": ("Neo Food Court", 12.846, 77.661),
          "udupi upahar, electronic city phase 1": ("Udupi Upahar Electronic City Phase 1", 12.847, 77.662)}
LEMON = {"id": "ChIJ_lemon", "place_id": "ChIJ_lemon", "name": "Lemon Tree Hotel, Electronic City",
         "latitude": BASE[0] + 0.008, "longitude": BASE[1], "display_name": "Lemon Tree Hotel, Hosur Road, Bengaluru",
         "types": ["lodging", "hotel"], "rating": 4.3, "user_rating_count": 5400}


def fake_venue_search(query):
    VENUE_QUERIES.append(query)
    key = query[: -len(" Bengaluru")].lower() if query.endswith(" Bengaluru") else query.lower()
    hit = VENUES.get(key)
    rs = [{"place_id": f"ChIJ_{hit[0].replace(' ', '')}", "name": hit[0], "latitude": hit[1], "longitude": hit[2]}] if hit else []
    return SimpleNamespace(results=rs, unavailable=False, ambiguous=False)


def fake_hotels(query, lat, lng, radius_m):
    HOTEL_CALLS.append(query)
    return [LEMON]


def fake_generate(prompt, validate_output, correction_prompt):
    """Like ai_provider.generate_itinerary: up to 4 attempts, each answer checked by validate_output."""
    for _ in range(4):
        ATTEMPTS.append(1)
        schema, err = validate_output(json.dumps(generic_plan()))
        if schema is not None:
            return schema, "OPENAI"
    raise ai_provider.ItineraryGenerationError(err) if hasattr(ai_provider, "ItineraryGenerationError") else ValueError(err)


def run_job(tid):
    with mock.patch.object(I, "get_cached_itinerary", lambda key: KEYS.append(key)), \
            mock.patch.object(I, "set_cached_itinerary", lambda key, data: None), \
            mock.patch.object(ai_provider, "ai_provider_name", lambda: "openai"), \
            mock.patch.object(ai_provider, "generate_itinerary", fake_generate), \
            mock.patch.object(PCI, "_default_search", fake_venue_search), \
            mock.patch.object(PP, "_google_hotels", fake_hotels):
        buf = io.StringIO()
        with redirect_stdout(buf):
            status = I.process_async_itinerary_generation(tid, database.SessionLocal)
    return status, buf.getvalue()


def rows(tid):
    with database.SessionLocal() as db:
        itin = db.query(ItineraryModel).filter(ItineraryModel.trip_id == tid).one()
        days = db.query(ItineraryDayModel).filter(ItineraryDayModel.itinerary_id == itin.id).order_by(ItineraryDayModel.day_number).all()
        out = []
        for dday in days:
            for x in db.query(ItineraryActivityModel).filter(ItineraryActivityModel.day_id == dday.id).all():
                out.append(SimpleNamespace(day=dday.day_number, title=x.title, loc=x.location_name, lat=x.latitude,
                                           pid=x.place_id, status=x.verify_status))
        return out


print("\n== 2. the real job: an event trip with the blocks on every day passes on the first attempt")
tid = make_trip()
status, log = run_job(tid)
check("trip READY", status == "READY", status)
check("validated on the first attempt (no correction round)", len(ATTEMPTS) == 1, len(ATTEMPTS))
check("cache key: no style part (account styles LUXURY, NIGHTLIFE)", KEYS and "luxury" not in KEYS[-1]
      and "nightlife" not in KEYS[-1] and KEYS[-1].endswith(":purpose_event:area_ChIJec:pv3"), KEYS)

print("\n== 3. place verify skips the generic blocks")
r = rows(tid)
check("no Google venue look-up for the event, the hotel-room sessions or the stay lines",
      not any("electronic city area" in q.lower() or "hotel" in q.lower() for q in VENUE_QUERIES)
      and len(VENUE_QUERIES) == 2, VENUE_QUERIES)
check("ONE hotel search for the whole trip", HOTEL_CALLS == ["hotel near Electronic City, Bengaluru"], HOTEL_CALLS)
ev = [x for x in r if x.title.startswith("Your ")]
check("event lines: no verify_status, no place id", len(ev) == 2 and all(x.status is None and x.pid is None for x in ev),
      [(x.title, x.status) for x in ev])
work = [x for x in r if x.title == "Work Session - Hotel Room"]
check("work lines: no verify_status, no place id, the stay hotel as their place",
      len(work) == 2 and all(x.status is None and x.pid is None and x.loc == "Your room at Lemon Tree Hotel, Electronic City"
                             and x.lat == LEMON["latitude"] for x in work), [(x.loc, x.status, x.pid) for x in work])
check("stay lines: the real hotel, verified", sorted(x.title for x in r if x.title.startswith(("Check in", "Stay")))
      == ["Check in: Lemon Tree Hotel, Electronic City", "Stay: Lemon Tree Hotel, Electronic City"])
check("real venues still checked: the two meals verified",
      sorted(x.pid for x in r if x.status == "verified" and x.title.startswith("Lunch")) == ["ChIJ_NeoFoodCourt", "ChIJ_UdupiUpaharElectronicCityPhase1"],
      [(x.title, x.status, x.pid) for x in r])
check("no 'not_found' anywhere", not any(x.status == "not_found" for x in r))

print("\n== 3b. no hotel found: work lines say 'Hotel near Electronic City', still no label")
s = GeneratedItinerarySchema.model_validate(generic_plan())
trip = SimpleNamespace(id="t", title="Bengaluru", destination=DEST, purpose_type="event", purpose_text="hackathon", base_area=EC)
with redirect_stdout(io.StringIO()):
    out = PV.verify_itinerary(s, trip, fake_venue_search, hotel_search_fn=lambda *x: [])
w = PP.slot_override(s.days[0].activities[4], trip, out.get((0, 4)))
check("work line without a hotel: 'Hotel near Electronic City', no coordinates, no status",
      w["location_name"] == "Hotel near Electronic City" and w["latitude"] is None and w["verify_status"] is None, w)
check("event positions get no record at all", (0, 2) not in out and (1, 1) not in out, sorted(out))

print("\n== 4. leisure: the job is unchanged (the same plan fails validation, key keeps its style)")
ATTEMPTS.clear()
lt = make_trip(purpose_type="leisure", text=None, area=None)
status, log = run_job(lt)
check("leisure with the repeated blocks: FAILED after 4 attempts", status == "FAILED" and len(ATTEMPTS) == 4,
      (status, len(ATTEMPTS)))
check("leisure key: byte-identical to before", KEYS[-1] == "itinerary:bengaluru:2d:luxury_nightlife:premium:from_noorigin",
      KEYS[-1])
check("leisure key via the builder: unchanged", build_itinerary_cache_key("Bengaluru", 2, "LUXURY, NIGHTLIFE", "PREMIUM",
                                                                         "Kolkata", purpose_type="leisure")
      == "itinerary:bengaluru:2d:luxury_nightlife:premium:from_kolkata")

with database.SessionLocal() as db:
    db.query(TripModel).filter(TripModel.user_id == USER).delete()
    db.commit()

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
