"""
Map stage 1: Google-only place search, landmark-first ranking, quota safety, Geocoding v4. Google simulated.
Landmark beats a shop with a similar name; ambiguous query -> up to 3 choices; empty result; quota/paused error
stops at once (search, REST, WS, voice); non-India result excluded; call count unchanged (1 + up to 6);
reverse geocoding uses v4 and calls nothing else on a quota error; logs carry the count, never the query.
Run from backend/: python -m tests.test_map_stage1
"""
import contextlib
import io
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

database.engine = create_engine(f"sqlite:///{os.path.join(SCRATCH, 'map1.db')}", connect_args={"check_same_thread": False})
database.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=database.engine)

import main  # noqa: E402
import places  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from redis_client import redis_conn  # noqa: E402
from services import google_maps_service as gms  # noqa: E402
from voice import agent  # noqa: E402
from voice.tools import lookups  # noqa: E402

main.SessionLocal = database.SessionLocal
database.Base.metadata.create_all(bind=database.engine)
for key in redis_conn.scan_iter("rl:*"):
    redis_conn.delete(key)
gms.GOOGLE_MAPS_SERVER_KEY = "test-key-not-real"


class MemCache:
    """Replaces the Redis-backed cache so runs never read or write the real local Redis."""

    def __init__(self):
        self.d, self.ttl = {}, {}

    async def get(self, key):
        return self.d.get(key)

    async def set(self, key, value, ttl_seconds=0):
        self.d[key] = value
        self.ttl[key] = ttl_seconds

    async def ttl_left(self, key):
        return self.ttl.get(key, -1) if key in self.d else None


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


# The demo key's real daily error (22 Nov 2026), and a per-minute one.
QUOTA_429 = (429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED",
                             "message": "Quota exceeded for quota metric 'GetPlaceRequest' and limit 'GetPlaceRequest per day'",
                             "details": [{"reason": "RATE_LIMIT_EXCEEDED", "metadata": {"quota_limit": "GetPlaceRequestPerDayPerProject"}}]}})
QUOTA_MINUTE = (429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED",
                                "message": "Quota exceeded for quota metric 'AutocompletePlacesRequest' and limit 'requests per minute'",
                                "details": [{"metadata": {"quota_limit": "AutocompletePlacesRequestPerMinutePerProject"}}]}})
QUOTA_403 = (403, {"error": {"code": 403, "status": "PERMISSION_DENIED", "message": "The daily limit for this demo key was reached; it is paused until tomorrow."}})


class FakeGoogle:
    """Answers Text Search and autocomplete by the query text, details by place ID. Records every request."""
    calls = []
    textsearch = {}     # query -> (status, body)
    autocomplete = {}   # query -> (status, body)
    details = {}        # place_id -> (status, body)
    geocode = []        # queue of (status, body) for GET geocode / POST searchNearby

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):
        FakeGoogle.calls.append(("POST", url, headers, json))
        if url.endswith("places:searchText"):
            return resp(*FakeGoogle.textsearch.get(json["textQuery"], (200, {})))
        if url.endswith("places:autocomplete"):
            return resp(*FakeGoogle.autocomplete.get(json["input"], (200, {})))
        return resp(*(FakeGoogle.geocode.pop(0) if FakeGoogle.geocode else (500, {})))

    async def get(self, url, headers=None):
        FakeGoogle.calls.append(("GET", url, headers, None))
        if "/v1/places/" in url:
            return resp(*FakeGoogle.details.get(url.rsplit("/", 1)[1], (404, {})))
        return resp(*(FakeGoogle.geocode.pop(0) if FakeGoogle.geocode else (500, {})))


def suggestion(pid, name, secondary, types):
    return {"placePrediction": {"placeId": pid, "text": {"text": f"{name}, {secondary}"},
                                "structuredFormat": {"mainText": {"text": name}, "secondaryText": {"text": secondary}},
                                "types": types}}


def detail(pid, name, lat, lng):
    return (200, {"id": pid, "displayName": {"text": name}, "formattedAddress": name, "location": {"latitude": lat, "longitude": lng}})


