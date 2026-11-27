"""
Place verification checks (backend/place_verify.py). Google is always simulated (a fake search_fn); the app DB is
a throwaway SQLite file; the AI is a fixed Kochi itinerary. Run from backend/: python -m tests.test_place_verify

all found; some not found; a ~140 km outlier flagged "far" (the Kairali / Palakkad case); a day with fewer than 2
found stops skips the check; TRANSIT and generic items skipped; the 20-call cap; quota error / exception / time
limit leave the trip READY with unverified activities and nothing deleted; only place_id + coordinates stored;
a plan-card trip never runs this step; the API returns the optional fields and an old row still serialises.
"""
import io
import json
import os
import sys
import tempfile
import threading
import time
import uuid
from contextlib import redirect_stdout
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
SCRATCH = tempfile.mkdtemp(prefix="voyageai_verify_")

from sqlalchemy import create_engine, inspect  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

import database  # noqa: E402

database.engine = create_engine(f"sqlite:///{os.path.join(SCRATCH, 'verify.db')}", connect_args={"check_same_thread": False})
database.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=database.engine)

import main  # noqa: E402
import itinerary_service  # noqa: E402
import place_verify as PV  # noqa: E402
import plan_card_itinerary as PCI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from models_itinerary import ItineraryActivityModel, ItineraryDayModel, ItineraryModel  # noqa: E402
from models_trip import TripModel  # noqa: E402
from redis_client import redis_conn  # noqa: E402
from schemas_itinerary import GeneratedItinerarySchema  # noqa: E402
from services.google_maps_service import GoogleQuotaError  # noqa: E402
from trip_lifecycle import today_ist  # noqa: E402

main.SessionLocal = database.SessionLocal
database.Base.metadata.create_all(bind=database.engine)
for key in redis_conn.scan_iter("rl:*"):
    redis_conn.delete(key)

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail != "" else ""), flush=True)


KOCHI = (9.9312, 76.2673)
START = (today_ist() + timedelta(days=20)).isoformat()


def act(time_slot, title, loc, lat=9.95, lng=76.26, kind="SIGHTSEEING", cost=500):
    return {"timeSlot": time_slot, "title": title, "description": f"About {title}", "activityType": kind,
            "locationName": loc, "latitude": lat, "longitude": lng, "estimatedCostInr": cost}


# Day 1: three Kochi stops. Day 2: Fort Kochi + the Kairali spa (~140 km away in the fake Google) + airport departure.
# Day 3: one found stop and one Google doesn't know (fewer than 2 found: no distance check).
PLAN = {"title": "Kochi", "days": [
    {"dayNumber": 1, "date": START, "title": "Kochi", "summary": "s", "activities": [
        act("09:00 AM", "Fort Kochi walk", "Fort Kochi Beach", 9.9658, 76.2421),
        act("12:00 PM", "Lunch at Kashi Art Cafe", "Kashi Art Cafe", 9.9667, 76.2425, "DINING", 800),
        act("04:00 PM", "Mattancherry Palace", "Mattancherry Palace", 9.9580, 76.2595),
    ]},
    {"dayNumber": 2, "date": START, "title": "Spa day", "summary": "s", "activities": [
        act("09:00 AM", "Chinese fishing nets", "Chinese Fishing Nets", 9.9680, 76.2420),
        act("01:00 PM", "Ayurvedic spa in Kochi", "Kairali Ayurvedic Healing Village, Palakkad Road", 9.98, 76.30, "RELAXATION", 4000),
        act("03:00 PM", "Jew Town shopping", "Jew Town", 9.9576, 76.2597),
        act("07:00 PM", "Departure", "Cochin International Airport", 10.152, 76.401, "TRANSIT", 0),
    ]},
    {"dayNumber": 3, "date": START, "title": "Last day", "summary": "s", "activities": [
        act("10:00 AM", "Marine Drive walk", "Marine Drive", 9.9779, 76.2760),
        act("02:00 PM", "Imaginary Museum", "Zzyzx Imaginary Museum", 9.99, 76.28),
    ]},
]}

