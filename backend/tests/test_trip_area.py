"""
Adding a place outside the trip's area is refused (trip_area.py, POST /api/trips/itinerary/add).
SQLite + local Redis, no AI, no Google. Run from backend/: python -m tests.test_trip_area
"""
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import dotenv

dotenv.load_dotenv = lambda *a, **k: None
os.environ["DATABASE_URL"] = "postgresql://x:y@127.0.0.1:1/none"
os.environ["AI_PROVIDER"] = "mock"
os.environ.pop("TRIP_AREA_RADIUS_KM", None)
from pathlib import Path
import tempfile

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)
SCRATCH = tempfile.mkdtemp(prefix="voyageai_test_")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import database

database.engine = create_engine(f"sqlite:///{os.path.join(SCRATCH, 'app.db')}", connect_args={"check_same_thread": False})
database.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=database.engine)

import main  # noqa: E402
import trip_area  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from models_itinerary import ItineraryActivityModel, ItineraryDayModel, ItineraryModel  # noqa: E402
from models_trip import TripModel  # noqa: E402
from redis_client import redis_conn  # noqa: E402

main.SessionLocal = database.SessionLocal
database.Base.metadata.create_all(bind=database.engine)
for key in redis_conn.scan_iter("rl:*"):
    redis_conn.delete(key)

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail != "" else ""))