def setup(query, items):
    """items: (pid, name, secondary, types, lat, lng). Google's order is the list order."""
    FakeGoogle.autocomplete[query] = (200, {"suggestions": [suggestion(p, n, s, t) for p, n, s, t, _, _ in items]})
    FakeGoogle.textsearch[query] = (200, {"places": [
        {"id": p, "displayName": {"text": n}, "formattedAddress": f"{n}, {s}", "location": {"latitude": la, "longitude": ln},
         "types": t} for p, n, s, t, la, ln in items]})
    for p, n, _, _, la, ln in items:
        FakeGoogle.details[p] = detail(p, n, la, ln)


def reset():
    FakeGoogle.calls.clear()
    gms.cache.d.clear()


STORE = ["service", "manufacturer", "store", "establishment", "point_of_interest"]
MOSQUE = ["place_of_worship", "mosque", "point_of_interest", "establishment"]
MONUMENT = ["monument", "tourist_attraction", "historical_place", "place_of_worship", "point_of_interest", "establishment"]
TEMPLE = ["hindu_temple", "place_of_worship", "point_of_interest", "establishment"]

# A shop with a similar name comes first from Google; the landmark is second.
setup("Charminar", [
    ("ChIJshop_charminar01", "Charminar Xerox and Colour Prints", "Pathar Gatti, Hyderabad, Telangana, India", STORE, 17.3605, 78.4740),
    ("ChIJlandmark_charmi1", "Charminar", "Char Kaman, Ghansi Bazaar, Hyderabad, Telangana, India", MONUMENT, 17.3616, 78.4747),
])
# Google's real answer for "4 minar" (22 Nov 2026): a shop first, an address, then small mosques. No Charminar.
setup("4 minar", [
    ("ChIJ4minar_xerox_001", "4 Minar Modi Colour Xerox", "Chow Mohalla, Pathar Gatti, Hyderabad, Telangana, India", STORE, 17.3600, 78.4730),
    ("ChIJ4minar_road_0002", "4, Minar Road", "Subhash Colony, Karnal, Haryana, India", ["geocode", "premise"], 29.69, 76.99),
    ("ChIJ4minar_belai_003", "Masjid 4 Minar Belai", "Belai, Madhya Pradesh, India", MOSQUE, 23.5, 77.5),
    ("ChIJ4minar_delhi_004", "Masjid Char Minar", "Block E 2, Nand Nagri, Mandoli, Delhi, India", MOSQUE, 28.70, 77.30),
])
# Ambiguous: five ghats, none named like the query.
setup("Varanasi ghat", [(f"ChIJghat_number_{i:04d}", n, "Varanasi, Uttar Pradesh, India", TEMPLE, 25.30 + i / 1000, 83.01)
                        for i, n in enumerate(["Dashashwamedh Ghat", "Assi Ghat", "Manikarnika Ghat", "Kedar Ghat", "Harishchandra Ghat"])])
# Non-India result among India ones.
setup("Eiffel", [
    ("ChIJeiffel_paris_001", "Eiffel Tower", "Paris, France", MONUMENT, 48.858, 2.294),
    ("ChIJeiffel_replica_2", "Eiffel Tower Replica", "Kota, Rajasthan, India", MONUMENT, 25.18, 75.83),
])
# More than 6 suggestions: details only for the first 6.
setup("Jaipur", [(f"ChIJjaipur_place_{i:03d}", f"Jaipur place {i}", "Jaipur, Rajasthan, India", ["locality", "political"], 26.9, 75.8)
                 for i in range(8)])
for q, answer in (("xyzzy nothing", (200, {})), ("quota please", QUOTA_429), ("paused please", QUOTA_403),
                  ("minute please", QUOTA_MINUTE)):
    FakeGoogle.autocomplete[q] = answer
    FakeGoogle.textsearch[q] = answer
setup("details quota", [("ChIJdetails_quota_01", "Some Fort", "Jaipur, Rajasthan, India", MONUMENT, 26.9, 75.8)])
FakeGoogle.details["ChIJdetails_quota_01"] = QUOTA_429