# What the fake Google knows: venue -> (name Google returns, lat, lng). Kairali ~140 km from Kochi.
GOOGLE = {
    "fort kochi beach": ("Fort Kochi Beach", 9.9650, 76.2410),
    "kashi art cafe": ("Kashi Art Cafe", 9.9665, 76.2428),
    "mattancherry palace": ("Mattancherry Palace Museum", 9.9585, 76.2590),
    "chinese fishing nets": ("Chinese Fishing Nets", 9.9683, 76.2418),
    "kairali ayurvedic healing village, palakkad road": ("Kairali - The Ayurvedic Healing Village", 11.02, 76.93),
    "jew town": ("Jew Town", 9.9575, 76.2600),
    "marine drive": ("Marine Drive", 9.9780, 76.2765),
}


class FakeGoogle:
    def __init__(self, fail_after=None, error=None, delay=0.0):
        self.queries, self.fail_after, self.error, self.delay = [], fail_after, error, delay
        self._lock = threading.Lock()

    def __call__(self, query):
        with self._lock:
            self.queries.append(query)
            n = len(self.queries)
        if self.delay:
            time.sleep(self.delay)
        if self.error is not None and (self.fail_after is None or n > self.fail_after):
            raise self.error
        venue = query[: -len(" Kochi")].lower() if query.endswith(" Kochi") else query.lower()
        hit = GOOGLE.get(venue)
        if hit is None and venue.startswith("venue "):
            hit = (venue.title(), KOCHI[0] + 0.001 * int(venue.split()[1]), KOCHI[1])
        if hit is None:
            return SimpleNamespace(results=[], unavailable=False, ambiguous=False)
        name, lat, lng = hit
        return SimpleNamespace(results=[{"place_id": f"ChIJ_{abs(hash(name)) % 10**8}", "name": name, "latitude": lat,
                                         "longitude": lng, "rating": 4.9, "photos": ["p1"], "address": "GOOGLE ADDRESS"}],
                               unavailable=False, ambiguous=False)


TRIP = SimpleNamespace(id="trip_unit", title="Kochi", destination={"name": "Kochi", "latitude": KOCHI[0], "longitude": KOCHI[1]})


def schema(plan=PLAN):
    return GeneratedItinerarySchema.model_validate(json.loads(json.dumps(plan)))


def run(plan=PLAN, google=None, **kw):
    buf = io.StringIO()
    s = schema(plan)
    with redirect_stdout(buf):
        out = PV.verify_itinerary(s, TRIP, google or FakeGoogle(), **kw)
    return s, out, buf.getvalue()


# ---------------- unit: statuses
g = FakeGoogle()
s, out, log = run(google=g)
st = {(d, a): r["status"] for (d, a), r in out.items()}
check("all known venues found; the Kairali stop ~140 km away -> 'far'", st == {
    (0, 0): "verified", (0, 1): "verified", (0, 2): "verified", (1, 0): "verified", (1, 1): "far", (1, 2): "verified",
    (2, 0): "verified", (2, 1): "not_found"}, st)
check("TRANSIT (airport departure) skipped: never looked up, no status", (1, 3) not in out
      and not any("Airport" in q for q in g.queries), g.queries)
check("day 3: one found + one not found -> fewer than 2 found, no distance check", st[(2, 0)] == "verified")
check("the query is locationName + the destination", "Kashi Art Cafe Kochi" in g.queries and len(g.queries) == 8, g.queries)
r = out[(0, 0)]
check("found: Google's place_id and coordinates; nothing else kept", set(r) == {"status", "place_id", "latitude", "longitude"}
      and r["place_id"].startswith("ChIJ_") and (r["latitude"], r["longitude"]) == (9.9650, 76.2410), r)
check("not found: no place_id, no coordinates", out[(2, 1)] == {"status": "not_found", "place_id": None, "latitude": None, "longitude": None})
check("the schema itself is not changed (the itinerary cache keeps the model's plan)",
      s.days[0].activities[0].latitude == 9.9658 and s.days[1].activities[1].locationName.startswith("Kairali"))
check("log: one line, counts only", log.strip().count("\n") == 0 and log.startswith("[PLACE VERIFY] trip=trip_unit activities=9 verified=6 not_found=1 far=1 google_calls=8 ms=")
      and "Kairali" not in log and "Kochi" not in log, log)

