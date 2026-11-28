"""
Work / event trips: no invented event, venue or hotel (feat/trip-purpose). Fake LLM, fake Google, no real calls.

Evidence: a Kolkata -> Bengaluru hackathon trip (base area Electronic City) got "Hackathon Session - NASSCOM Centre"
(never named by the user) and "The Grand Magrath, Electronic City" (a hotel in central Bengaluru, ~16 km away).
Checks:
  B. purpose_plan.find_stay_hotel: ONE search "hotel near Electronic City, Bengaluru" (type lodging, 3 km circle round
     the base area); only lodging within 3 km with >= 20 reviews; the best rating wins (more reviews break a tie).
     Then the real job (process_async_itinerary_generation) with a fake LLM that names the Grand Magrath on the
     check-in and a later stay line: both get the same real hotel's name, address, place_id, coordinates and
     verify_status "verified"; the model's hotel name is gone. Google returns nothing / raises -> "Hotel near
     Electronic City", no name, no place id, the trip still READY. The hotel search counts in the Google call cap.
  A. the event line the model wrote with a venue and a time ("Hackathon Session - NASSCOM Centre", 10:00 AM) is
     written by code: "Your hackathon, in the Electronic City area", "Venue and timings as per your hackathon.",
     no clock time, no coordinates, no place id.
  Leisure trips are untouched even if a plan carries planSlot.
  E. place_verify: a stop ~16 km from the base area is "far" by the base-area rule; the same stop on a trip without a
     base area is NOT flagged by the day-median rule (40 km), so a "far" on that hotel can only have come from the
     base-area check (the label's wording is chosen by the frontend from the trip's baseArea).
Run from backend/: python -m tests.test_trip_purpose_stay
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

database.engine = create_engine(f"sqlite:///{os.path.join(SCRATCH, 'stay.db')}", connect_args={"check_same_thread": False})
database.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=database.engine)
import models_db, models_trip, models_itinerary, models_package, models_place  # noqa: E401,E402,F401
database.Base.metadata.create_all(bind=database.engine)

import ai_provider  # noqa: E402
import itinerary_service as I  # noqa: E402
import place_verify as PV  # noqa: E402
import plan_card_itinerary as PCI  # noqa: E402
import purpose_plan as PP  # noqa: E402
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


def hotel(pid, name, dlat, rating, reviews, types=("lodging", "hotel")):
    return {"id": pid, "place_id": pid, "name": name, "latitude": BASE[0] + dlat, "longitude": BASE[1],
            "display_name": f"{name}, Hosur Road, Electronic City Phase 1, Bengaluru", "city": "x",
            "types": list(types), "rating": rating, "user_rating_count": reviews}


HOTELS = [
    hotel("ChIJ_lemon", "Lemon Tree Hotel, Electronic City", 0.008, 4.3, 5400),        # ~0.9 km
    hotel("ChIJ_ramada", "Ramada Encore Bangalore Domlur", 0.045, 4.8, 900),            # ~5 km: outside 3 km
    hotel("ChIJ_new", "Brand New Inn", 0.004, 4.9, 12),                                 # too few reviews
    hotel("ChIJ_cafe", "Cafe Stay Coffee", 0.002, 5.0, 3000, types=("cafe", "restaurant")),  # not lodging
    hotel("ChIJ_tie", "Keys Select Hotel", 0.010, 4.3, 800),                            # same rating, fewer reviews
]
HOTEL_CALLS = []


def fake_hotels(query, lat, lng, radius_m):
    HOTEL_CALLS.append((query, round(lat, 3), round(lng, 3), radius_m))
    return list(HOTELS)


def event_trip(area=EC, purpose_type="event", text="hackathon"):
    return SimpleNamespace(id="t", title="Bengaluru Tour Package", destination=DEST, purpose_type=purpose_type,
                           purpose_text=text, base_area=area)


print("\n== B. choosing the hotel (pure)")
h = PP.find_stay_hotel(event_trip(), fake_hotels)
check("ONE search: 'hotel near Electronic City, Bengaluru', 3 km circle round the base area",
      HOTEL_CALLS == [("hotel near Electronic City, Bengaluru", 12.845, 77.66, 3000)], HOTEL_CALLS)
check("best rating within 3 km with >= 20 reviews, lodging only; a tie goes to more reviews",
      h and h["place_id"] == "ChIJ_lemon" and h["name"] == "Lemon Tree Hotel, Electronic City", h)
check("name, address, place_id and coordinates kept", h["address"].startswith("Lemon Tree Hotel, Electronic City, Hosur Road")
      and h["latitude"] == BASE[0] + 0.008 and h["longitude"] == BASE[1])
check("STAY_RADIUS_KM 3, STAY_MIN_REVIEWS 20", PP.STAY_RADIUS_KM == 3.0 and PP.STAY_MIN_REVIEWS == 20)
check("Google returns nothing -> None", PP.find_stay_hotel(event_trip(), lambda *a: []) is None)


def boom(*a):
    raise RuntimeError("quota")


with redirect_stdout(io.StringIO()):
    check("Google raises -> None (never into trip creation)", PP.find_stay_hotel(event_trip(), boom) is None)
check("only far / unrated results -> None", PP.find_stay_hotel(event_trip(), lambda *a: [HOTELS[1], HOTELS[2], HOTELS[3]]) is None)
HOTEL_CALLS.clear()
PP.find_stay_hotel(event_trip(area=None), fake_hotels)
check("no base area -> the destination centre: 'hotel near Bengaluru'",
      HOTEL_CALLS and HOTEL_CALLS[0][:3] == ("hotel near Bengaluru", 12.97, 77.59), HOTEL_CALLS)

# ---------------------------------------------------------------- the real job
NOW = datetime.now(timezone.utc).isoformat()
USER = f"usr_stay_{uuid.uuid4().hex[:6]}"


def make_trip(purpose_type="event", text="hackathon", area=EC):
    tid = f"trip_stay_{uuid.uuid4().hex[:8]}"
    with database.SessionLocal() as db:
        db.add(TripModel(id=tid, user_id=USER, title="Bengaluru Tour Package", status="PLANNING", start_date="2026-12-12",
                         end_date="2026-12-13", total_days=2, destination=DEST, travelers=[{"id": "tr_1", "type": "ADULT"}],
                         budget={"level": "MODERATE", "targetAmount": 12000}, preferences_snapshot={"travelStyles": []},
                         purpose_type=purpose_type, purpose_text=text, base_area_json=json.dumps(area) if area else None,
                         created_at=NOW, updated_at=NOW, itinerary_status="GENERATING"))
        db.commit()
    return tid


def a(slot, title, loc, kind="DINING", time="09:00 AM", lat=None, lng=None, plan_slot=None, cost=0):
    out = {"timeSlot": time, "title": title, "description": "x", "activityType": kind, "locationName": loc,
           "latitude": lat, "longitude": lng, "estimatedCostInr": cost}
    if plan_slot:
        out["planSlot"] = plan_slot
    return out


# What the model did in the evidence: a named venue + time for the event, a named hotel far away.
MODEL_PLAN = {"title": "Plan", "days": [
    {"dayNumber": 1, "date": "2026-12-12", "title": "Arrive", "summary": "s", "activities": [
        a(1, "Airport to Electronic City", "Kempegowda International Airport", kind="TRANSIT", time="07:00 AM"),
        a(1, "Check in: The Grand Magrath, Electronic City", "The Grand Magrath, Electronic City", kind="RELAXATION",
          time="11:00 AM", lat=12.9703, lng=77.6108, plan_slot="STAY", cost=4500),
        a(1, "Hackathon Session - NASSCOM Centre", "NASSCOM Centre, Electronic City", kind="SIGHTSEEING", time="10:00 AM",
          lat=12.84, lng=77.67, plan_slot="EVENT"),
        a(1, "Lunch at Food Court", "Neo Food Court, Electronic City Phase 1", time="01:30 PM")]},
    {"dayNumber": 2, "date": "2026-12-13", "title": "Back", "summary": "s", "activities": [
        a(2, "Stay: The Grand Magrath", "The Grand Magrath, Electronic City", kind="RELAXATION", time="08:00 AM",
          plan_slot="STAY"),
        a(2, "Breakfast", "Udupi Upahar, Electronic City Phase 1", time="09:00 AM"),
        a(2, "Electronic City to the airport", "Kempegowda International Airport", kind="TRANSIT", time="06:00 PM")]},
], "transportSuggestions": []}
VENUES = {"neo food court, electronic city phase 1": ("Neo Food Court", 12.846, 77.661),
          "udupi upahar, electronic city phase 1": ("Udupi Upahar", 12.847, 77.662)}
VENUE_QUERIES = []


def fake_venue_search(query):
    VENUE_QUERIES.append(query)
    key = query[: -len(" Bengaluru")].lower() if query.endswith(" Bengaluru") else query.lower()
    hit = VENUES.get(key)
    rs = [{"place_id": f"ChIJ_{hit[0].replace(' ', '')}", "name": hit[0], "latitude": hit[1], "longitude": hit[2]}] if hit else []
    return SimpleNamespace(results=rs, unavailable=False, ambiguous=False)


def fake_generate(prompt, validate_output, correction_prompt):
    schema, err = validate_output(json.dumps(MODEL_PLAN))
    assert schema is not None, err
    return schema, "OPENAI"


def run_job(tid, hotels=fake_hotels):
    with mock.patch.object(I, "get_cached_itinerary", lambda key: None), \
            mock.patch.object(I, "set_cached_itinerary", lambda key, data: None), \
            mock.patch.object(ai_provider, "ai_provider_name", lambda: "openai"), \
            mock.patch.object(ai_provider, "generate_itinerary", fake_generate), \
            mock.patch.object(PCI, "_default_search", fake_venue_search), \
            mock.patch.object(PP, "_google_hotels", hotels):
        buf = io.StringIO()
        with redirect_stdout(buf):
            status = I.process_async_itinerary_generation(tid, database.SessionLocal)
    return status, buf.getvalue()


def acts(tid):
    with database.SessionLocal() as db:
        itin = db.query(ItineraryModel).filter(ItineraryModel.trip_id == tid).one()
        days = db.query(ItineraryDayModel).filter(ItineraryDayModel.itinerary_id == itin.id).order_by(ItineraryDayModel.day_number).all()
        out = []
        for dday in days:
            for x in db.query(ItineraryActivityModel).filter(ItineraryActivityModel.day_id == dday.id).all():
                out.append(SimpleNamespace(day=dday.day_number, title=x.title, desc=x.description, loc=x.location_name,
                                           time=x.time_slot, lat=x.latitude, lng=x.longitude, pid=x.place_id,
                                           status=x.verify_status, cost=x.estimated_cost_inr, kind=x.activity_type))
        return out


print("\n== B. the real job: the model's hotel replaced by the real one, on every stay line")
HOTEL_CALLS.clear()
tid = make_trip()
status, log = run_job(tid)
rows = acts(tid)
stays = [r for r in rows if r.title.startswith(("Check in", "Stay"))]
check("trip READY", status == "READY", status)
check("one hotel search for the trip (two stay lines)", len(HOTEL_CALLS) == 1, HOTEL_CALLS)
check("check-in line: the real hotel's name", any(r.title == "Check in: Lemon Tree Hotel, Electronic City" for r in stays),
      [r.title for r in stays])
check("the later stay line: the same hotel", any(r.title == "Stay: Lemon Tree Hotel, Electronic City" for r in stays),
      [r.title for r in stays])
check("both: address, place_id, coordinates, verified, no price", all(
    r.loc.startswith("Lemon Tree Hotel, Electronic City, Hosur Road") and r.pid == "ChIJ_lemon" and r.status == "verified"
    and r.lat == BASE[0] + 0.008 and r.cost == 0 for r in stays) and len(stays) == 2,
      [(r.loc, r.pid, r.status, r.cost) for r in stays])
check("the model's hotel name is gone everywhere", not any("Magrath" in (r.title + (r.loc or "")) for r in rows))
check("the hotel search counts in the Google call cap (log google_calls includes it, stay=found)",
      "stay=found" in log and "google_calls=" in log)
check("the stay lines are never looked up as venues", not any("Magrath" in q for q in VENUE_QUERIES), VENUE_QUERIES)

print("\n== A. the event line: written by code, no venue, no time")
ev = [r for r in rows if r.title.startswith("Your ")]
check("one event line: 'Your hackathon, in the Electronic City area'",
      len(ev) == 1 and ev[0].title == "Your hackathon, in the Electronic City area", [r.title for r in rows])
check("'Venue and timings as per your hackathon.', no clock time",
      ev and ev[0].desc == "Venue and timings as per your hackathon." and ev[0].time == "As per your event", ev and ev[0].time)
check("no coordinates, no place id, no NASSCOM", ev and ev[0].lat is None and ev[0].pid is None
      and not any("NASSCOM" in (r.title + (r.loc or "")) for r in rows))
check("other lines as the model wrote them (meals near the base area, the two travel legs)",
      any(r.title == "Lunch at Food Court" for r in rows) and sum(1 for r in rows if r.kind == "TRANSIT") == 2)

print("\n== B. Google returns nothing / raises: the generic line, the trip still READY")
for label, fn in (("nothing", lambda *a: []), ("raises", boom)):
    tid2 = make_trip()
    status, log = run_job(tid2, hotels=fn)
    rows2 = acts(tid2)
    stays2 = [r for r in rows2 if r.title.startswith(("Check in", "Stay"))]
    check(f"[{label}] trip READY", status == "READY", status)
    check(f"[{label}] 'Check in: Hotel near Electronic City' / 'Stay: Hotel near Electronic City', no name invented",
          sorted(r.title for r in stays2) == ["Check in: Hotel near Electronic City", "Stay: Hotel near Electronic City"]
          and all(r.loc == "Hotel near Electronic City" and r.pid is None and r.lat is None and r.status is None for r in stays2),
          [(r.title, r.loc, r.pid) for r in stays2])
    check(f"[{label}] no Magrath anywhere", not any("Magrath" in (r.title + (r.loc or "")) for r in rows2))
    check(f"[{label}] log: stay=generic", "stay=generic" in log)

print("\n== B. the call cap reached before the hotel: generic line")
s = GeneratedItinerarySchema.model_validate(MODEL_PLAN)
with redirect_stdout(io.StringIO()):
    out = PV.verify_itinerary(s, event_trip(), fake_venue_search, max_calls=0, hotel_search_fn=fake_hotels)
check("max_calls=0 -> no hotel, stays generic", all(r.get("stay") is None for r in out.values() if "stay" in r)
      and any("stay" in r for r in out.values()))

print("\n== a leisure trip is untouched (even if the plan carries planSlot)")
lt = make_trip(purpose_type="leisure", text=None, area=None)
status, log = run_job(lt)
rows3 = acts(lt)
check("leisure: the model's lines kept as they were, no hotel search", any("Magrath" in r.title for r in rows3)
      and any(r.title == "Hackathon Session - NASSCOM Centre" for r in rows3) and "stay=" not in log)

print("\n== E. why 'far' on that hotel: the base-area rule (~16 km); the day-median rule would not flag it")
MAG = (12.9703, 77.6108)            # Magrath Road, central Bengaluru
GOOGLE_EC = (12.8399, 77.6770)      # Google's "Electronic City" point
check("distance Magrath Road -> Electronic City ~16 km (> 15 km)", 15.0 < PCI._km(*MAG, *GOOGLE_EC) < 17.0,
      round(PCI._km(*MAG, *GOOGLE_EC), 1))
E_PLAN = {"title": "P", "days": [{"dayNumber": 1, "date": "2026-12-12", "title": "D", "summary": "s", "activities": [
    a(1, "The Grand Magrath", "The Grand Magrath", kind="RELAXATION", time="11:00 AM"),
    a(1, "Neo Food Court", "Neo Food Court", time="01:00 PM")]}]}
E_GOOGLE = {"the grand magrath": ("The Grand Magrath", *MAG), "neo food court": ("Neo Food Court", 12.846, 77.661)}


def e_search(query):
    key = query[: -len(" Bengaluru")].lower() if query.endswith(" Bengaluru") else query.lower()
    hit = E_GOOGLE.get(key)
    return SimpleNamespace(results=[{"place_id": f"ChIJ_{hit[0][:6]}", "name": hit[0], "latitude": hit[1],
                                     "longitude": hit[2]}] if hit else [], unavailable=False, ambiguous=False)


def e_run(trip):
    with redirect_stdout(io.StringIO()):
        out = PV.verify_itinerary(GeneratedItinerarySchema.model_validate(E_PLAN), trip, e_search)
    return {k: v["status"] for k, v in out.items()}


with_area = SimpleNamespace(id="e1", title="Bengaluru", destination=DEST, purpose_type="event",
                            base_area=dict(EC, latitude=GOOGLE_EC[0], longitude=GOOGLE_EC[1]))
without = SimpleNamespace(id="e2", title="Bengaluru", destination=DEST, purpose_type=None, base_area=None)
st = e_run(with_area)
check("with the base area: the hotel ~16 km away -> far (base-area rule)", st.get((0, 0)) == "far", st)
st = e_run(without)
check("without a base area: the same hotel is verified (the 40 km day-median rule does not flag ~16 km)",
      st.get((0, 0)) == "verified", st)

with database.SessionLocal() as db:
    db.query(TripModel).filter(TripModel.user_id == USER).delete()
    db.commit()

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