class Catch(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append((record.levelname, record.getMessage()))


caught = Catch()
trip_area.log.addHandler(caught)

GOA = {"name": "Goa", "latitude": 15.2993, "longitude": 74.1240}
PANAJI, BIHAR = (15.4989, 73.8278), (26.3537, 86.0718)


def north(km):
    return 15.2993 + km / 111.195, 74.1240


def refused(dest, place):
    try:
        trip_area.require_place_in_trip_area(SimpleNamespace(id="t", destination=dest), *place)
        return False
    except trip_area.PlaceOutsideTripArea:
        return True


# ---- the rule
check("default radius is 60 km", trip_area.trip_area_radius_km() == 60)
check("Panaji on a Goa trip: allowed", not refused(GOA, PANAJI))
check("Bihar on a Goa trip: refused", refused(GOA, BIHAR))
check("edge: 59.9 km allowed, 60.1 km refused", not refused(GOA, north(59.9)) and refused(GOA, north(60.1)))
check("no warnings for normal checks", caught.lines == [], caught.lines)
check("destination without coordinates: no guard", not refused({"name": "Goa"}, BIHAR) and not refused({}, BIHAR)
      and not refused(None, BIHAR) and not refused({"name": "Goa", "latitude": 0, "longitude": 0}, BIHAR))
check("... with a warning each time", len(caught.lines) == 4 and all(lv == "WARNING" for lv, _ in caught.lines), caught.lines)
check("place without usable coordinates: nothing to compare, allowed",
      not any(refused(GOA, p) for p in [(None, None), (15.3, None), (float("nan"), 74.1), (0, 0)]))
os.environ["TRIP_AREA_RADIUS_KM"] = "10"
check("TRIP_AREA_RADIUS_KM=10 refuses Panaji", refused(GOA, PANAJI))
for bad in ("junk", "-5", "0", "nan", ""):
    os.environ["TRIP_AREA_RADIUS_KM"] = bad
    if trip_area.trip_area_radius_km() != 60:
        check(f"bad TRIP_AREA_RADIUS_KM={bad!r} -> 60", False)
check("bad TRIP_AREA_RADIUS_KM values fall back to 60", trip_area.trip_area_radius_km() == 60)
os.environ.pop("TRIP_AREA_RADIUS_KM", None)

# ---- POST /api/trips/itinerary/add
client = TestClient(main.app)
client.__enter__()


def register(name, email):
    r = client.post("/api/auth/register", json={"name": name, "email": email, "password": "secret123"})
    assert r.status_code == 200, r.text
    client.cookies.clear()
    return r.json()["token"], r.json()["user"]["id"]


tok, uid = register("Asha Tester", "area-a@example.com")
tok_b, _ = register("Bilal Tester", "area-b@example.com")
now = datetime.now(timezone.utc)
with database.SessionLocal() as db:
    for tid, dest in (("trip_area_goa", GOA), ("trip_area_nocoords", {"name": "Goa"})):
        db.add(TripModel(id=tid, user_id=uid, title="Goa", status="PLANNING", total_days=3,
                         start_date=(now + timedelta(days=5)).date().isoformat(), end_date=(now + timedelta(days=7)).date().isoformat(),
                         destination=dest, travelers=[], budget={}, created_at=now.isoformat(), updated_at=now.isoformat()))
    db.commit()


def add(trip_id, title, coords=None, token=tok):
    body = {"trip_id": trip_id, "title": title, "day_number": 1, "item_id": f"test_{title}"}
    if coords:
        body.update(latitude=coords[0], longitude=coords[1])
    return client.post("/api/trips/itinerary/add", json=body, headers={"Authorization": f"Bearer {token}"})


def saved(title):
    with database.SessionLocal() as db:
        return db.query(ItineraryActivityModel).filter(ItineraryActivityModel.title == title).count()


try:
    r = add("trip_area_goa", "Bihar Temple", BIHAR)
    check("add: Bihar place refused with place_outside_trip_area", r.status_code == 422 and r.json().get("error_code") == "place_outside_trip_area",
          f"{r.status_code} {r.text[:120]}")
    check("add: the message", r.json().get("detail") == "Yeh jagah aapke Goa trip ke area ke bahar hai.", r.json().get("detail"))
    check("add: nothing written (DB, Redis)", saved("Bihar Temple") == 0 and not redis_conn.exists("trip:trip_area_goa:day:1"))
    r = add("trip_area_goa", "Panaji Church", PANAJI)
    check("add: Panaji place accepted and saved", r.status_code == 200 and saved("Panaji Church") == 1, f"{r.status_code} {r.text[:120]}")
    caught.lines.clear()
    r = add("trip_area_nocoords", "Far Temple", BIHAR)
    check("add: destination without coordinates -> no guard, saved, warning logged",
          r.status_code == 200 and saved("Far Temple") == 1 and any("trip_area_nocoords" in m for _, m in caught.lines), f"{r.status_code} {caught.lines}")
    r = add("trip_area_goa", "No Coords Place")
    check("add: older client without coordinates still works", r.status_code == 200 and saved("No Coords Place") == 1, r.status_code)
    r = add("trip_area_goa", "Other User", BIHAR, tok_b)
    check("add: another user's trip is 404 first (no destination name leaked)", r.status_code == 404 and "Goa" not in r.text, f"{r.status_code} {r.text[:80]}")

    # ---- swaps, edits and AI replacements follow the same rule
    with database.SessionLocal() as db:
        day = (db.query(ItineraryDayModel).join(ItineraryModel, ItineraryModel.id == ItineraryDayModel.itinerary_id)
               .filter(ItineraryModel.trip_id == "trip_area_goa").first())
        db.add(ItineraryActivityModel(id="act_area_x", day_id=day.id, time_slot="10:00 AM", title="Old Fort", latitude=15.49, longitude=73.77))
        # added before the rule existed: far away already
        db.add(ItineraryActivityModel(id="act_area_far", day_id=day.id, time_slot="11:00 AM", title="Legacy Far", latitude=BIHAR[0], longitude=BIHAR[1]))
        db.commit()
    auth = {"Authorization": f"Bearer {tok}"}
    far = {"name": "Far Swap", "title": "Far Swap", "latitude": BIHAR[0], "longitude": BIHAR[1]}
    near = {"name": "Near Swap", "title": "Near Swap", "latitude": PANAJI[0], "longitude": PANAJI[1]}

    def title_of(aid):
        with database.SessionLocal() as db:
            return db.query(ItineraryActivityModel).filter(ItineraryActivityModel.id == aid).first().title

    def is_refused(r):
        return r.status_code == 422 and r.json().get("error_code") == "place_outside_trip_area"

    base = "/api/trips/trip_area_goa"
    r = client.post("/api/trips/itinerary/swap-execute", headers=auth,
                    json={"trip_id": "trip_area_goa", "day_number": 1, "old_activity_id": "act_area_x", "new_activity": far})
    check("swap-execute: outside refused, unchanged", is_refused(r) and title_of("act_area_x") == "Old Fort", f"{r.status_code} {r.text[:100]}")
    r = client.post("/api/trips/itinerary/swap", headers=auth, json={"trip_id": "trip_area_goa", "activity_id": "act_area_x", "replacement": far})
    check("concierge swap: outside refused, unchanged", is_refused(r) and title_of("act_area_x") == "Old Fort", f"{r.status_code} {r.text[:100]}")
    r = client.patch(f"{base}/itinerary/activities/act_area_x", headers=auth, json={"replacement": far})
    check("PATCH replacement: outside refused, unchanged", is_refused(r) and title_of("act_area_x") == "Old Fort", f"{r.status_code} {r.text[:100]}")
    r = client.patch(f"{base}/itinerary/activities/act_area_x", headers=auth, json={"title": "Moved", "latitude": BIHAR[0], "longitude": BIHAR[1]})
    check("PATCH coordinates: outside refused, unchanged", is_refused(r) and title_of("act_area_x") == "Old Fort", f"{r.status_code} {r.text[:100]}")
    refine = [{"type": "REPLACE_ACTIVITY", "activityId": "act_area_x", "replacement": near},
              {"type": "REPLACE_ACTIVITY", "activityId": "act_area_far", "replacement": {**far, "latitude": 26.9, "longitude": 85.0}}]
    r = client.post(f"{base}/itinerary/refine", headers=auth, json={"actions": refine})
    check("refine: one outside replacement refuses the whole batch", is_refused(r) and title_of("act_area_x") == "Old Fort", f"{r.status_code} {r.text[:100]}")

    def ws(action, payload):
        with client.websocket_connect("/ws/app") as sock:
            sock.send_json({"id": "q", "action": action, "payload": {"token": tok, **payload}})
            while True:
                fr = sock.receive_json()
                if fr.get("id") == "q":
                    return fr

    fr = ws("trips:swap_activity", {"trip_id": "trip_area_goa", "activity_id": "act_area_x", "replacement": far})
    check("WS swap: outside refused with code and message", fr["status"] == 422 and fr.get("error_code") == "place_outside_trip_area"
          and fr["error"] == "Yeh jagah aapke Goa trip ke area ke bahar hai." and title_of("act_area_x") == "Old Fort", fr)
    fr = ws("trips:refine", {"trip_id": "trip_area_goa", "actions": refine})
    check("WS refine: outside refused", fr["status"] == 422 and title_of("act_area_x") == "Old Fort", fr)
    r = client.patch(f"{base}/itinerary/activities/act_area_far", headers=auth, json={"title": "Legacy Renamed", "latitude": BIHAR[0], "longitude": BIHAR[1]})
    check("an activity already far away can still be edited (not moved)", r.status_code == 200 and title_of("act_area_far") == "Legacy Renamed", f"{r.status_code} {r.text[:100]}")
    fr = ws("trips:swap_activity", {"trip_id": "trip_area_goa", "activity_id": "act_area_x", "replacement": near})
    check("WS swap: inside accepted", fr["status"] == 200 and title_of("act_area_x") == "Near Swap", fr)

    from voice.tools import smart
    pend = {"tool": "weather_replan", "data": {"trip_id": "trip_area_goa", "day_number": 1,
            "actions": [{"type": "REPLACE_ACTIVITY", "activityId": "act_area_x", "activityTitle": "Near Swap", "replacement": far}]}}
    with database.SessionLocal() as db:
        res = smart.apply_confirmed(pend, uid, "hi", db=db)
    check("voice replan 'haan': refused with the spoken message, unchanged",
          "Yeh jagah aapke Goa trip ke area ke bahar hai." in str(res) and "place_outside_trip_area" in str(res) and title_of("act_area_x") == "Near Swap", str(res)[:200])
finally:
    for tid in ("trip_area_goa", "trip_area_nocoords"):
        for k in (f"trip:itinerary:{tid}", f"trip:{tid}:day:1", f"trip:{tid}"):
            redis_conn.delete(k)
    client.__exit__(None, None, None)

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