# all found / some not found
plan_ok = json.loads(json.dumps(PLAN))
plan_ok["days"] = plan_ok["days"][:1]
_, out_ok, _ = run(plan_ok)
check("all found -> all verified", sorted(r["status"] for r in out_ok.values()) == ["verified"] * 3)
plan_some = json.loads(json.dumps(PLAN))
plan_some["days"][0]["activities"][2]["locationName"] = "Nowhere Hall"
_, out_some, _ = run(plan_some)
check("some not found -> those not_found, the rest verified", out_some[(0, 2)]["status"] == "not_found"
      and out_some[(0, 0)]["status"] == out_some[(0, 1)]["status"] == "verified")
plan_two = {"title": "x", "days": [{"dayNumber": 1, "date": START, "title": "d", "summary": "s", "activities": [
    act("09:00 AM", "Spa", "Kairali Ayurvedic Healing Village, Palakkad Road"), act("11:00 AM", "Museum", "Zzyzx Imaginary Museum")]}]}
_, out_two, _ = run(plan_two)
check("a day with 1 found stop far away: no distance check (stays verified)", out_two[(0, 0)]["status"] == "verified"
      and out_two[(0, 1)]["status"] == "not_found")

# generic items
for title, loc, kind, looked in (("Departure", "Kochi Airport", "SIGHTSEEING", False), ("Free time", "Free time", "RELAXATION", False),
                                 ("Check-in at hotel", "Hotel", "RELAXATION", False), ("Check-in", "Taj Malabar Resort", "RELAXATION", True)):
    a_ = SimpleNamespace(activityType=kind, locationName=loc, title=title)
    check(f"generic: {title!r} / {loc!r} -> {'looked up' if looked else 'skipped'}", (PV.venue_of(a_, "Kochi") is not None) == looked)

# the 20-call cap
many = {"title": "x", "days": [{"dayNumber": 1, "date": START, "title": "d", "summary": "s", "activities": [
    act(f"{8 + i // 4:02d}:{(i % 4) * 15:02d} AM" if 8 + i // 4 < 12 else f"{8 + i // 4 - 12 or 12:02d}:{(i % 4) * 15:02d} PM",
        f"Stop {i}", f"Venue {i}", 9.9 + i / 1000, 76.2) for i in range(30)]}]}
gc = FakeGoogle()
_, out_c, log_c = run(many, gc)
check("cap: at most 20 Google calls per trip; the rest stay unverified", len(gc.queries) == 20 and len(out_c) == 20
      and "google_calls=20" in log_c and "stopped=cap" in log_c, (len(gc.queries), len(out_c)))
trip_nocoords = SimpleNamespace(id="t", title="Kochi", destination={"name": "Kochi"})
gn = FakeGoogle()
with redirect_stdout(io.StringIO()):
    PV.verify_itinerary(schema(many), trip_nocoords, gn)
check("cap: the destination look-up (no coordinates) counts too", len(gn.queries) == 20, len(gn.queries))

# quota / exception / time limit
gq = FakeGoogle(fail_after=0, error=GoogleQuotaError("quota"))
_, out_q, log_q = run(google=gq)
check("quota error -> nothing verified, nothing stored, logged", out_q == {} and "stopped=error:GoogleQuotaError" in log_q, log_q)
gq2 = FakeGoogle(fail_after=2, error=GoogleQuotaError("quota"))
_, out_q2, _ = run(many, gq2)
check("quota error after 2 calls -> the remaining stay unverified (no not_found for them)", len(out_q2) <= 4 + 2
      and all(r["status"] == "verified" for r in out_q2.values()) and len(gq2.queries) < 12, (len(out_q2), len(gq2.queries)))
_, out_u, log_u = run(google=lambda q: SimpleNamespace(results=[], unavailable=True, ambiguous=False))
check("paused / unavailable -> unverified", out_u == {} and "stopped=unavailable" in log_u, log_u)
_, out_e, log_e = run(google=FakeGoogle(error=RuntimeError("boom")))
check("an exception in a look-up -> unverified", out_e == {} and "stopped=error:RuntimeError" in log_e and "boom" not in log_e, log_e)
with mock.patch.object(PCI, "_km", side_effect=ValueError("x")):
    _, out_k, log_k = run()
check("an exception in the step itself -> everything unverified (nothing half-done)", out_k == {} and "stopped=error:ValueError" in log_k, log_k)
t0 = time.perf_counter()
_, out_t, log_t = run(google=FakeGoogle(delay=1.0), time_limit_s=0.3)
took = time.perf_counter() - t0
check("time limit: the step returns on time and the slow look-ups stay unverified", took < 0.9 and out_t == {}
      and "stopped=time_limit" in log_t, (round(took, 2), log_t))

