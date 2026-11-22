"""
Map card "Details" (fixes-before-step4 item 10): GET /api/places/details with Google simulated.
Field mask, mapping, empty fields -> null/[], versioned cache, bad / mock IDs -> 404 without calling Google,
address search keeps the basic mask.
Run from backend/: python -m tests.test_place_details
"""
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

import dotenv

dotenv.load_dotenv = lambda *a, **k: None
os.environ["DATABASE_URL"] = "postgresql://x:y@127.0.0.1:1/none"
os.environ["AI_PROVIDER"] = "mock"
os.environ["GOOGLE_MAPS_SERVER_KEY"] = "test-key-not-real"

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)
SCRATCH = tempfile.mkdtemp(prefix="voyageai_test_")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

import database  # noqa: E402

database.engine = create_engine(f"sqlite:///{os.path.join(SCRATCH, 'details.db')}", connect_args={"check_same_thread": False})
database.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=database.engine)

import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from redis_client import redis_conn  # noqa: E402
from services import google_maps_service as gms  # noqa: E402

main.SessionLocal = database.SessionLocal
database.Base.metadata.create_all(bind=database.engine)
for key in redis_conn.scan_iter("rl:*"):
    redis_conn.delete(key)
gms.GOOGLE_MAPS_SERVER_KEY = "test-key-not-real"
gms.cache._disabled = True  # in-memory only
gms._in_memory_cache.clear()

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail != "" else ""), flush=True)


PID = "ChIJxxxxTestPlaceId_1234"
TEST_IDS = (PID, "ChIJyyyyTestPlaceId_5678", "ChIJbasicSearchUse_0001")


def drop_cached_test_places():
    """The details cache reaches the real local Redis: drop this test's fake places, so a re-run within 24 h still
    calls the (fake) Google API instead of reading the last run's copy, and nothing fake is left behind."""
    for test_id in TEST_IDS:
        for key in redis_conn.scan_iter(f"places:detail:*:{test_id}"):
            redis_conn.delete(key)


drop_cached_test_places()
FULL = {
    "id": PID, "displayName": {"text": "Hawa Mahal"}, "formattedAddress": "Hawa Mahal Rd, Jaipur, Rajasthan 302002, India",
    "location": {"latitude": 26.9239, "longitude": 75.8267},
    "regularOpeningHours": {"openNow": True, "weekdayDescriptions": ["Monday: 9:00 AM – 4:30 PM", "Tuesday: 9:00 AM – 4:30 PM"]},
    "nationalPhoneNumber": "0141 261 8862", "websiteUri": "https://hawamahal.com/", "googleMapsUri": "https://maps.google.com/?cid=1",
    "editorialSummary": {"text": "Iconic pink sandstone palace."},
}


class FakeGoogle:
    calls, queue = [], []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, headers=None):
        FakeGoogle.calls.append((url, headers))
        status, body = FakeGoogle.queue.pop(0) if FakeGoogle.queue else (404, {})
        resp = mock.Mock()
        resp.status_code = status
        resp.json.return_value = body
        return resp


client = TestClient(main.app)
client.__enter__()
with mock.patch.object(gms.httpx, "AsyncClient", FakeGoogle):
    FakeGoogle.queue = [(200, FULL)]
    r = client.get("/api/places/details", params={"place_id": PID})
    d = r.json()
    check("200 with the details shape", r.status_code == 200 and set(d) == {"id", "name", "address", "latitude", "longitude", "open_now",
                                                                           "hours", "phone", "website", "maps_url", "summary"}, sorted(d))
    check("mapping", d["name"] == "Hawa Mahal" and d["open_now"] is True and len(d["hours"]) == 2 and d["phone"] == "0141 261 8862"
          and d["website"] == "https://hawamahal.com/" and d["maps_url"].startswith("https://maps.google") and d["summary"].startswith("Iconic"), d)
    mask = FakeGoogle.calls[-1][1]["X-Goog-FieldMask"]
    check("field mask asks for hours, phone, website, Google Maps link, summary",
          all(f in mask for f in ("regularOpeningHours", "nationalPhoneNumber", "websiteUri", "googleMapsUri", "editorialSummary")), mask)
    check("no photos or reviews requested", "photos" not in mask and "reviews" not in mask)
    n = len(FakeGoogle.calls)
    r2 = client.get("/api/places/details", params={"place_id": PID})
    check("second call is a cache hit", r2.status_code == 200 and len(FakeGoogle.calls) == n)
    check("cache key is versioned", any(k.startswith("places:detail:v2:full:") for k in gms._in_memory_cache))

    FakeGoogle.queue = [(200, {"id": "ChIJyyyyTestPlaceId_5678", "displayName": {"text": "Small Cafe"}, "location": {"latitude": 1.0, "longitude": 2.0}})]
    d = client.get("/api/places/details", params={"place_id": "ChIJyyyyTestPlaceId_5678"}).json()
    check("missing fields -> null / [] (the page hides them)", d["open_now"] is None and d["hours"] == [] and d["phone"] is None
          and d["website"] is None and d["summary"] is None and d["address"] == "", d)

    FakeGoogle.queue = [(404, {})]
    r = client.get("/api/places/details", params={"place_id": "ChIJzzzzUnknownPlace_000"})
    check("Google 404 -> 404", r.status_code == 404)
    n = len(FakeGoogle.calls)
    codes = [client.get("/api/places/details", params={"place_id": bad}).status_code
             for bad in ("poi-26.9-75.8", "../etc", "a/b/c/d/e/f/g", "short", " ", "x" * 301)]
    check("bad / mock IDs -> 404 without calling Google", all(c == 404 for c in codes) and len(FakeGoogle.calls) == n, codes)

    import asyncio
    FakeGoogle.queue = [(200, FULL)]
    basic = asyncio.run(gms.get_place_details("ChIJbasicSearchUse_0001"))
    check("address search keeps the basic mask", FakeGoogle.calls[-1][1]["X-Goog-FieldMask"] == gms.PLACE_FIELDS_BASIC
          and set(basic) == {"id", "name", "address", "latitude", "longitude"})

client.__exit__(None, None, None)
drop_cached_test_places()
print(f"\n{sum(results)}/{len(results)} passed", flush=True)
sys.exit(0 if all(results) else 1)
