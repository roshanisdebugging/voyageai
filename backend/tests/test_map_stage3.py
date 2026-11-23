"""
Map stage 3: Google Routes API. Google and OpenAI simulated.
POST /api/routes/compute: login, modes, validation, India only, field mask (no wildcard), TRAFFIC_UNAWARE (not for
WALK), cache hit = 0 calls, quota -> 503 + pause, rate limit, per-user daily count, no coordinates in logs.
Voice get_travel_time: "Hawa Mahal kitni door hai", "airport kitni door hai bike se", Routes paused, trip origin.
Run from backend/: python -m tests.test_map_stage3
"""
import contextlib
import io
import os
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import dotenv

dotenv.load_dotenv = lambda *a, **k: None
os.environ["DATABASE_URL"] = "postgresql://x:y@127.0.0.1:1/none"
os.environ["AI_PROVIDER"] = "mock"
os.environ["GOOGLE_MAPS_SERVER_KEY"] = "test-key-not-real"
os.environ["ROUTES_CACHE_TTL_S"] = "1800"   # the cache tests turn it on; the default is 0 (test_map_stage4)

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)
SCRATCH = tempfile.mkdtemp(prefix="voyageai_test_")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

import database  # noqa: E402

database.engine = create_engine(f"sqlite:///{os.path.join(SCRATCH, 'map3.db')}", connect_args={"check_same_thread": False})
database.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=database.engine)

import main  # noqa: E402
import openai_client  # noqa: E402
import places  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from redis_client import redis_conn  # noqa: E402
from services import google_maps_service as gms  # noqa: E402
from services import routes_service as rs  # noqa: E402
from voice import agent  # noqa: E402
from voice.tools import lookups  # noqa: E402

main.SessionLocal = database.SessionLocal
database.Base.metadata.create_all(bind=database.engine)
for key in redis_conn.scan_iter("rl:*"):
    redis_conn.delete(key)
gms.GOOGLE_MAPS_SERVER_KEY = "test-key-not-real"


class MemCache:
    def __init__(self):
        self.d, self.ttl = {}, {}

    async def get(self, key):
        return self.d.get(key)

    async def set(self, key, value, ttl_seconds=0):
        self.d[key] = value
        self.ttl[key] = ttl_seconds


gms.cache = MemCache()
results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail != "" else ""), flush=True)


def resp(status, body):
    r = mock.Mock()
    r.status_code = status
    r.json.return_value = body
    return r


ROUTE_OK = (200, {"routes": [{"distanceMeters": 6830, "duration": "1364s", "polyline": {"encodedPolyline": "_p~iF~ps|U_ulLnnqC"}}]})
ROUTE_WARN = (200, {"routes": [{"distanceMeters": 6700, "duration": "1200s", "polyline": {"encodedPolyline": "abc"},
                                "warnings": ["This route has tolls.", "Use caution."]}]})
QUOTA = (429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED",
                         "message": "Quota exceeded for quota metric 'ComputeRoutesRequest' and limit 'per day'"}})


class FakeRoutes:
    calls, queue = [], []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):
        FakeRoutes.calls.append((url, headers, json))
        return resp(*(FakeRoutes.queue.pop(0) if FakeRoutes.queue else ROUTE_OK))


def reset():
    FakeRoutes.calls.clear()
    FakeRoutes.queue.clear()
    gms.cache.d.clear()


client = TestClient(main.app)
client.__enter__()
email = f"routes_{uuid.uuid4().hex[:6]}@example.com"
r = client.post("/api/auth/register", json={"name": "Route Tester", "email": email, "password": "secret123"})
token = r.json()["token"]
user_id = r.json()["user"]["id"]
client.cookies.clear()
AUTH = {"Authorization": f"Bearer {token}"}
HAWA = {"lat": 26.9239, "lng": 75.8267}
AMER = {"lat": 26.9855, "lng": 75.8513}


def post(body, auth=True):
    return client.post("/api/routes/compute", json=body, headers=AUTH if auth else {})