# ---------------- the worker pipeline (SQLite)
NOW = datetime.now(timezone.utc).isoformat()
client = TestClient(main.app)
client.__enter__()
reg = client.post("/api/auth/register", json={"name": "Verify T", "email": f"pv_{uuid.uuid4().hex[:6]}@example.com", "password": "secret123"})
TOKEN, UID = reg.json()["token"], reg.json()["user"]["id"]
client.cookies.clear()
H = {"Authorization": f"Bearer {TOKEN}"}


def make_trip(days=3, snap=None):
    tid = f"trip_pv_{uuid.uuid4().hex[:8]}"
    end = (datetime.fromisoformat(START) + timedelta(days=days - 1)).date().isoformat()
    with database.SessionLocal() as db:
        db.add(TripModel(id=tid, user_id=UID, title="Kochi", status="PLANNING", start_date=START, end_date=end, total_days=days,
                         destination={"name": "Kochi", "latitude": KOCHI[0], "longitude": KOCHI[1]},
                         travelers=[{"type": "ADULT"}], budget={"targetAmount": 50000}, preferences_snapshot=snap or {},
                         created_at=NOW, updated_at=NOW, itinerary_status="GENERATING"))
        db.commit()
    return tid


def generate(tid, google, verify=None):
    patches = [mock.patch.object(itinerary_service, "get_cached_itinerary", lambda k: None),
               mock.patch.object(itinerary_service, "set_cached_itinerary", lambda *a, **k: None),
               mock.patch.object(itinerary_service.ai_provider_service, "generate_itinerary_json", lambda i, p: json.dumps(PLAN)),
               mock.patch.object(PCI, "_default_search", google),
               mock.patch.object(PV, "should_verify", lambda provider: True)]   # the fixed plan stands in for real AI
    if verify is not None:
        patches.append(mock.patch.object(PV, "verify_itinerary", verify))
    buf = io.StringIO()
    for p in patches:
        p.start()
    try:
        with redirect_stdout(buf):
            status = itinerary_service.process_async_itinerary_generation(tid, database.SessionLocal)
    finally:
        for p in reversed(patches):
            p.stop()
    return status, buf.getvalue()


def rows(tid):
    with database.SessionLocal() as db:
        it = db.query(ItineraryModel).filter(ItineraryModel.trip_id == tid).first()
        days = db.query(ItineraryDayModel).filter(ItineraryDayModel.itinerary_id == it.id).order_by(ItineraryDayModel.day_number).all()
        out = []
        for d in days:
            acts = db.query(ItineraryActivityModel).filter(ItineraryActivityModel.day_id == d.id).all()
            out += [(d.day_number, a) for a in sorted(acts, key=lambda a: itinerary_service.parse_time_to_minutes(a.time_slot))]
        return out


def trip_status(tid):
    with database.SessionLocal() as db:
        return db.query(TripModel).filter(TripModel.id == tid).first().itinerary_status


T1 = make_trip()
status, log = generate(T1, FakeGoogle())
rs = rows(T1)
by = {a.location_name: a for _, a in rs}
check("pipeline: trip READY, every activity saved", status == "READY" and trip_status(T1) == "READY" and len(rs) == 9, (status, len(rs)))
check("pipeline: statuses stored", [a.verify_status for _, a in rs] == ["verified", "verified", "verified", "verified", "far", "verified",
      None, "verified", "not_found"], [a.verify_status for _, a in rs])
k = by["Kairali Ayurvedic Healing Village, Palakkad Road"]
check("pipeline: the Kairali stop is 'far' with Google's place_id and coordinates", k.verify_status == "far" and k.place_id.startswith("ChIJ_")
      and (k.latitude, k.longitude) == (11.02, 76.93))
f = by["Fort Kochi Beach"]
check("pipeline: a verified stop gets Google's coordinates", (f.latitude, f.longitude) == (9.9650, 76.2410) and f.place_id)
z = by["Zzyzx Imaginary Museum"]
check("pipeline: not found keeps the model's coordinates, no place_id", (z.latitude, z.longitude) == (9.99, 76.28) and z.place_id is None)
air = by["Cochin International Airport"]
check("pipeline: TRANSIT untouched (no status, model's coordinates)", air.verify_status is None and air.place_id is None
      and (air.latitude, air.longitude) == (10.152, 76.401))
