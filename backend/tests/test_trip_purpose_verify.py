"""
The Google check follows the base area (feat/trip-purpose commit 4). Google simulated (a fake search_fn).

Checks: with a base area, a verified stop more than BASE_AREA_RADIUS_KM (15 km) from it is "far" and one 5 km away is
"verified", whatever the day's median says; a day with a single found stop is still checked; without a base area the
existing day-median rule stays (a day whose two stops are 20 km apart flags nothing; stops > 40 km from the median
are still "far").
Run from backend/: python -m tests.test_trip_purpose_verify
"""
import io
import json
import os
import sys
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

import dotenv

dotenv.load_dotenv = lambda *a, **k: None
os.environ["DATABASE_URL"] = "postgresql://x:y@127.0.0.1:1/none"
os.environ["AI_PROVIDER"] = "mock"

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)

import place_verify as PV  # noqa: E402
import trip_purpose as TP  # noqa: E402
from schemas_itinerary import GeneratedItinerarySchema  # noqa: E402

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if (detail != "" and not cond) else ""), flush=True)


BLR = (12.97, 77.59)
BASE = (12.845, 77.66)   # Electronic City
# venue -> (Google's name, lat, lng); distances from the base area in the names' comments
GOOGLE = {
    "infosys campus": ("Infosys Campus", BASE[0] + 0.045, BASE[1]),            # ~5 km
    "iskcon temple": ("ISKCON Temple", BASE[0] + 0.18, BASE[1]),              # ~20 km
    "hosur road dhaba": ("Hosur Road Dhaba", BASE[0] + 0.01, BASE[1] + 0.01),  # ~1.5 km
    "nandi hills": ("Nandi Hills", 13.37, 77.68),                              # ~58 km
    "mysore palace": ("Mysore Palace", 12.305, 76.655),                        # ~125 km
}


def fake_google(query):
    venue = query[: -len(" Bengaluru")].lower() if query.endswith(" Bengaluru") else query.lower()
    hit = GOOGLE.get(venue)
    if hit is None:
        return SimpleNamespace(results=[], unavailable=False, ambiguous=False)
    name, lat, lng = hit
    return SimpleNamespace(results=[{"place_id": f"ChIJ_{name.replace(' ', '')}", "name": name, "latitude": lat,
                                     "longitude": lng}], unavailable=False, ambiguous=False)


def act(slot, title, loc):
    return {"timeSlot": slot, "title": title, "description": "x", "activityType": "SIGHTSEEING", "locationName": loc,
            "latitude": None, "longitude": None, "estimatedCostInr": 0}


PLAN = {"title": "Plan", "days": [
    {"dayNumber": 1, "date": "2026-12-13", "title": "D1", "summary": "s",
     "activities": [act("09:00 AM", "Infosys Campus", "Infosys Campus"), act("06:00 PM", "ISKCON Temple", "ISKCON Temple")]},
    {"dayNumber": 2, "date": "2026-12-14", "title": "D2", "summary": "s",
     "activities": [act("10:00 AM", "Hosur Road Dhaba", "Hosur Road Dhaba")]},
    {"dayNumber": 3, "date": "2026-12-15", "title": "D3", "summary": "s",
     "activities": [act("09:00 AM", "Hosur Road Dhaba lunch", "Hosur Road Dhaba"), act("01:00 PM", "Nandi Hills", "Nandi Hills"),
                    act("05:00 PM", "Mysore Palace", "Mysore Palace")]},
]}


def run(trip):
    s = GeneratedItinerarySchema.model_validate(json.loads(json.dumps(PLAN)))
    with redirect_stdout(io.StringIO()):
        out = PV.verify_itinerary(s, trip, fake_google)
    return {k: v["status"] for k, v in out.items()}


DEST = {"name": "Bengaluru", "latitude": BLR[0], "longitude": BLR[1]}
with_area = SimpleNamespace(id="t_area", title="Bengaluru", destination=DEST, purpose_type="event",
                            base_area={"id": "ChIJec", "name": "Electronic City", "latitude": BASE[0], "longitude": BASE[1]})
without = SimpleNamespace(id="t_plain", title="Bengaluru", destination=DEST)
old_row = SimpleNamespace(id="t_old", title="Bengaluru", destination=DEST, base_area=None, purpose_type=None)

print("\n== with a base area: distance from the base area, 15 km")
st = run(with_area)
check("a stop 5 km from the base area -> verified", st.get((0, 0)) == "verified", st)
check("a stop 20 km from the base area -> far (the day median would not flag it)", st.get((0, 1)) == "far", st)
check("a day with one found stop is checked too (1.5 km -> verified)", st.get((1, 0)) == "verified", st)
check("58 km and 125 km from the base area -> far", st.get((2, 1)) == "far" and st.get((2, 2)) == "far", st)
check("1.5 km on a day with far stops -> verified", st.get((2, 0)) == "verified", st)
check("the radius is the one constant", TP.BASE_AREA_RADIUS_KM == 15.0)

print("\n== without a base area: the day-median rule as before")
for label, trip in (("no base_area attribute", without), ("base_area None (old row)", old_row)):
    st = run(trip)
    check(f"[{label}] two stops 20 km apart -> both verified (median rule)", st.get((0, 0)) == "verified"
          and st.get((0, 1)) == "verified", st)
    check(f"[{label}] a single stop on a day -> verified, never compared", st.get((1, 0)) == "verified", st)
    check(f"[{label}] day 3's median is the dhaba: Nandi Hills (~57 km) and Mysore (~125 km) -> far, the dhaba verified",
          st.get((2, 2)) == "far" and st.get((2, 1)) == "far" and st.get((2, 0)) == "verified", st)

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