with mock.patch.object(rs.httpx, "AsyncClient", FakeRoutes):
    # ---------------- login, modes, validation
    reset()
    check("guest refused (401)", post({"origin": HAWA, "destination": AMER, "mode": "drive"}, auth=False).status_code == 401)
    for mode, travel in (("drive", "DRIVE"), ("two_wheeler", "TWO_WHEELER"), ("walk", "WALK")):
        reset()
        r = post({"origin": HAWA, "destination": AMER, "mode": mode})
        d = r.json()
        body = FakeRoutes.calls[-1][2] if FakeRoutes.calls else {}
        check(f"mode {mode} accepted -> {travel}", r.status_code == 200 and body.get("travelMode") == travel
              and d["distance_m"] == 6830 and d["duration_s"] == 1364 and d["mode"] == mode and d["polyline"], (r.status_code, d))
        check(f"{mode}: warnings asked in English (en-IN), metric", body.get("languageCode") == "en-IN" and body.get("units") == "METRIC")
        if mode == "walk":
            check("walk sends no routingPreference (Google rejects it)", "routingPreference" not in body)
        else:
            check(f"{mode} uses TRAFFIC_UNAWARE", body.get("routingPreference") == "TRAFFIC_UNAWARE")
    mask = FakeRoutes.calls[-1][1]["X-Goog-FieldMask"]
    check("field mask: exact fields, no wildcard", "*" not in mask and mask.split(",") ==
          ["routes.duration", "routes.distanceMeters", "routes.polyline.encodedPolyline", "routes.warnings"], mask)
    check("key in header, never in the URL", "key=" not in FakeRoutes.calls[-1][0]
          and FakeRoutes.calls[-1][1]["X-Goog-Api-Key"] == "test-key-not-real")

    reset()
    n = len(FakeRoutes.calls)
    bad = [post({"origin": HAWA, "destination": AMER, "mode": "fly"}),
           post({"origin": HAWA, "destination": AMER, "mode": "TRANSIT"}),
           post({"origin": {"lat": 48.858, "lng": 2.294}, "destination": AMER, "mode": "drive"}),
           post({"origin": HAWA, "destination": {"lat": 200, "lng": 75}, "mode": "drive"})]
    check("invalid mode / out of India / out of range -> 400, no Google call",
          [b.status_code for b in bad] == [400, 400, 400, 400] and len(FakeRoutes.calls) == n, [b.status_code for b in bad])
    check("out of India says so", "India" in bad[2].json()["detail"])

    # ---------------- warning, cache
    reset()
    FakeRoutes.queue = [ROUTE_WARN]
    r = post({"origin": HAWA, "destination": AMER, "mode": "two_wheeler"})
    check("Google's route warnings returned as 'warning'", r.json()["warning"] == "This route has tolls. Use caution.", r.json())
    reset()
    post({"origin": HAWA, "destination": AMER, "mode": "drive"})
    n = len(FakeRoutes.calls)
    r2 = post({"origin": {"lat": 26.92392, "lng": 75.82671}, "destination": AMER, "mode": "drive"})   # same at 3 decimals
    check("cache hit -> 0 Google calls", len(FakeRoutes.calls) == n and r2.json()["cached"] is True, len(FakeRoutes.calls) - n)
    key = rs.cache_key(26.9239, 75.8267, 26.9855, 75.8513, "drive")
    check("cache key: rounded to 3 decimals + mode, TTL 30 min", key == "routes:v1:drive:26.924:75.827:26.985:75.851"
          and gms.cache.ttl.get(key) == 1800, (key, gms.cache.ttl.get(key)))
    post({"origin": HAWA, "destination": AMER, "mode": "walk"})
    check("other mode -> its own call", len(FakeRoutes.calls) == n + 1)
    with mock.patch.dict(os.environ, {"ROUTES_CACHE_TTL_S": "0"}):
        reset()
        post({"origin": HAWA, "destination": AMER, "mode": "drive"})
        post({"origin": HAWA, "destination": AMER, "mode": "drive"})
        check("ROUTES_CACHE_TTL_S=0 -> nothing cached (Google terms 19.3)", len(FakeRoutes.calls) == 2 and not gms.cache.d)

    # ---------------- no route, quota / paused
    reset()
    FakeRoutes.queue = [(200, {})]
    check("no route from Google -> 404, nothing invented", post({"origin": HAWA, "destination": AMER, "mode": "drive"}).status_code == 404)
    reset()
    FakeRoutes.queue = [QUOTA]
    r = post({"origin": HAWA, "destination": AMER, "mode": "drive"})
    check("quota -> 503 'Route abhi available nahi hai'", r.status_code == 503 and r.json()["detail"] == "Route abhi available nahi hai", r.text[:120])
    check("quota -> Routes paused until Google's reset", gms.cache.d.get("gmaps:paused:routes") is True
          and 60 < gms.cache.ttl.get("gmaps:paused:routes", 0) <= 86460)
    n = len(FakeRoutes.calls)
    r = post({"origin": {"lat": 28.6129, "lng": 77.2295}, "destination": {"lat": 28.5245, "lng": 77.1855}, "mode": "drive"})
    check("while paused -> 503 with 0 Google calls (no retry)", r.status_code == 503 and len(FakeRoutes.calls) == n)

    # ---------------- per-user daily count, logs
    reset()
    day_key = f"routes:calls:{user_id}:{datetime.now(timezone(timedelta(hours=5, minutes=30))):%Y-%m-%d}"
    redis_conn.delete(day_key)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        post({"origin": HAWA, "destination": AMER, "mode": "drive"})
        post({"origin": HAWA, "destination": AMER, "mode": "drive"})                 # cached
        post({"origin": HAWA, "destination": {"lat": 26.9116, "lng": 75.8195}, "mode": "drive"})
    log = buf.getvalue()
    check("per-user daily count = real Google calls only", int(redis_conn.get(day_key) or 0) == 2, redis_conn.get(day_key))
    check("log has counts", "[ROUTES] mode=drive google_calls=1" in log and "google_calls=0 cached=True" in log, log.strip())
    check("log has no coordinates, user or key", not any(x in log for x in ("26.92", "75.82", "26.98", user_id, "test-key-not-real")))
    redis_conn.delete(day_key)

    # ---------------- rate limit (20 a minute per user)
    reset()
    for k in redis_conn.scan_iter("rl:routes:*"):
        redis_conn.delete(k)
    codes = [post({"origin": HAWA, "destination": AMER, "mode": "drive"}).status_code for _ in range(21)]
    check("rate limit: 21st request in a minute -> 429", codes[:20] == [200] * 20 and codes[20] == 429, codes[-3:])
    for k in redis_conn.scan_iter("rl:routes:*"):
        redis_conn.delete(k)

    # ---------------- voice get_travel_time
    HAWA_HIT = [{"id": "ChIJhawa", "name": "Hawa Mahal", "city": "Badi Choupad, Jaipur, Rajasthan, India",
                 "latitude": 26.9239, "longitude": 75.8267, "types": ["tourist_attraction", "monument"]}]
    AIRPORT_HIT = [{"id": "ChIJjai", "name": "Jaipur International Airport", "city": "Sanganer, Jaipur, Rajasthan, India",
                    "latitude": 26.8242, "longitude": 75.8122, "types": ["airport"]}]
    ME = (26.9124, 75.7873)

    class FakeLLM:
        queue = []

        def __call__(self, messages_, tools, **kw):
            name, args = FakeLLM.queue.pop(0)
            return {"content": None, "tool_calls": [{"name": name, "arguments": args}]}

    def say(text, hits, tool_args, location=ME, lang="hi"):
        FakeLLM.queue = [("get_travel_time", tool_args)]
        with mock.patch.object(openai_client, "chat_tools", FakeLLM()), \
                mock.patch.object(places, "search_places", lambda q: hits):
            return agent.run_agent(text, lang, user_id=user_id, conversation_id=f"conv_{uuid.uuid4().hex[:6]}",
                                   screen="/home", trip=None, redis_conn=redis_conn, location=location)

    reset()
    t = say("Hawa Mahal kitni door hai", HAWA_HIT, {"place": "Hawa Mahal"})
    check("voice 'Hawa Mahal kitni door hai' -> one sentence with km and car time",
          t.reply_text == "Hawa Mahal aapki location se 6.8 km hai, car se 23 minute." and t.action == "travel_time", t.reply_text)
    check("voice: drive by default, from the user's location", FakeRoutes.calls[-1][2]["travelMode"] == "DRIVE"
          and abs(FakeRoutes.calls[-1][2]["origin"]["location"]["latLng"]["latitude"] - ME[0]) < 1e-6)
    check("voice: never writes / no screen actions", t.ui_actions == [] and t.pending_actions == [])

    reset()
    FakeRoutes.queue = [ROUTE_WARN]
    t = say("airport kitni door hai bike se", AIRPORT_HIT, {"place": "Jaipur airport", "mode": "two_wheeler"})
    check("voice 'airport kitni door hai bike se' -> bike route", FakeRoutes.calls[-1][2]["travelMode"] == "TWO_WHEELER"
          and t.reply_text == "Jaipur International Airport aapki location se 6.7 km hai, bike se 20 minute.", t.reply_text)
    check("voice: Google's warning in the screen note, not spoken", t.note == "This route has tolls. Use caution."
          and "caution" not in t.reply_text.lower())

    reset()
    t = say("how far is Hawa Mahal", HAWA_HIT, {"place": "Hawa Mahal", "mode": None}, lang="en")
    check("voice English", t.reply_text == "Hawa Mahal is 6.8 km from your location, 23 minutes by car.", t.reply_text)

    reset()
    FakeRoutes.queue = [QUOTA]
    t = say("Hawa Mahal kitni door hai", HAWA_HIT, {"place": "Hawa Mahal"})
    check("voice: Routes paused -> 'Route abhi available nahi hai' + straight-line distance",
          t.reply_text.startswith("Route abhi available nahi hai.") and "Seedhi doori 4.1 km" in t.reply_text, t.reply_text)

    # Origin = the device location only (fix-origin-current): never the trip destination
    reset()
    with mock.patch.object(lookups, "_trip_destination", lambda u, tid: {"name": "Jaipur", "latitude": 26.9124, "longitude": 75.7873}):
        t = lookups.get_travel_time("Hawa Mahal", "car", "hi", user_id=user_id, trip_id="trip_x", origin=None,
                                    search_fn=lambda q: HAWA_HIT)
    check("voice: no location (trip open) -> 'Aapki location nahi mili, location on kijiye', no trip fallback",
          t.reply_text == "Aapki location nahi mili, location on kijiye." and t.error_code == "no_origin", t.reply_text)
    check("voice: no location -> no Google call at all (no search, no route)", FakeRoutes.calls == [] and not t.google_calls)
    t = say("Hawa Mahal kitni door hai", HAWA_HIT, {"place": "Hawa Mahal"}, location=None)
    check("voice via agent, no location -> asks for location, no route call",
          t.reply_text == "Aapki location nahi mili, location on kijiye." and FakeRoutes.calls == [], t.reply_text)
    t = lookups.get_travel_time("Hawa Mahal", None, "en", origin=None, search_fn=lambda q: HAWA_HIT)
    check("voice English, no location", t.reply_text == "I couldn't get your location. Please turn location on.", t.reply_text)

    reset()
    t = lookups.get_travel_time("Hawa Mahal", None, "hi", origin=(26.9240, 75.8268), search_fn=lambda q: HAWA_HIT)
    check("voice: under 150 m -> 'Aap Hawa Mahal par hi hain', no route call",
          t.reply_text == "Aap Hawa Mahal par hi hain." and FakeRoutes.calls == [], t.reply_text)
    t = lookups.get_travel_time("Hawa Mahal", None, "hi", origin=(28.6129, 77.2295), search_fn=lambda q: HAWA_HIT)
    check("voice: Delhi -> Hawa Mahal (~238 km) still gets a route", len(FakeRoutes.calls) == 1, t.reply_text)
    reset()
    t = lookups.get_travel_time("Hawa Mahal", None, "hi", origin=(19.0760, 72.8777), search_fn=lambda q: HAWA_HIT)
    check("voice: over 300 km (Mumbai) -> 'door hain' + straight-line km, no route call",
          t.error_code == "far_away" and "door hain" in t.reply_text and " km" in t.reply_text and FakeRoutes.calls == [], t.reply_text)

    from voice.ws import _parse_location
    check("voice start location: accuracy 30 m -> used", _parse_location({"lat": 26.9, "lng": 75.8, "accuracy_m": 30}) == (26.9, 75.8))
    check("voice start location: accuracy 2 km -> ignored", _parse_location({"lat": 26.9, "lng": 75.8, "accuracy_m": 2000}) is None)
    check("voice start location: no accuracy -> ignored", _parse_location({"lat": 26.9, "lng": 75.8}) is None)
    check("voice start location: outside India -> ignored", _parse_location({"lat": 51.5, "lng": -0.1, "accuracy_m": 10}) is None)

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        reset()
        say("Hawa Mahal kitni door hai", HAWA_HIT, {"place": "Hawa Mahal"})
    check("voice logs: no words, no coordinates", not any(x in buf.getvalue() for x in ("Hawa", "kitni", "26.91", "75.78")),
          buf.getvalue().strip()[:200])
    check("tool list has get_travel_time", "get_travel_time" in agent.TOOL_NAMES)

for k in list(redis_conn.scan_iter(f"routes:calls:{user_id}:*")) + list(redis_conn.scan_iter(f"voice:*{user_id}*")):
    redis_conn.delete(k)
client.__exit__(None, None, None)
print(f"\n{sum(results)}/{len(results)} passed", flush=True)
sys.exit(0 if all(results) else 1)