check("pipeline: titles, descriptions, times and costs never change", [(a.title, a.description, a.time_slot, a.estimated_cost_inr) for _, a in rs] == [
    (x["title"], x["description"], x["timeSlot"], x["estimatedCostInr"]) for d in PLAN["days"]
    for x in sorted(d["activities"], key=lambda x: itinerary_service.parse_time_to_minutes(x["timeSlot"]))])
check("pipeline: no Google content stored (name / address / rating / photos)", all(
    "GOOGLE" not in str(v) and "The Ayurvedic Healing Village" not in str(v)
    for _, a in rs for v in (a.title, a.description, a.location_name)))
cols = {c["name"] for c in inspect(database.engine).get_columns("itinerary_activities")}
check("model: only place_id and verify_status added for this (no rating / photo / name columns)",
      {"place_id", "verify_status"} <= cols and not any(w in c for c in cols for w in ("rating", "photo", "google")), sorted(cols))
check("pipeline: one [PLACE VERIFY] line", log.count("[PLACE VERIFY]") == 1 and f"trip={T1} activities=9 verified=6 not_found=1 far=1" in log, log)

T2 = make_trip()
status, log = generate(T2, FakeGoogle(error=GoogleQuotaError("quota")))
rs2 = rows(T2)
check("quota: trip READY, all 9 activities saved, none verified, model's coordinates kept", status == "READY" and len(rs2) == 9
      and all(a.verify_status is None and a.place_id is None for _, a in rs2)
      and {a.location_name: (a.latitude, a.longitude) for _, a in rs2}["Fort Kochi Beach"] == (9.9658, 76.2421), status)
T3 = make_trip()
status, log = generate(T3, FakeGoogle(), verify=mock.Mock(side_effect=RuntimeError("verify broke")))
rs3 = rows(T3)
check("an exception from the whole step: trip READY, nothing deleted, unverified, one log line with the class only",
      status == "READY" and len(rs3) == 9 and all(a.verify_status is None for _, a in rs3)
      and "[PLACE VERIFY] trip=" in log and "error=RuntimeError" in log and "verify broke" not in log, log[-300:])

# a MOCK itinerary (AI_PROVIDER=mock) is never sent to Google
check("mock AI output is never verified", PV.should_verify("MOCK") is False and PV.should_verify("OPENAI") and PV.should_verify("CACHED"))

# plan-card trip: never this step
T4 = make_trip(snap={"planCard": {"id": "kashi-vishwanath"}})
spy = mock.Mock(return_value={})
import pilgrimage  # noqa: E402
with mock.patch.object(pilgrimage, "get_card", lambda cid: SimpleNamespace(id=cid)), \
        mock.patch("plan_card_itinerary.generate", lambda trip, db, card: "READY"):
    status, _ = generate(T4, FakeGoogle(), verify=spy)
check("plan-card trip: built by plan_card_itinerary, place_verify never called", status == "READY" and not spy.called)

# ---------------- API: optional fields; an old row (NULL) still serialises
g1 = client.get(f"/api/trips/{T1}/itinerary", headers=H)
acts = [a for d in g1.json().get("days", []) for a in d["activities"]]
kai = next(a for a in acts if a["locationName"].startswith("Kairali"))
check("API: placeId + verifyStatus on each activity", g1.status_code == 200 and kai["verifyStatus"] == "far" and kai["placeId"].startswith("ChIJ_")
      and all("verifyStatus" in a and "placeId" in a for a in acts), g1.status_code)
with database.SessionLocal() as db:
    db.query(ItineraryActivityModel).update({ItineraryActivityModel.place_id: None, ItineraryActivityModel.verify_status: None},
                                            synchronize_session=False)
    db.commit()
for path in (f"/api/trips/{T1}/itinerary", f"/api/trips/{T1}"):
    gr = client.get(path, headers=H)
    check(f"API: an old row (NULL fields) still serialises ({path})", gr.status_code == 200, gr.status_code)
olds = [a for d in client.get(f"/api/trips/{T1}/itinerary", headers=H).json()["days"] for a in d["activities"]]
check("API: NULL -> verifyStatus null (no label)", all(a["verifyStatus"] is None and a["placeId"] is None for a in olds))

client.__exit__(None, None, None)
print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
