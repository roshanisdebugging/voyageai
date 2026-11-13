"""
0e backend checks (SQLite + local Redis): past trips are closed on read, by the India date;
/api/trips/itinerary/add needs login and never touches another user's trip.
Run from backend/: python -m tests.test_step0e
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest import mock

import dotenv

dotenv.load_dotenv = lambda *a, **k: None
os.environ["DATABASE_URL"] = "postgresql://x:y@127.0.0.1:1/none"
os.environ["AI_PROVIDER"] = "mock"
from pathlib import Path
import tempfile

# backend/ on the import path, so this runs as `python -m tests.<name>` or `python tests/<name>.py` from backend/.
BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)
SCRATCH = tempfile.mkdtemp(prefix="voyageai_test_")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import database

db_path = os.path.join(SCRATCH, "app.db")
if os.path.exists(db_path):
    os.remove(db_path)
database.engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
database.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=database.engine)

import main  # noqa: E402
import trip_lifecycle  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from models_trip import TripModel  # noqa: E402
from models_itinerary import ItineraryModel, ItineraryActivityModel  # noqa: E402
from redis_client import redis_conn  # noqa: E402

main.SessionLocal = database.SessionLocal
database.Base.metadata.create_all(bind=database.engine)
for key in redis_conn.scan_iter("rl:*"):
    redis_conn.delete(key)

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail != "" else ""))


client = TestClient(main.app)
client.__enter__()


def register(name, email):
    r = client.post("/api/auth/register", json={"name": name, "email": email, "password": "secret123"})
    assert r.status_code == 200, r.text
    return r.json()["token"], r.json()["user"]["id"]


tok_a, uid_a = register("Asha Tester", "asha0e@example.com")
tok_b, uid_b = register("Bilal Tester", "bilal0e@example.com")
client.cookies.clear()

IST = timezone(timedelta(hours=5, minutes=30))
today = datetime.now(IST).date()
d = lambda n: (today + timedelta(days=n)).isoformat()  # noqa: E731

# ---- trips straight into the DB (creation blocks past dates, so old trips are inserted directly)
rows = {
    "trip_ended_yesterday": ("PLANNING", d(-4), d(-1)),
    "trip_ends_today": ("PLANNING", d(-2), d(0)),
    "trip_upcoming": ("PLANNING", d(5), d(7)),
    "trip_old_cancelled": ("CANCELLED", d(-30), d(-28)),
    "trip_old_active": ("ACTIVE", d(-10), d(-8)),
}
with database.SessionLocal() as db:
    for tid, (status, start, end) in rows.items():
        db.add(TripModel(id=tid, user_id=uid_a, title=tid, status=status, start_date=start, end_date=end,
                         total_days=3, destination={"name": "Mumbai"}, travelers=[], budget={}, created_at=datetime.now(timezone.utc).isoformat(), updated_at=datetime.now(timezone.utc).isoformat()))
    db.commit()

auth = {"Authorization": f"Bearer {tok_a}"}

# ---- REST list closes past trips
r = client.get("/api/trips", headers=auth)
status = {t["id"]: t["status"] for t in r.json()}
check("REST /api/trips: ended yesterday -> COMPLETED", status.get("trip_ended_yesterday") == "COMPLETED", status.get("trip_ended_yesterday"))
check("REST: ends today stays open", status.get("trip_ends_today") == "PLANNING", status.get("trip_ends_today"))
check("REST: upcoming stays open", status.get("trip_upcoming") == "PLANNING")
check("REST: cancelled is left alone", status.get("trip_old_cancelled") == "CANCELLED")
check("REST: old ACTIVE -> COMPLETED", status.get("trip_old_active") == "COMPLETED")
with database.SessionLocal() as db:
    saved = db.query(TripModel).filter(TripModel.id == "trip_ended_yesterday").first().status
check("status is saved in the DB", saved == "COMPLETED", saved)

# ---- WS list and REST single get also close
with database.SessionLocal() as db:
    db.query(TripModel).filter(TripModel.id == "trip_ended_yesterday").first().status = "PLANNING"
    db.commit()
with client.websocket_connect("/ws/app") as ws:
    ws.send_json({"id": "x", "action": "trips:list", "payload": {"token": tok_a}})
    while True:
        f = ws.receive_json()
        if f.get("id") == "x":
            break
st = {t["id"]: t["status"] for t in f["data"]}
check("WS trips:list closes past trips", st.get("trip_ended_yesterday") == "COMPLETED", st.get("trip_ended_yesterday"))
with database.SessionLocal() as db:
    db.query(TripModel).filter(TripModel.id == "trip_ended_yesterday").first().status = "PLANNING"
    db.commit()
r = client.get("/api/trips/trip_ended_yesterday", headers=auth)
check("REST trip get closes it", r.status_code == 200 and r.json()["status"] == "COMPLETED", r.status_code)

# ---- "today" is the India date: at 23:30 UTC on day X it's already day X+1 in India
fake_now = datetime(2026, 11, 13, 23, 30, tzinfo=timezone.utc)
with mock.patch.object(trip_lifecycle, "datetime", wraps=datetime) as m:
    m.now.side_effect = lambda tz=None: fake_now.astimezone(tz) if tz else fake_now.replace(tzinfo=None)
    check("today_ist() uses the India date", trip_lifecycle.today_ist().isoformat() == "2026-11-14", trip_lifecycle.today_ist())

# ---- /api/trips/itinerary/add: guests refused; a user with no trips never reaches someone else's
body = {"title": "Hawa Mahal", "trip_id": "active_trip", "day_number": 1}
r = client.post("/api/trips/itinerary/add", json=body)
check("add to itinerary: guest refused (401)", r.status_code == 401, r.status_code)
with database.SessionLocal() as db:
    before = db.query(ItineraryActivityModel).count()
r = client.post("/api/trips/itinerary/add", json=body, headers={"Authorization": f"Bearer {tok_b}"})
with database.SessionLocal() as db:
    after = db.query(ItineraryActivityModel).count()
check("add to itinerary: user with no trips gets 404, nothing written", r.status_code == 404 and after == before, f"{r.status_code}, {before}->{after}")
r = client.post("/api/trips/itinerary/add", json={**body, "trip_id": "trip_upcoming"}, headers={"Authorization": f"Bearer {tok_b}"})
check("add to itinerary: B naming A's trip gets 404", r.status_code == 404, r.status_code)
r = client.post("/api/trips/itinerary/add", json={**body, "trip_id": "trip_upcoming"}, headers=auth)
check("add to itinerary: owner still works", r.status_code == 200, f"{r.status_code} {r.text[:120]}")

client.__exit__(None, None, None)
print(f"\n{sum(results)}/{len(results)} passed")