client = TestClient(main.app)
client.__enter__()
with mock.patch.object(gms.httpx, "AsyncClient", FakeGoogle):
    # ---------------- ranking
    reset()
    found = places.search_places_detailed("Charminar")
    check("landmark beats a shop with a similar name", found.results and found.results[0]["name"] == "Charminar"
          and found.results[0]["kind"] == "landmark", [r["name"] for r in found.results])
    check("shop is kept, but last", found.results[-1]["kind"] == "shop" and len(found.results) == 2)
    check("clear landmark -> not ambiguous", found.ambiguous is False)
    check("named lookup = exactly 1 Google call (Text Search), no Details", found.google_calls == 1 and len(FakeGoogle.calls) == 1
          and FakeGoogle.calls[0][1].endswith("places:searchText"), (found.google_calls, [c[1] for c in FakeGoogle.calls]))
    ts = FakeGoogle.calls[0]
    check("Text Search: regionCode IN, field mask id/name/address/location/types only (no photos, reviews)",
          ts[3]["regionCode"] == "IN" and ts[2]["X-Goog-FieldMask"] == "places.id,places.displayName,places.formattedAddress,places.location,places.types",
          ts[2]["X-Goog-FieldMask"])

    reset()
    found = places.search_places_detailed("4 minar")
    check("'4 minar': the shop is never first", found.results[0]["kind"] != "shop", [r["name"] for r in found.results])
    check("'4 minar': two similar mosques -> ambiguous, up to 3 choices, no shop among them",
          found.ambiguous and 1 < len(found.choices) <= 3 and all(c["kind"] != "shop" for c in found.choices),
          [c["name"] for c in found.choices])

    reset()
    found = places.search_places_detailed("Varanasi ghat")
    check("ambiguous query -> at most 3 choices", found.ambiguous and len(found.choices) == 3, [c["name"] for c in found.choices])

    reset()
    found = places.search_places_detailed("xyzzy nothing")
    check("empty result -> no results, nothing invented, 1 call", found.results == [] and not found.ambiguous
          and found.google_calls == 1, found)

    reset()
    found = places.search_places_detailed("Eiffel")
    check("non-India result excluded", [r["name"] for r in found.results] == ["Eiffel Tower Replica"], [r["name"] for r in found.results])

    reset()
    found = places.search_places_detailed("Jaipur")
    check("8 places found -> still 1 Google call", found.google_calls == 1 and len(FakeGoogle.calls) == 1, found.google_calls)
    again = places.search_places_detailed("Jaipur")
    check("cached search -> 0 Google calls, same order", again.google_calls == 0
          and [r["id"] for r in again.results] == [r["id"] for r in found.results])

    # Real Google orders seen in the eval (22 Nov 2026).
    def names(q, items):
        return [r["name"] for r in places.rank_places(q, [{"name": n, "latitude": 20, "longitude": 78, "types": t}
                                                          for n, t in items]).results]
    check("Google's #1 typed 'premise' is not pushed below another city's temple ('Golden Temple')",
          names("Golden Temple", [("Golden Temple", ["geocode", "premise"]), ("GOLDEN TEMPLE", TEMPLE),
                                  ("Golden Temple Parking Front Gate", ["service", "parking", "establishment"])])[0] == "Golden Temple")
    check("Google's #1 typed 'route' stays first ('Marine Drive')",
          names("Marine Drive", [("Marine Drive", ["route", "geocode"]), ("Marine Drive", ["sublocality", "political"]),
                                 ("Marine Drive Park", ["park", "establishment"])])[0] == "Marine Drive"
          and places.rank_places("Marine Drive", [{"name": "Marine Drive", "latitude": 20, "longitude": 78, "types": ["route"]}]).results[0]["kind"] == "area")
    check("a bus stop with the same name goes below the landmark ('Gate way of India')",
          names("Gate way of India", [("Gate Way Of India", ["transit_station", "bus_stop", "establishment"]),
                                      ("Gateway of India", ["historical_landmark", "establishment"])])[0] == "Gateway of India")

    # Same place returned several times (the Hawa Mahal voice case, 22 Nov 2026): merged before judging ambiguity.
    def place(n, lat, lng, t):
        return {"name": n, "latitude": lat, "longitude": lng, "types": t}
    dup = places.rank_places("Sjohawamahal", [place("Hawa Mahal", 26.92390, 75.82670, MONUMENT),
                                              place("Hawa Mahal", 26.92430, 75.82680, ["premise", "geocode"]),
                                              place("hawa mahal", 26.92400, 75.82640, ["neighborhood", "political"])])
    check("same name 50 m apart -> one result, no choice question", len(dup.results) == 1 and not dup.ambiguous
          and dup.results[0]["kind"] == "landmark", [(r["name"], r["kind"]) for r in dup.results])
    far = places.rank_places("Hawa Mahal", [place("Hawa Mahal", 26.9239, 75.8267, MONUMENT),
                                            place("Hawa Mahal", 26.9689, 75.8267, MONUMENT)])   # ~5 km north
    check("same name 5 km apart -> stays two", len(far.results) == 2, len(far.results))
    near_other = places.rank_places("ghat", [place("Assi Ghat", 25.2900, 83.0060, TEMPLE),
                                             place("Tulsi Ghat", 25.2905, 83.0062, TEMPLE)])
    check("different names close together -> both kept", len(near_other.results) == 2)

    check("untyped results keep Google's order and are not ambiguous",
          [r["name"] for r in places.rank_places("x", [{"name": "B", "latitude": 26, "longitude": 75},
                                                        {"name": "A", "latitude": 26, "longitude": 75}]).results] == ["B", "A"])

    # ---------------- quota / paused
    for q, label in (("quota please", "429 RESOURCE_EXHAUSTED"), ("paused please", "403 paused")):
        reset()
        found = places.search_places_detailed(q)
        check(f"{label}: unavailable, 1 call, no details call, no retry",
              found.unavailable and found.google_calls == 1 and len(FakeGoogle.calls) == 1, (found.google_calls, len(FakeGoogle.calls)))
    reset()
    places.search_places_detailed("quota please")
    n = len(FakeGoogle.calls)
    again = places.search_places_detailed("Charminar")
    check("after a quota error the next search calls Google 0 times", again.unavailable and again.google_calls == 0
          and len(FakeGoogle.calls) == n)
    ttl = gms.cache.ttl.get(gms.pause_key("textsearch"), 0)
    check("daily limit -> paused until Google's reset (midnight Pacific)", 60 < ttl <= 86400 + 60, ttl)
    reset()
    places.search_places_detailed("minute please")
    check("per-minute limit -> paused 60 s only", gms.cache.ttl.get(gms.pause_key("textsearch")) == 60, gms.cache.ttl)

    # ---------------- typing suggestions (autocomplete only) and picking one (one Place Details call)
    reset()
    sugg = places.suggest_places("Charminar")
    check("suggestions while typing: 1 autocomplete call, no Details, no coordinates",
          len(FakeGoogle.calls) == 1 and FakeGoogle.calls[0][1].endswith("places:autocomplete")
          and sugg and all("latitude" not in s for s in sugg) and sugg[1]["name"] == "Charminar", [c[1] for c in FakeGoogle.calls])
    reset()
    check("fewer than 3 characters -> no call", places.suggest_places("ch") == [] and FakeGoogle.calls == [])
    reset()
    picked = places.resolve_place("ChIJlandmark_charmi1")
    check("picking a suggestion = exactly 1 Place Details call", len(FakeGoogle.calls) == 1 and FakeGoogle.calls[0][0] == "GET"
          and "/v1/places/ChIJlandmark_charmi1" in FakeGoogle.calls[0][1] and picked["name"] == "Charminar"
          and abs(picked["latitude"] - 17.3616) < 1e-6, (len(FakeGoogle.calls), picked))
    reset()
    check("picking a place outside India -> None", places.resolve_place("ChIJeiffel_paris_001") is None)
    check("bad place ID -> None, no call", places.resolve_place("../etc") is None and len(FakeGoogle.calls) == 1)
    reset()
    try:
        places.resolve_place("ChIJdetails_quota_01")
        check("quota on Place Details (picking) -> MapSearchUnavailable", False)
    except places.MapSearchUnavailable:
        check("quota on Place Details (picking) -> MapSearchUnavailable", True)
    check("Place Details paused", gms.cache.d.get(gms.pause_key("details")) is True)
    reset()
    try:
        places.suggest_places("quota please")
        check("quota on autocomplete (typing) -> MapSearchUnavailable", False)
    except places.MapSearchUnavailable:
        check("quota on autocomplete (typing) -> MapSearchUnavailable", True)
    reset()
    try:
        places.search_places("quota please")
        check("search_places raises MapSearchUnavailable", False)
    except places.MapSearchUnavailable:
        check("search_places raises MapSearchUnavailable", True)
    check("quota results are not cached", not any(k.startswith("places:textsearch") for k in gms.cache.d))

    reset()
    r = client.get("/api/places/search", params={"q": "quota please"})
    check("REST /api/places/search -> 503 with a plain message", r.status_code == 503
          and r.json().get("detail", "").startswith("Map search"), (r.status_code, r.text[:120]))
    reset()
    r = client.get("/api/places/search", params={"q": "Charminar"})
    check("REST search: landmark first", r.status_code == 200 and r.json()[0]["name"] == "Charminar")
    with client.websocket_connect("/ws/app") as ws:
        def call(action, payload):
            ws.send_json({"id": "m1", "action": action, "payload": payload})
            while True:
                frame = ws.receive_json()
                if frame.get("id") == "m1":
                    return frame
        f = call("places:search", {"query": "paused please"})
        check("WS places:search -> 503 + 'Map search ...' message", f["status"] == 503 and str(f["error"]).startswith("Map search"),
              (f.get("status"), f.get("error")))
        reset()
        f = call("places:search", {"query": "Charminar"})
        check("WS places:search: landmark first, JSON list as before", f["status"] == 200 and isinstance(f["data"], list)
              and f["data"][0]["name"] == "Charminar")
        reset()
        f = call("places:suggest", {"query": "Charminar"})
        check("WS places:suggest: suggestions, 1 autocomplete call", f["status"] == 200 and len(f["data"]) == 2
              and len(FakeGoogle.calls) == 1, (f.get("status"), len(FakeGoogle.calls)))
        f = call("places:resolve", {"place_id": "ChIJlandmark_charmi1"})
        check("WS places:resolve: the picked place with coordinates, 1 Details call", f["status"] == 200
              and f["data"]["name"] == "Charminar" and f["data"]["latitude"] and len(FakeGoogle.calls) == 2, f.get("data"))
        f = call("places:resolve", {"place_id": "ChIJeiffel_paris_001"})
        check("WS places:resolve outside India -> 404", f["status"] == 404)
        reset()
        f = call("places:suggest", {"query": "quota please"})
        check("WS places:suggest quota -> 503 'Map search ...'", f["status"] == 503 and str(f["error"]).startswith("Map search"))
    r = client.get("/api/places/autocomplete", params={"q": "quota please"})
    check("unused /api/places/autocomplete removed (stage 4)", r.status_code in (404, 405), r.status_code)

    # ---------------- voice
    reset()
    t = lookups.search_place("quota please", "hi", show=True)
    check("voice: quota -> 'Map search abhi available nahi hai.', nothing on screen",
          t.reply_text == "Map search abhi available nahi hai." and t.ui_actions == [] and t.pending_actions == []
          and t.error_code == "maps_unavailable" and t.google_calls == 1, (t.reply_text, t.google_calls))
    t = lookups.search_place("quota please", "en", show=True)
    check("voice: quota (English); paused -> 0 calls", t.reply_text == "Map search isn't available right now." and t.google_calls == 0)
    reset()
    t = lookups.get_weather("quota please", "today", "hi", forecast_fn=lambda *a: (_ for _ in ()).throw(AssertionError("called")))
    check("voice weather: quota -> same reply, forecast not called", t.reply_text == "Map search abhi available nahi hai.")

    reset()
    t = lookups.search_place("Charminar", "hi", show=True)
    check("voice: landmark shown on the map", t.action == "map_focus" and t.ui_actions[0]["name"] == "Charminar"
          and t.google_calls == 1, (t.reply_text, t.google_calls))
    res = agent._from_tool(t)
    check("agent result carries the Google call count (turn log)", res.google_calls == 1)

    reset()
    t = lookups.search_place("Varanasi ghat", "hi", show=True)
    check("voice: ambiguous -> short choice, nothing shown yet", t.action == "place_ask" and t.ui_actions == []
          and t.pending_actions == [] and t.reply_text == "Dashashwamedh Ghat, Assi Ghat ya Manikarnika Ghat?", t.reply_text)
    t = lookups.search_place("Varanasi ghat", "en", show=False)
    check("voice: ambiguous (English)", t.reply_text == "Did you mean Dashashwamedh Ghat, Assi Ghat or Manikarnika Ghat?", t.reply_text)

    only_shop = [{"id": "s1", "name": "Minar Xerox", "city": "Pathar Gatti, Hyderabad, Telangana, India",
                  "latitude": 17.36, "longitude": 78.47, "types": STORE}]
    t = lookups.search_place("minar", "hi", show=True, search_fn=lambda q: only_shop)
    check("voice: only a shop -> not opened by default; shown only after 'haan'", t.action == "where" and t.ui_actions == []
          and t.pending_actions and "Map par dikhaun?" in t.reply_text, t.reply_text)

    # ---------------- logs: count only, never the query or key
    reset()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        places.search_places_detailed("Charminar")
        places.search_places_detailed("quota please")
        places.search_places_detailed("Charminar")
    log = buf.getvalue()
    check("search log has google_calls", "[PLACES SEARCH] google_calls=1" in log and "google_calls=1" in log and "google_calls=0" in log, log.strip())
    check("search log has no query text and no key", "Charminar" not in log and "quota please" not in log
          and "test-key-not-real" not in log)

    # ---------------- reverse geocoding v4
    import asyncio
    reset()
    FakeGoogle.geocode = [(200, {"results": [
        {"formattedAddress": "XJ6F+MV Hyderabad", "addressComponents": [{"longText": "India", "types": ["country"]}]},
        {"formattedAddress": "Charminar, Hyderabad, Telangana 500002, India", "addressComponents": [
            {"longText": "Hyderabad", "types": ["locality", "political"]},
            {"longText": "Telangana", "types": ["administrative_area_level_1", "political"]},
            {"longText": "India", "types": ["country", "political"]}]}]})]
    g = asyncio.run(gms.reverse_geocode(17.3616, 78.4747))
    url = FakeGoogle.calls[0][1]
    check("reverse geocode uses Geocoding v4 (key in header, not URL)", "geocode.googleapis.com/v4/geocode/location/" in url
          and "key=" not in url and FakeGoogle.calls[0][2].get("X-Goog-Api-Key") == "test-key-not-real", url)
    check("v4 -> city/state, 1 call", g["city"] == "Hyderabad" and g["state"] == "Telangana" and len(FakeGoogle.calls) == 1, g)
    check("no Geocoding v3 URL anywhere", not any("maps/api/geocode" in c[1] for c in FakeGoogle.calls))
    reset()
    FakeGoogle.geocode = [QUOTA_429, (200, {"places": []})]
    g = asyncio.run(gms.reverse_geocode(12.97, 77.59))
    check("v4 quota -> nothing else called, no invented city", len(FakeGoogle.calls) == 1 and g["city"] == "Current Location", g)
    g = asyncio.run(gms.reverse_geocode(12.98, 77.60))
    check("geocode paused -> no call at all", len(FakeGoogle.calls) == 1 and g["city"] == "Current Location")
    FakeGoogle.geocode = []

# ---------------- Google only
src = (BACKEND_DIR / "places.py").read_text(encoding="utf-8") + (BACKEND_DIR / "services" / "google_maps_service.py").read_text(encoding="utf-8")
# Other providers' hosts, split so a repo-wide grep for their names stays empty (map stage 4).
OTHER_HOSTS = ["nomi" + "natim.", "over" + "pass-api", "basemaps." + "car" + "tocdn", "photon.ko" + "moot", "api.map" + "box"]
check("no other map provider in the search code", not any(w in src.lower() for w in OTHER_HOSTS))

client.__exit__(None, None, None)
print(f"\n{sum(results)}/{len(results)} passed", flush=True)
sys.exit(0 if all(results) else 1)
