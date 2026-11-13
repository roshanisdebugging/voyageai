"""
Step 0 backend checks against a throwaway SQLite DB + local Redis. No real AI calls:
AI_PROVIDER=mock for generation; Groq/Gemini HTTP is simulated for the provider tests.
Run from backend/: python -m tests.test_step0
"""
import json
import os
import sys
from unittest import mock

import dotenv

dotenv.load_dotenv = lambda *a, **k: None
os.environ["DATABASE_URL"] = "postgresql://x:y@127.0.0.1:1/none"
os.environ["AI_PROVIDER"] = "mock"
for k in ("GROQ_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
    os.environ.pop(k, None)
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
import itinerary_service  # noqa: E402
# Never read the developer's local itinerary cache: a real (Groq) itinerary cached by a live run would
# replace the mock one this test expects.
itinerary_service.get_cached_itinerary = lambda key: None
database.Base.metadata.create_all(bind=database.engine)
for key in redis_conn.scan_iter("rl:*"):
    redis_conn.delete(key)

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if not cond and detail else ""))


client = TestClient(main.app)
client.__enter__()


def register(name, email):
    r = client.post("/api/auth/register", json={"name": name, "email": email, "password": "secret123"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


tok_a = register("Asha Tester", "asha@example.com")
tok_b = register("Bilal Tester", "bilal@example.com")
client.cookies.clear()

JAIPUR = {"name": "Jaipur", "region": "Rajasthan", "country": "India", "latitude": 26.9124, "longitude": 75.7873}
DELHI = {"name": "New Delhi", "region": "Delhi", "country": "India", "latitude": 28.6139, "longitude": 77.2090}
created_ids = set()

with client.websocket_connect("/ws/app") as ws_a, client.websocket_connect("/ws/app") as ws_b:
    def call(ws, action, payload, token):
        ws.send_json({"id": "x", "action": action, "payload": {**payload, "token": token}})
        while True:
            frame = ws.receive_json()
            if frame.get("id") == "x":
                return frame

    # ---------- 0b: budget amount, derived level, origin, adults/children
    f = call(ws_a, "trips:create", {
        "destination": JAIPUR, "origin": DELHI,
        "startDate": "2027-01-10", "endDate": "2027-01-12",
        "adultsCount": 2, "childrenCount": 2, "budgetAmount": 45000,
    }, tok_a)
    check("create trip with origin + budget", f["status"] == 200, f.get("error"))
    trip = f["data"] or {}
    trip_id = trip.get("id")
    created_ids.add(trip_id)
    check("budget amount saved (45000)", (trip.get("budget") or {}).get("targetAmount") == 45000, trip.get("budget"))
    # 45000 / (2 + 0.5*2 = 3 people) / 3 days = 5000/person/day -> MODERATE
    check("budget level derived (MODERATE)", (trip.get("budget") or {}).get("level") == "MODERATE", trip.get("budget"))
    check("origin reads back as New Delhi", (trip.get("origin") or {}).get("name") == "New Delhi", trip.get("origin"))
    check("adults/children saved", trip.get("adultsCount") == 2 and trip.get("childrenCount") == 2)

    f2 = call(ws_a, "trips:create", {
        "destination": JAIPUR, "origin": DELHI,
        "startDate": "2027-02-10", "endDate": "2027-02-11", "adultsCount": 1, "budgetAmount": 60000,
    }, tok_a)
    created_ids.add((f2.get("data") or {}).get("id"))
    from models_place import CityModel
    with database.SessionLocal() as s:
        delhi_rows = s.query(CityModel).filter(CityModel.name == "New Delhi").count()
    check("same starting city is reused, not duplicated", delhi_rows == 1, delhi_rows)
    check("big budget → LUXURY", ((f2.get("data") or {}).get("budget") or {}).get("level") == "LUXURY", f2.get("data"))

    f3 = call(ws_a, "trips:create", {"destination": JAIPUR, "startDate": "2027-03-01", "endDate": "2027-03-02",
                                     "adultsCount": 0, "childrenCount": 1}, tok_a)
    check("trip with no adult is rejected", f3["status"] == 400, f3)

    # REST read-back
    r = client.get(f"/api/trips/{trip_id}", headers={"Authorization": f"Bearer {tok_a}"})
    body = r.json()
    check("REST GET returns origin + budget", (body.get("origin") or {}).get("name") == "New Delhi"
          and body.get("budget", {}).get("targetAmount") == 45000, body.get("origin"))

    # ---------- itinerary generation (mock) incl. transport suggestions
    from itinerary_service import process_async_itinerary_generation
    status = process_async_itinerary_generation(trip_id, database.SessionLocal)
    check("itinerary generation returns READY", status == "READY", status)
    f = call(ws_a, "trips:get_transports", {"trip_id": trip_id}, tok_a)
    transports = f.get("data") or []
    rec = [t for t in transports if t.get("status") == "RECOMMENDED"]
    check("transport suggestion saved from origin", len(rec) >= 1 and rec[0].get("transportType") == "TRAIN", transports)
    check("suggested fare covers the whole group (800 x 4)", rec and rec[0].get("estimatedFare") == 3200, rec)

    # ---------- mark activity done
    f = call(ws_a, "trips:get_itinerary", {"trip_id": trip_id}, tok_a)
    days = (f.get("data") or {}).get("days") or []
    act_id = days[0]["activities"][0]["id"] if days else None
    check("itinerary exposes isDone", days and "isDone" in days[0]["activities"][0])
    f = call(ws_a, "trips:set_activity_done", {"trip_id": trip_id, "activity_id": act_id, "done": True}, tok_a)
    check("mark activity done", f["status"] == 200 and f["data"]["isDone"] is True
          and f["data"]["progress"]["completedActivitiesCount"] == 1, f)
    f = call(ws_a, "trips:set_activity_done", {"trip_id": trip_id, "activity_id": act_id, "done": False}, tok_a)
    check("undo mark done", f["status"] == 200 and f["data"]["isDone"] is False
          and f["data"]["progress"]["completedActivitiesCount"] == 0, f)
    f = call(ws_b, "trips:set_activity_done", {"trip_id": trip_id, "activity_id": act_id, "done": True}, tok_b)
    check("other user cannot mark done", f["status"] == 404, f)

    # ---------- 0a: every trip action refuses another user's trip
    actions = ["trips:get_itinerary", "trips:get_stays", "trips:add_stay", "trips:get_transports",
               "trips:add_transport", "trips:get_expenses", "trips:add_expense", "trips:weather_replan",
               "trips:optimize_day", "trips:optimize_budget", "trips:refine", "trips:regenerate_itinerary",
               "trips:swap_activity", "trips:delete"]
    refused = []
    for action in actions:
        f = call(ws_b, action, {"trip_id": trip_id, "activity_id": act_id, "day_id": "x"}, tok_b)
        if f["status"] != 404:
            refused.append((action, f["status"]))
    check("all 14 trip actions refuse another user's trip", not refused, refused)
    for action in actions[:3]:
        f = call(ws_b, action, {"trip_id": trip_id}, None)
        if f["status"] != 401:
            refused.append((action, "no-login", f["status"]))
    check("trip actions require login", not refused, refused)

    # ---------- 0c: smart actions end to end by tap (mock AI, real weather horizon logic)
    f = call(ws_a, "trips:optimize_day", {"trip_id": trip_id, "day_id": days[0]["id"]}, tok_a)
    check("optimize day works on own trip", f["status"] == 200, f.get("error"))
    f = call(ws_a, "trips:optimize_budget", {"trip_id": trip_id}, tok_a)
    check("optimize budget works on own trip", f["status"] == 200, f.get("error"))
    f = call(ws_a, "trips:weather_replan", {"trip_id": trip_id}, tok_a)
    check("weather replan far ahead says no forecast yet (no fake weather)",
          f["status"] == 400 and "16 days" in (f.get("error") or ""), f)

client.__exit__(None, None, None)

# ---------- 0d: Groq first, Gemini backup (simulated HTTP)
import ai_provider  # noqa: E402
import groq_client  # noqa: E402


class FakeResp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


groq_ok = FakeResp(200, {"choices": [{"message": {"content": '{"alternatives": [1]}'}, "finish_reason": "stop"}]})
gemini_ok = FakeResp(200, {"candidates": [{"content": {"parts": [{"text": '{"alternatives": [2]}'}]}}]})

os.environ["AI_PROVIDER"] = "groq"
os.environ["GROQ_API_KEY"] = "test-key"
os.environ["GEMINI_API_KEY"] = "test-key"
seen = []


def fake_post(url, **kw):
    seen.append("groq" if "groq.com" in url else "gemini")
    return groq_ok if "groq.com" in url else gemini_ok


with mock.patch("requests.post", side_effect=fake_post):
    out = json.loads(ai_provider.complete_json("say json"))
check("groq used first when it works", out == {"alternatives": [1]} and seen == ["groq"], seen)

seen.clear()


def fake_post_429(url, **kw):
    seen.append("groq" if "groq.com" in url else "gemini")
    return FakeResp(429, {"error": "rate"}) if "groq.com" in url else gemini_ok


with mock.patch("requests.post", side_effect=fake_post_429):
    out = json.loads(ai_provider.complete_json("say json"))
check("gemini backup when groq is rate-limited", out == {"alternatives": [2]} and seen[0] == "groq", seen)

with mock.patch("requests.post", side_effect=fake_post_429):
    prov = ai_provider.get_ai_provider()
    recs = prov.generate_refinement_actions("swap", {"days": []}) if False else None
check("provider chain is Groq then Gemini", [p.__class__.__name__ for p in prov.providers] == ["GroqProvider", "GeminiProvider"])

os.environ.pop("GROQ_API_KEY")
seen.clear()
with mock.patch("requests.post", side_effect=fake_post):
    out = json.loads(ai_provider.complete_json("say json"))
check("no Groq key → Gemini serves the call", out == {"alternatives": [2]} and seen == ["gemini"], seen)

# cost guard: Groq classifier with Gemini backup, fail closed when both fail
import cost_guard  # noqa: E402

os.environ["GROQ_API_KEY"] = "test-key"
cost_guard._guard = None
groq_intent = FakeResp(200, {"choices": [{"message": {"content": '{"intent": "travel", "unambiguous": true}'},
                                          "finish_reason": "stop"}]})
with mock.patch("requests.post", return_value=groq_intent):
    allowed, gate, _ = cost_guard.evaluate_cost_guards("best time to visit Amber Fort?")
check("cost guard accepts travel via Groq", allowed and gate == "PASSED_TO_LLM", gate)
cost_guard._guard = None
with mock.patch("requests.post", side_effect=Exception("network down")):
    allowed, gate, _ = cost_guard.evaluate_cost_guards("best time to visit Amber Fort?")
check("cost guard fails closed when every classifier fails", not allowed, gate)
cost_guard._guard = None

# cleanup: queued jobs from this test only
removed = 0
for raw in redis_conn.lrange(TASK_QUEUE_KEY, 0, -1):
    if any(tid and tid in raw for tid in created_ids):
        removed += redis_conn.lrem(TASK_QUEUE_KEY, 0, raw)
for key in redis_conn.scan_iter("rl:*"):
    redis_conn.delete(key)
print(f"removed {removed} queued test jobs")

failed = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
