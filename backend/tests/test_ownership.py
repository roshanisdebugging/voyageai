"""
Two-user ownership smoke test against a throwaway SQLite database.
Run from backend/: python -m tests.test_ownership
Uses the local Redis for rate limits and the job queue; queued test jobs are removed at the end.
"""
import os
import sys

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
from fastapi.testclient import TestClient  # noqa: E402
from redis_client import redis_conn  # noqa: E402
from task_queue import TASK_QUEUE_KEY  # noqa: E402

main.SessionLocal = database.SessionLocal
database.Base.metadata.create_all(bind=database.engine)
for key in redis_conn.scan_iter("rl:*"):
    redis_conn.delete(key)

client = TestClient(main.app)
client.__enter__()  # one event loop for the whole run, like uvicorn
results = []


def check(name, cond):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)


def register(name, email):
    r = client.post("/api/auth/register", json={"name": name, "email": email, "password": "secret123"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


tok_a = register("Asha Tester", "asha@example.com")
tok_b = register("Bilal Tester", "bilal@example.com")
client.cookies.clear()

# Login rules
r = client.post("/api/auth/login", json={"email": "asha@example.com"})
check("login without password is rejected", r.status_code == 400)
r = client.post("/api/auth/login", json={"email": "asha@example.com", "password": "wrong"})
check("login with wrong password is rejected", r.status_code == 400)
r = client.post("/api/auth/login", json={"email": "new@example.com", "password": "x", "isRegister": True})
check("login can no longer create accounts", r.status_code == 400)
r = client.post("/api/auth/login", json={"email": "asha@example.com", "password": "secret123"})
check("login with correct password works", r.status_code == 200 and r.json().get("token"))
client.cookies.clear()

trip_payload = {
    "destination": {"name": "Jaipur", "country": "India", "latitude": 26.9124, "longitude": 75.7873},
    "startDate": "2027-01-10",
    "endDate": "2027-01-12",
    "travelersCount": 2,
}

with client.websocket_connect("/ws/app") as ws_a, client.websocket_connect("/ws/app") as ws_b:
    def call(ws, action, payload, token):
        ws.send_json({"id": "x", "action": action, "payload": {**payload, "token": token}})
        while True:
            frame = ws.receive_json()
            if frame.get("id") == "x":
                return frame

    f = call(ws_a, "trips:create", trip_payload, tok_a)
    check("user A creates a trip over WS", f["status"] == 200)
    trip_id = f["data"]["id"]

    f = call(ws_a, "trips:create", {**trip_payload, "travelersCount": 100000}, tok_a)
    check("absurd traveler count is rejected", f["status"] == 400)
    f = call(ws_a, "trips:create", {**trip_payload, "endDate": "2027-06-30"}, tok_a)
    check("trip longer than 30 days is rejected", f["status"] == 400)

    f = call(ws_b, "trips:get_itinerary", {"trip_id": trip_id}, tok_b)
    check("user B cannot read A's itinerary (WS)", f["status"] == 404)
    f = call(ws_b, "trips:add_expense", {"trip_id": trip_id, "title": "x", "amount": 1}, tok_b)
    check("user B cannot add expense to A's trip (WS)", f["status"] == 404)
    f = call(ws_b, "trips:delete", {"trip_id": trip_id}, tok_b)
    check("user B cannot delete A's trip (WS)", f["status"] == 404)
    f = call(ws_b, "trips:list", {}, tok_b)
    check("user B's trip list is empty", f["status"] == 200 and f["data"] == [])

    f = call(ws_a, "trips:get_stays", {"trip_id": trip_id}, tok_a)
    check("user A can read own trip stays (WS)", f["status"] == 200)

    owner_conns = [c for c, u in main.connection_registry.connection_users.items() if u]
    users = set(main.connection_registry.connection_users.values())
    check("registry knows which user owns each socket", len(owner_conns) == 2 and len(users) == 2)

# REST paths
hdr_a = {"Authorization": f"Bearer {tok_a}"}
hdr_b = {"Authorization": f"Bearer {tok_b}"}
check("user A can GET own trip (REST)", client.get(f"/api/trips/{trip_id}", headers=hdr_a).status_code == 200)
check("user B cannot GET A's trip (REST)", client.get(f"/api/trips/{trip_id}", headers=hdr_b).status_code == 404)
check("user B cannot PATCH A's trip (REST)", client.patch(f"/api/trips/{trip_id}", json={"title": "pwned"}, headers=hdr_b).status_code == 404)
check("user B cannot export A's trip (REST)", client.get(f"/api/trips/{trip_id}/export", headers=hdr_b).status_code == 404)
check("user B cannot DELETE A's trip (REST)", client.delete(f"/api/trips/{trip_id}", headers=hdr_b).status_code == 404)
r = client.post("/api/trips", json={**trip_payload, "startDate": "2027-02-01", "endDate": "2027-02-02"}, headers=hdr_a)
check("REST trip creation works after a cache-warmed login (was a 500)", r.status_code == 201)
r = client.post("/api/chat", json={"message": "hello"}, headers=hdr_a)
check("chat after cache-warmed login no longer crashes (was a 500)", r.status_code == 200)
created_ids = {trip_id, r.json().get("id") if r.status_code == 201 else None}
check("A's trip still exists", client.get(f"/api/trips/{trip_id}", headers=hdr_a).json().get("title") == "Jaipur Tour Package")

# clean up queued test jobs
removed = 0
for raw in redis_conn.lrange(TASK_QUEUE_KEY, 0, -1):
    if any(tid and tid in raw for tid in created_ids):
        removed += redis_conn.lrem(TASK_QUEUE_KEY, 0, raw)
for key in redis_conn.scan_iter("rl:*"):
    redis_conn.delete(key)
for key in redis_conn.scan_iter("session_cache:*"):
    if redis_conn.get(key) in {u for u in main.connection_registry.connection_users.values()}:
        redis_conn.delete(key)
print(f"removed {removed} queued test jobs")

client.__exit__(None, None, None)
failed = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
