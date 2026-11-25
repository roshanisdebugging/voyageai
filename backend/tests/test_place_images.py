"""
Real place pictures (image_service.py, trips_service highlights, media_service covers, GET /api/place-photo).
Google, Wikipedia and Pexels are all simulated: no network. image_service's Redis is an in-memory fake; only the
rate limiter of /api/place-photo uses the local Redis (its rl:* keys are removed, like the other tests).
Run from backend/: python -m tests.test_place_images
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

import dotenv

dotenv.load_dotenv = lambda *a, **k: None
os.environ["DATABASE_URL"] = "postgresql://x:y@127.0.0.1:1/none"
os.environ["AI_PROVIDER"] = "mock"
os.environ["GOOGLE_MAPS_SERVER_KEY"] = "test-key-not-real"
os.environ["PEXELS_API_KEY"] = "pexels-test-key-not-real"
os.environ["GOOGLE_IMAGES_ENABLED"] = "true"       # sections 1-6: the Google path; section 7: the default (off)
for old in ("GOOGLE_MAPS_API_KEY", "GOOGLE_MAP_DEMO_KEY"):
    os.environ.pop(old, None)

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)
SCRATCH = tempfile.mkdtemp(prefix="voyageai_test_")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

import database  # noqa: E402

database.engine = create_engine(f"sqlite:///{os.path.join(SCRATCH, 'images.db')}", connect_args={"check_same_thread": False})
database.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=database.engine)

import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from redis_client import redis_conn  # noqa: E402
import image_service as IS  # noqa: E402
import media_service as MS  # noqa: E402
import trips_service as TS  # noqa: E402

main.SessionLocal = database.SessionLocal
database.Base.metadata.create_all(bind=database.engine)
for key in redis_conn.scan_iter("rl:*"):
    redis_conn.delete(key)

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if (detail != "" and not cond) else ""), flush=True)


class FakeRedis:
    def __init__(self):
        self.d = {}
        self.touched = []         # every key read or written

    def get(self, k):
        self.touched.append(k)
        return self.d.get(k)

    def set(self, k, v, ex=None):
        self.touched.append(k)
        self.d[k] = v if isinstance(v, str) else str(v)

    def setex(self, k, ttl, v):
        self.d[k] = v

    def incr(self, k):
        self.touched.append(k)
        self.d[k] = str(int(self.d.get(k) or 0) + 1)
        return int(self.d[k])

    def expire(self, k, ttl):
        pass

    def keys_like(self, prefix):
        return [k for k in self.d if k.startswith(prefix)]


FAKE_REDIS = FakeRedis()
IS.redis_conn = FAKE_REDIS
TS.redis_conn = FAKE_REDIS


class Res:
    def __init__(self, status=200, body=None, headers=None, content=b""):
        self.status_code, self._body, self.headers, self._content = status, body, headers or {}, content
        self.text = json.dumps(body) if body is not None else ""

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body

    def iter_content(self, n):
        for i in range(0, len(self._content), n):
            yield self._content[i:i + n]


class Net:
    """Routes every outgoing request by host; records (method, url, params, headers)."""

    def __init__(self):
        self.calls = []
        self.google = lambda payload: Res(200, {"places": []})
        self.wiki_summary = {}            # page title -> body (missing -> 404)
        self.wiki_geo = []
        self.pexels = lambda params: Res(200, {"photos": []})
        self.media = lambda params: Res(200, {"photoUri": "https://lh3.googleusercontent.com/p/AF1Q-test=w800"})
        self.image = lambda url: Res(200, headers={"Content-Type": "image/jpeg"}, content=b"\xff\xd8\xff" + b"x" * 100)
        self.delay = 0.0

    def hosts(self):
        return [c[1].split("/")[2] for c in self.calls]

    def post(self, url, json=None, headers=None, timeout=None, **k):
        self.calls.append(("POST", url, json, headers or {}))
        if self.delay:
            time.sleep(self.delay)
        return self.google(json)

    def get(self, url, params=None, headers=None, timeout=None, **k):
        self.calls.append(("GET", url, params, headers or {}))
        if self.delay:
            time.sleep(self.delay)
        if "wikipedia.org/w/api.php" in url and (params or {}).get("list") == "geosearch":
            return Res(200, {"query": {"geosearch": self.wiki_geo}})
        if "wikipedia.org/w/api.php" in url:
            return Res(200, {"query": wiki_query(self.wiki_summary, params["titles"].split("|"))})
        if "api.pexels.com" in url:
            return self.pexels(params)
        if url.endswith("/media"):
            return self.media(params)
        if "googleusercontent.com" in url or "evil" in url:
            return self.image(url)
        raise AssertionError(f"unexpected URL {url}")


NET = Net()


def fresh(reset_cache=True):
    global NET
    NET = Net()
    FAKE_REDIS.touched.clear()
    if reset_cache:
        FAKE_REDIS.d.clear()
        IS._wiki_blocked_until = 0.0
    return NET


patch_get = mock.patch.object(IS.requests, "get", lambda *a, **k: NET.get(*a, **k))
patch_post = mock.patch.object(IS.requests, "post", lambda *a, **k: NET.post(*a, **k))
patch_get.start()
patch_post.start()

PHOTO_NAME = "places/ChIJ_HawaMahal_test01/photos/AUc7tXabcdefghijklmnop"


def google_place(name="Hawa Mahal", lat=26.9239, lng=75.8267, photos=True, pid="ChIJ_HawaMahal_test01"):
    p = {"id": pid, "displayName": {"text": name}, "location": {"latitude": lat, "longitude": lng}}
    if photos:
        p["photos"] = [{"name": PHOTO_NAME, "authorAttributions": [
            {"displayName": "Ravi Kumar", "uri": "https://maps.google.com/maps/contrib/123", "photoUri": "//lh3.x"}]}]
    return lambda payload: Res(200, {"places": [p]})


def wiki_page(title, lat=None, lon=None, img="https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/X.jpg/320px-X.jpg",
              width=4000, extract="", description="", typ="standard"):
    body = {"type": typ, "title": title, "description": description, "extract": extract,
            "thumbnail": {"source": img, "width": 320}, "originalimage": {"source": img.replace("/thumb", "").rsplit("/", 1)[0], "width": width},
            "content_urls": {"desktop": {"page": f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"}}}
    if lat is not None:
        body["coordinates"] = {"lat": lat, "lon": lon}
    return body


def wiki_query(known, titles):
    """The action API's answer (formatversion 2) for these titles, built from REST-style test pages."""
    pages, redirects = [], []
    for t in titles:
        body = known.get(t)
        if not body:
            pages.append({"title": t, "missing": True})
            continue
        if body["title"] != t:
            redirects.append({"from": t, "to": body["title"]})
        page = {"title": body["title"], "extract": body.get("extract", ""), "fullurl": body["content_urls"]["desktop"]["page"],
                "thumbnail": body["thumbnail"], "original": body["originalimage"],
                "pageprops": {"wikibase-shortdesc": body.get("description", "")}}
        if body.get("type") == "disambiguation":
            page["pageprops"]["disambiguation"] = ""
        if body.get("coordinates"):
            page["coordinates"] = [body["coordinates"]]
        pages.append(page)
    return {"redirects": redirects, "pages": pages}


PEXELS_HIT = lambda params: Res(200, {"photos": [{"url": "https://www.pexels.com/photo/thali-123/", "photographer": "Asha Rao",  # noqa: E731
                                                   "src": {"large": "https://images.pexels.com/photos/123/x.jpeg?w=940"}}]})

# ======================================================================= 1. prompt + stripping
captured = {}


def fake_llm(prompt, **kw):
    captured["prompt"] = prompt
    return json.dumps({
        "destination": "Jaipur", "overview": "Pink city.",
        "activities": [
            {"id": "act_1", "title": "Hawa Mahal", "category": "Sights", "coordinates": [26.9239, 75.8267],
             "photos": ["https://images.unsplash.com/photo-1599661046289-e31897846e41"], "image": "https://evil.example/x.jpg"},
            {"id": "act_2", "title": "Laxmi Mishthan Bhandar", "category": "Food", "coordinates": [26.92, 75.82],
             "photos": ["https://images.unsplash.com/photo-xyz"], "photoCredit": "made up"},
        ],
        "events": [{"id": "evt_1", "title": "Teej Festival", "category": "Festival",
                    "image": "https://images.unsplash.com/photo-1514525253161"}],
    })


import ai_provider  # noqa: E402

with mock.patch.object(ai_provider, "complete_json", fake_llm), \
        mock.patch.object(IS, "resolve_many", lambda items, **k: [None] * len(items)):
    out = TS.generate_live_destination_highlights("Jaipur")
p = captured.get("prompt", "")
check("prompt: no image URL anywhere (no http, no unsplash)", "http" not in p and "unsplash" not in p.lower(), p[:80])
check("prompt: no photos / image fields in the schema", '"photos"' not in p and '"image"' not in p)
dump = json.dumps(out)
check("LLM-returned URLs stripped (no unsplash / evil host in the response)", "unsplash" not in dump and "evil.example" not in dump)
check("no picture found -> activity photos [] and event image null", out["activities"][0]["photos"] == [] and out["events"][0]["image"] is None)
check("model's own photoCredit dropped", out["activities"][1]["photoCredit"] is None)
cached = json.loads(FAKE_REDIS.d["cache:spotlight:jaipur"])
check("highlights cache holds text only (no picture fields)", all("photos" not in a for a in cached["activities"])
      and all("image" not in e for e in cached["events"]))

# old cache entry with a model URL: dropped on read
FAKE_REDIS.d["cache:spotlight:jodhpur"] = json.dumps({"destination": "Jodhpur", "activities": [
    {"title": "Mehrangarh", "photos": ["https://images.unsplash.com/old"]}], "events": []})
with mock.patch.object(IS, "resolve_many", lambda items, **k: [None] * len(items)):
    out = TS.generate_live_destination_highlights("Jodhpur")
check("old cached entry: model URL removed on read", "unsplash" not in json.dumps(out) and out["activities"][0]["photos"] == [])

# ======================================================================= 2. order
fresh()
NET.google = google_place()
r = IS.resolve_place_image("Hawa Mahal", "Jaipur", 26.9239, 75.8267, "Sights")
check("1st: Google photo (source google)", r and r["source"] == "google", r)
check("Google: proxy URL, never the key", r and r["url"].startswith("/api/place-photo?name=places/") and "test-key" not in json.dumps(r))
check("Google: author credit + link, place_id only", r and r["credit"] == "Ravi Kumar" and r["credit_url"].startswith("https://")
      and r["place_id"] == "ChIJ_HawaMahal_test01")
check("Google: one Text Search, small field mask with photos, location bias", len(NET.calls) == 1
      and NET.calls[0][3].get("X-Goog-FieldMask") == "places.id,places.displayName,places.location,places.photos"
      and NET.calls[0][2]["locationBias"]["circle"]["radius"] == 5000.0 and NET.calls[0][2]["textQuery"] == "Hawa Mahal, Jaipur")
check("Google result not cached anywhere", not FAKE_REDIS.keys_like("img:v2:"))

fresh()
NET.google = google_place(photos=False)
NET.wiki_summary["Hawa Mahal, Jaipur"] = wiki_page("Hawa Mahal", 26.9239, 75.8267)
r = IS.resolve_place_image("Hawa Mahal", "Jaipur", 26.92, 75.82, "Sights")
check("2nd: Google has no photo -> Wikipedia", r and r["source"] == "wikipedia" and r["credit"] == "Wikimedia Commons (CC BY-SA)"
      and r["credit_url"] == "https://en.wikipedia.org/wiki/Hawa_Mahal", r)
check("Wikipedia: larger Commons thumbnail", r and "/960px-" in r["url"], r and r["url"])
check("Wikipedia: descriptive User-Agent sent", any("VoyageAI" in (c[3].get("User-Agent") or "") for c in NET.calls if "wikipedia" in c[1]))
check("Wikipedia link cached 7 days (link only)", len(FAKE_REDIS.keys_like("img:v2:place:")) == 1)
fresh(reset_cache=False)
NET.google = google_place(photos=False)
r2 = IS.resolve_place_image("Hawa Mahal", "Jaipur", 26.92, 75.82, "Sights")
check("cached Wikipedia link reused (Google still asked first, no Wikipedia call)", r2 == r
      and NET.hosts() == ["places.googleapis.com"], NET.hosts())

fresh()
NET.pexels = PEXELS_HIT
r = IS.resolve_place_image("Street food at Johari Bazaar", "Jaipur", 26.92, 75.82, "Food")
check("3rd: broad category (Food) -> Pexels after Google and Wikipedia", r and r["source"] == "pexels"
      and r["credit"] == "Photo by Asha Rao on Pexels" and r["credit_url"].startswith("https://www.pexels.com/"), r)
hosts = NET.hosts()
check("order: Google, then Wikipedia, then Pexels", hosts[0] == "places.googleapis.com" and hosts[-1] == "api.pexels.com"
      and "en.wikipedia.org" in hosts and hosts.index("en.wikipedia.org") < hosts.index("api.pexels.com"), hosts)
pex_call = [c for c in NET.calls if "pexels" in c[1]][0]
check("Pexels: query = destination + broad category, key in a header", pex_call[2]["query"] == "Jaipur food"
      and pex_call[3].get("Authorization") == "pexels-test-key-not-real")

fresh()
NET.pexels = PEXELS_HIT
r = IS.resolve_place_image("Hawa Mahal", "Jaipur", 26.92, 75.82, "Sights")
check("4th: named landmark, nothing found -> None", r is None, r)
check("named landmark NEVER asks Pexels", "api.pexels.com" not in NET.hosts(), NET.hosts())
check("negative result cached 1 day", json.loads(FAKE_REDIS.d[FAKE_REDIS.keys_like("img:v2:place:")[0]]) == "none")
for cat in ("Sights", "Culture", "Heritage", "Adventure", "Must Visit", None, ""):
    fresh()
    NET.pexels = PEXELS_HIT
    IS.resolve_place_image("Amber Fort", "Jaipur", 26.98, 75.85, cat)
    check(f"category {cat!r}: no Pexels", "api.pexels.com" not in NET.hosts())

fresh()
os.environ["PEXELS_API_KEY"] = ""
r = IS.resolve_place_image("Street food", "Jaipur", None, None, "Food")
check("no PEXELS_API_KEY: skipped without error", r is None and "api.pexels.com" not in NET.hosts())
os.environ["PEXELS_API_KEY"] = "pexels-test-key-not-real"

fresh()
NET.google = google_place(name="Some Other Hotel", lat=27.5, lng=76.5)
NET.wiki_summary["Hawa Mahal, Jaipur"] = wiki_page("Hawa Mahal", 26.9239, 75.8267)
r = IS.resolve_place_image("Hawa Mahal", "Jaipur", 26.92, 75.82, "Sights")
check("Google returned a different, far place -> its photo is not used", r and r["source"] == "wikipedia", r)

# ======================================================================= 3. Wikipedia matching
W = IS.wiki_summary_matches
check("wiki: coordinates 30 km away -> rejected", not W(wiki_page("Hawa Mahal", 27.19, 75.82), "Hawa Mahal", "Jaipur", (26.92, 75.82), 2.0))
check("wiki: coordinates within 2 km -> accepted", W(wiki_page("Hawa Mahal", 26.9239, 75.8267), "Hawa Mahal", "Jaipur", (26.92, 75.82), 2.0))
check("wiki: other title, no coordinates -> rejected", not W(wiki_page("Hawa Mahal Road"), "Hawa Mahal", "Jaipur", None, 2.0))
check("wiki: same title but another city -> rejected", not W(wiki_page("City Palace", extract="City Palace is in Udaipur, Rajasthan."),
                                                           "City Palace", "Jaipur", None, 2.0))
check("wiki: same title and the city is mentioned -> accepted", W(wiki_page("City Palace", extract="A palace complex in Jaipur."),
                                                                 "City Palace", "Jaipur", None, 2.0))
check("wiki: disambiguation page -> rejected", not W(wiki_page("Hawa Mahal", typ="disambiguation", extract="Jaipur"), "Hawa Mahal", "Jaipur", None, 2.0))
fresh()
NET.wiki_summary["Hawa Mahal, Jaipur"] = wiki_page("Hawa Mahal", 26.9239, 75.8267,
                                                   img="https://upload.wikimedia.org/wikipedia/en/thumb/a/ab/Logo.png/320px-Logo.png")
check("wiki: non-free en.wikipedia image -> not used", IS.resolve_place_image("Hawa Mahal", "Jaipur", 26.92, 75.82, "Sights") is None)
fresh()
NET.wiki_summary["Hawa Mahal, Jaipur"] = wiki_page("Hawa Mahal", 26.9239, 75.8267,
                                                   img="https://thumb.wikimedia.org/wikipedia/commons/thumb/a/ab/X.jpg/330px-X.jpg")
r = IS.resolve_place_image("Hawa Mahal", "Jaipur", 26.92, 75.82, "Sights")
check("wiki: Commons file on thumb.wikimedia.org -> used", r and r["url"].startswith("https://thumb.wikimedia.org/wikipedia/commons/"), r)
check("wiki: lookalike host refused", IS._is_commons("https://upload.wikimedia.org.evil.example/wikipedia/commons/x.jpg") is False
      and IS._is_commons("http://upload.wikimedia.org/wikipedia/commons/x.jpg") is False)
fresh()
NET.wiki_summary["Hawa Mahal, Jaipur"] = wiki_page("Hawa Mahal", 27.30, 75.82)    # 40 km off
NET.wiki_geo = [{"title": "Jantar Mantar, Jaipur", "dist": 500}, {"title": "Hawa Mahal (palace)", "dist": 120}]
NET.wiki_summary["Hawa Mahal (palace)"] = wiki_page("Hawa Mahal (palace)")
r = IS.resolve_place_image("Hawa Mahal", "Jaipur", 26.92, 75.82, "Sights")
check("wiki geosearch: only a nearby page whose name matches is used", r and r["credit_url"].endswith("Hawa_Mahal_(palace)")
      and not any("Jantar" in json.dumps(c[2]) for c in NET.calls if c[2] and "titles" in c[2]), r)

check("names: 'Amber Fort' vs 'Jaigarh Fort' (only 'fort' shared) -> no", not IS.names_match("Amber Fort", "Jaigarh Fort", "Jaipur"))
check("names: 'Amber Fort' vs 'Kingdom of Amber' -> no", not IS.names_match("Amber Fort", "Kingdom of Amber", "Jaipur"))
check("names: 'Hawa Mahal' vs 'Hawa Mahal (palace)' -> yes", IS.names_match("Hawa Mahal", "Hawa Mahal (palace)", "Jaipur"))

fresh()
NET.wiki_summary["Amber Fort"] = wiki_page("Amer Fort", 26.9855, 75.8513, extract="Amer Fort is a fort in Amer, Jaipur.")
r = IS.resolve_place_image("Amber Fort", "Jaipur", 26.96, 75.84, "Sights")   # model's coordinates ~3 km off
check("wiki: exact name redirected (Amber Fort -> Amer Fort), Jaipur named, 3 km off -> accepted",
      r and r["credit_url"].endswith("/Amer_Fort"), r)
S = IS.wiki_summary_matches
far = IS._page_summary({"title": "Amer Fort", "coordinates": [{"lat": 27.2, "lon": 75.84}], "extract": "A fort in Jaipur."})
check("wiki: exact name but 27 km away -> rejected", not S(far, "Amber Fort", "Jaipur", (26.96, 75.84), 2.0, exact=True))
nocity = IS._page_summary({"title": "Teej", "extract": "Teej is a festival celebrated in India and Nepal."})
check("wiki: festival page naming India, no coordinates -> accepted for a broad category (loose)",
      S(nocity, "Teej Festival", "Jaipur", None, 2.0, exact=True, loose=True))
check("wiki: same page for a named place needs the city named -> rejected", not S(nocity, "Teej Festival", "Jaipur", None, 2.0, exact=True))

fresh()
for i in range(7):
    NET.wiki_summary[f"Spot {i}, Jaipur"] = wiki_page(f"Spot {i}", 26.92, 75.82)
found = IS.resolve_many([{"title": f"Spot {i}", "destination": "Jaipur", "lat": 26.92, "lng": 75.82, "category": "Sights"}
                         for i in range(7)])
title_queries = [c for c in NET.calls if c[2] and "titles" in c[2]]
check("7 places -> ONE batched Wikipedia query", len(title_queries) == 1 and all(f and f["source"] == "wikipedia" for f in found),
      (len(title_queries), found))

# ======================================================================= 4. failures never break highlights
fresh()
NET.delay = 1.5          # each provider call takes 1.5 s: Google + Wikipedia together miss the 2 s budget


def fake_llm_7(prompt, **kw):
    return json.dumps({"destination": "Udaipur", "overview": "Lakes.",
                       "activities": [{"id": f"a{i}", "title": f"Place {i}", "category": "Sights", "coordinates": [24.58, 73.68]} for i in range(8)],
                       "events": [{"id": "e1", "title": "Mewar Festival", "category": "Festival"}]})


NET.wiki_summary["Place 0, Udaipur"] = wiki_page("Place 0", 24.58, 73.68)
t0 = time.monotonic()
with mock.patch.object(ai_provider, "complete_json", fake_llm_7):
    out = TS.generate_live_destination_highlights("Udaipur")
took = time.monotonic() - t0
check("slow providers -> highlights still returned within ~2.5 s", len(out["activities"]) == 8 and took < 2.8, f"{took:.2f}s")
check("not ready in time -> placeholders (photos [], image null)", all(a["photos"] == [] for a in out["activities"])
      and out["events"][0]["image"] is None)
IS.wait_background()
cached = [json.loads(v) for k, v in FAKE_REDIS.d.items() if k.startswith("img:v2:")]
check("the slow lookup finished in the background and its link is cached",
      any(isinstance(c, dict) and c.get("source") == "wikipedia" for c in cached), cached)
NET.delay = 0.0
with mock.patch.object(ai_provider, "complete_json", fake_llm_7):
    out = TS.generate_live_destination_highlights("Udaipur")
check("next load: the cached picture is shown", out["activities"][0]["photoSource"] == "wikipedia"
      and out["activities"][0]["photos"][0].startswith("https://upload.wikimedia.org/"), out["activities"][0])

fresh()
NET.delay = 1.5
with mock.patch.object(IS, "BACKGROUND_TIMEOUT_S", 1.0):
    IS.resolve_place_image("Hawa Mahal", "Jaipur", 26.92, 75.82, "Sights")
    IS.wait_background()
check("a lookup past the background limit caches nothing", not FAKE_REDIS.keys_like("img:v2:"), FAKE_REDIS.keys_like("img:v2:"))
NET.delay = 0.0

fresh()
IS.resolve_many([{"title": f"P{i}", "destination": "X"} for i in range(12)])
IS.wait_background()
check("at most 7 lookups per highlights response", sum(1 for c in NET.calls if c[0] == "POST") == 7, len(NET.calls))

fresh()
with mock.patch.object(ai_provider, "complete_json", fake_llm_7), \
        mock.patch.object(IS, "resolve_many", mock.Mock(side_effect=RuntimeError("boom"))):
    FAKE_REDIS.d.clear()
    out = TS.generate_live_destination_highlights("Udaipur")
check("image_service crashing -> highlights still returned", len(out["activities"]) == 8 and out["activities"][0]["photos"] == [])

fresh()
NET.google = lambda payload: Res(500, {"error": {"status": "INTERNAL"}})
NET.wiki_summary = {}
NET.get = mock.Mock(side_effect=ConnectionError("down"))
check("network errors -> None, never raises", IS.resolve_place_image("Hawa Mahal", "Jaipur", 26.9, 75.8, "Sights") is None)

fresh()
NET.google = lambda payload: Res(429, {"error": {"status": "RESOURCE_EXHAUSTED", "message": "Quota exceeded per day"}})
IS.resolve_place_image("Hawa Mahal", "Jaipur", 26.9, 75.8, "Sights")
check("Google quota -> textsearch paused", FAKE_REDIS.get("gmaps:paused:textsearch") is not None)
NET.calls.clear()
IS.resolve_place_image("Amber Fort", "Jaipur", 26.98, 75.85, "Sights")
check("while paused, no Google call", "places.googleapis.com" not in NET.hosts(), NET.hosts())

fresh()
os.environ["IMAGE_GOOGLE_DAILY_CAP"] = "2"
NET.google = google_place()
for _ in range(3):
    IS.resolve_place_image("Hawa Mahal", "Jaipur", 26.92, 75.82, "Sights")
check("daily cap on Google picture lookups", sum(1 for h in NET.hosts() if h == "places.googleapis.com") == 2)
os.environ.pop("IMAGE_GOOGLE_DAILY_CAP", None)

fresh()
NET.wiki_summary["Hampi"] = {**wiki_page("Hampi", 15.335, 76.462), "type": "standard"}
NET.get_orig = NET.get
calls_503 = {"n": 0}


def wiki_503(url, **k):
    calls_503["n"] += 1
    return Res(503, {"error": "busy"}) if "wikipedia" in url else NET.get_orig(url, **k)


NET.get = wiki_503
check("Wikipedia 503 -> None", IS.resolve_cover_image("Hampi", "Karnataka", 15.33, 76.46) is None)
check("a 503 is not cached as 'no picture'", not FAKE_REDIS.keys_like("img:v2:"))

fresh()
NET.get = lambda url, **k: Res(429, {"error": "too many"}, headers={"Retry-After": "30"}) if "wikipedia" in url else Res(404, {})
NET.calls_seen = 0
check("Wikipedia 429 -> None", IS.resolve_place_image("Hawa Mahal", "Jaipur", 26.92, 75.82, "Sights") is None)
check("Wikipedia 429 -> cool-down set, nothing cached", FAKE_REDIS.get(IS.WIKI_COOLDOWN_KEY) is not None and not FAKE_REDIS.keys_like("img:v2:"))
wiki_hits = []
NET.get = lambda url, **k: wiki_hits.append(url) or Res(404, {})
IS.resolve_place_image("Amber Fort", "Jaipur", 26.98, 75.85, "Sights")
check("during the cool-down: no Wikipedia request at all", wiki_hits == [], wiki_hits)

fresh()
import threading  # noqa: E402
live = {"now": 0, "max": 0}
lock = threading.Lock()


def slow_wiki(url, **k):
    if "wikipedia" in url:
        with lock:
            live["now"] += 1
            live["max"] = max(live["max"], live["now"])
        time.sleep(0.15)
        with lock:
            live["now"] -= 1
    return Res(404, {})


NET.get = slow_wiki
IS.resolve_many([{"title": f"Fort {i}", "destination": "Jaipur", "lat": 26.9, "lng": 75.8, "category": "Sights"} for i in range(7)])
IS.wait_background()
check("Wikipedia: at most 2 requests at a time", 1 <= live["max"] <= 2, live)

# ======================================================================= 5. covers
fresh()
m = MS.media_service.resolve_cover_media({"name": "Goa", "latitude": 15.29, "longitude": 74.12})
check("cover: Goa keeps its catalog photo (with credit)", m["provider"] == "catalog" and "unsplash" in m["url"] and m["credit"] == "Unsplash")
check("cover: catalog needs no network", NET.calls == [])
NET.wiki_summary["Udaipur"] = wiki_page("Udaipur", 24.585, 73.712)
m = MS.media_service.resolve_cover_media({"name": "Udaipur", "region": "Rajasthan", "latitude": 24.58, "longitude": 73.71})
check("cover: Udaipur (Rajasthan) no longer gets Jaipur's Hawa Mahal", "1477587458883" not in m["url"])
check("cover: Udaipur -> its Wikipedia picture with credit", m["provider"] == "wikipedia" and m["credit"] == "Wikimedia Commons (CC BY-SA)"
      and m["creditUrl"].endswith("/Udaipur"), m)
check("cover: never Google", "places.googleapis.com" not in NET.hosts())
fresh()
NET.pexels = PEXELS_HIT
m = MS.media_service.resolve_cover_media({"name": "Nowhereville", "latitude": 22.0, "longitude": 80.0})
check("cover: no Wikipedia page -> Pexels (destination covers may use Pexels)", m["provider"] == "pexels"
      and [c for c in NET.calls if "pexels" in c[1]][0][2]["query"] == "Nowhereville India", m)
fresh()
m = MS.media_service.resolve_cover_media({"name": "Nowhereville", "latitude": 22.0, "longitude": 80.0})
check("cover: nothing found -> no picture (placeholder), not a random photo", m == {"url": "", "alt": "Nowhereville", "provider": "none"}, m)

# ======================================================================= 6. /api/place-photo proxy
fresh()
good_url = IS.photo_proxy_url(PHOTO_NAME, 800)
with TestClient(main.app) as client:
    res = client.get(good_url)
    check("proxy: guest allowed (like other place endpoints) -> 200 image", res.status_code == 200
          and res.headers["content-type"] == "image/jpeg" and res.content.startswith(b"\xff\xd8"), res.status_code)
    check("proxy: Cache-Control private, 1 hour", res.headers.get("cache-control") == "private, max-age=3600")
    media_call = [c for c in NET.calls if c[1].endswith("/media")][0]
    img_call = [c for c in NET.calls if "googleusercontent" in c[1]][0]
    check("proxy: key only in the header of the Google media call", media_call[3].get("X-Goog-Api-Key") == "test-key-not-real"
          and "test-key" not in media_call[1] + json.dumps(media_call[2]))
    check("proxy: image download carries no key", "X-Goog-Api-Key" not in img_call[3] and "test-key" not in img_call[1])
    check("proxy: key never in the response", b"test-key" not in res.content and "test-key" not in json.dumps(dict(res.headers)))
    check("proxy: skipHttpRedirect + requested width", media_call[2] == {"maxWidthPx": 800, "skipHttpRedirect": "true"})

    NET.calls.clear()
    res = client.get(IS.photo_proxy_url(PHOTO_NAME, 800).replace("w=800", "w=99999"))
    check("proxy: width capped at 1600", res.status_code == 200 and [c for c in NET.calls if c[1].endswith("/media")][0][2]["maxWidthPx"] == 1600)
    NET.calls.clear()
    res = client.get(good_url.replace("w=800", "w=10"))
    check("proxy: tiny / non-numeric width -> 400", res.status_code == 400 and client.get(good_url.replace("w=800", "w=abc")).status_code == 400)

    bad = ["https://evil.example/x.jpg", "places/abc/photos/def", "places/ChIJ_HawaMahal_test01/photos/../../v1/places:searchText",
           "places/ChIJ_HawaMahal_test01/reviews/AUc7tXabcdefghijklmnop", "/places/ChIJ_HawaMahal_test01/photos/AUc7tXabcdefghijklmnop", ""]
    codes = []
    for name in bad:
        r = client.get("/api/place-photo", params={"name": name, "w": "800", "sig": IS.photo_signature(name)})
        codes.append(r.status_code)
    check("proxy: names not 'places/<id>/photos/<ref>' -> 400", all(c == 400 for c in codes), codes)
    check("proxy: bad names never reach Google", NET.calls == [])
    r = client.get("/api/place-photo", params={"name": PHOTO_NAME, "w": "800", "sig": "0" * 32})
    r2 = client.get("/api/place-photo", params={"name": PHOTO_NAME.replace("abc", "abd"), "w": "800",
                                                 "sig": IS.photo_signature(PHOTO_NAME)})
    check("proxy: wrong / missing signature -> 400 (no open proxy)", r.status_code == 400 and r2.status_code == 400
          and client.get("/api/place-photo", params={"name": PHOTO_NAME, "w": "800"}).status_code == 400 and NET.calls == [])

    NET.media = lambda params: Res(200, {"photoUri": "https://evil.example/steal"})
    check("proxy: photoUri outside googleusercontent -> 404, not fetched", client.get(good_url).status_code == 404
          and not any("evil" in c[1] for c in NET.calls))
    NET.media = lambda params: Res(200, {"photoUri": "https://lh3.googleusercontent.com/p/x"})
    NET.image = lambda url: Res(200, headers={"Content-Type": "text/html"}, content=b"<html>")
    check("proxy: non-image content -> 404", client.get(good_url).status_code == 404)
    NET.image = lambda url: Res(200, headers={"Content-Type": "image/jpeg"}, content=b"x" * (IS.PHOTO_MAX_BYTES + 10))
    check("proxy: over 4 MB -> 404", client.get(good_url).status_code == 404)
    NET.media = lambda params: Res(429, {"error": {"status": "RESOURCE_EXHAUSTED", "message": "per day"}})
    r = client.get(good_url)
    check("proxy: Google quota -> 503 + photo paused", r.status_code == 503 and FAKE_REDIS.get("gmaps:paused:photo") is not None)
    NET.calls.clear()
    check("proxy: while paused, no Google call", client.get(good_url).status_code == 503 and NET.calls == [])

# ======================================================================= 7. GOOGLE_IMAGES_ENABLED off (the default)
import contextlib  # noqa: E402
import io  # noqa: E402


def logged(fn):
    """(result, the [IMAGES] lines it printed)"""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        out_ = fn()
        IS.wait_background()
    return out_, [ln for ln in buf.getvalue().splitlines() if ln.startswith(("[IMAGES]", "[GOOGLE", "[PLACE PHOTO]"))]


def google_free():
    return (not any("google" in h for h in NET.hosts())
            and not any("gmaps:paused" in k or k.startswith("img:calls:") for k in FAKE_REDIS.touched))


for val, want in (("true", True), ("1", True), ("TRUE", True), ("false", False), ("0", False), ("", False), ("junk", False)):
    os.environ["GOOGLE_IMAGES_ENABLED"] = val
    check(f"flag {val!r} -> {want}", IS.google_images_enabled() is want)
os.environ.pop("GOOGLE_IMAGES_ENABLED")
check("flag unset -> off (the default)", IS.google_images_enabled() is False)

fresh()
NET.google = google_place()                                 # Google WOULD have a photo
NET.wiki_summary["Hawa Mahal, Jaipur"] = wiki_page("Hawa Mahal", 26.9239, 75.8267)
r = IS.resolve_place_image("Hawa Mahal", "Jaipur", 26.92, 75.82, "Sights")
check("off: named landmark -> Wikipedia first", r and r["source"] == "wikipedia", r)
check("off: no Google request, no gmaps:paused:* read or write, no Google counter", google_free(), (NET.hosts(), FAKE_REDIS.touched))

fresh()
NET.google, NET.pexels = google_place(), PEXELS_HIT
r = IS.resolve_place_image("Street food at Johari Bazaar", "Jaipur", 26.92, 75.82, "Food")
hosts = NET.hosts()
check("off: generic category -> Wikipedia, then Pexels", r and r["source"] == "pexels" and hosts[0] == "en.wikipedia.org"
      and hosts[-1] == "api.pexels.com" and google_free(), hosts)

fresh()
NET.google, NET.pexels = google_place(), PEXELS_HIT
r = IS.resolve_place_image("Amber Fort", "Jaipur", 26.98, 75.85, "Sights")
check("off: named landmark, nothing on Wikipedia -> None, never Pexels", r is None and "api.pexels.com" not in NET.hosts() and google_free(), NET.hosts())

fresh()
NET.google = google_place()
os.environ["PEXELS_API_KEY"] = ""
r = IS.resolve_place_image("Street food", "Jaipur", 26.92, 75.82, "Food")
os.environ["PEXELS_API_KEY"] = "pexels-test-key-not-real"
check("off: generic, no PEXELS_API_KEY -> None", r is None and "api.pexels.com" not in NET.hosts() and google_free(), NET.hosts())

fresh()
NET.google, NET.pexels = google_place(), PEXELS_HIT
m = MS.media_service.resolve_cover_media({"name": "Nowhereville", "latitude": 22.0, "longitude": 80.0})
check("off: covers unchanged (Wikipedia, then Pexels)", m["provider"] == "pexels" and google_free(), m)

fresh()
FAKE_REDIS.d["gmaps:paused:textsearch"] = "true"            # a pause set by place search: left alone
NET.wiki_summary["Hawa Mahal, Jaipur"] = wiki_page("Hawa Mahal", 26.9239, 75.8267)
IS.resolve_place_image("Hawa Mahal", "Jaipur", 26.92, 75.82, "Sights")
check("off: an existing pause flag is neither read nor changed", google_free() and FAKE_REDIS.d["gmaps:paused:textsearch"] == "true")

fresh()
found = IS._google_lookup("Hawa Mahal", "Jaipur", (26.92, 75.82), time.monotonic() + 2)
check("off: even a direct _google_lookup makes no request", found == (None, None) and NET.calls == [] and google_free())

fresh()
os.environ["GOOGLE_IMAGES_ENABLED"] = "true"
good_url = IS.photo_proxy_url(PHOTO_NAME, 800)
os.environ["GOOGLE_IMAGES_ENABLED"] = "false"
with TestClient(main.app) as client:
    res = client.get(good_url)
    check("off: /api/place-photo (an old link) -> 503, no Google call, no flag touched", res.status_code == 503 and NET.calls == [] and google_free(), res.status_code)
    check("off: a bad photo name is still 400", client.get("/api/place-photo", params={"name": "x", "w": "800", "sig": "x"}).status_code == 400)


# highlights: the log line, and a 429 that must not break them
def fake_llm_goa(prompt, **kw):
    return json.dumps({"destination": "Goa", "overview": "Beaches.",
                       "activities": [{"id": f"a{i}", "title": t, "category": c, "coordinates": [15.5, 73.91]} for i, (t, c) in enumerate(
                           [("Basilica of Bom Jesus", "Sights"), ("Fort Aguada", "Sights"), ("Goan fish thali", "Food"),
                            ("Se Cathedral", "Culture"), ("Chapora Fort", "Sights")])],
                       "events": [{"id": "e1", "title": "Shigmo", "category": "Festival"}, {"id": "e2", "title": "Goa Carnival", "category": "Festival"}]})


def goa():
    with mock.patch.object(ai_provider, "complete_json", fake_llm_goa):
        return TS.generate_live_destination_highlights("Goa")


fresh()
NET.google, NET.pexels = google_place(), PEXELS_HIT
NET.wiki_summary["Basilica of Bom Jesus, Goa"] = wiki_page("Basilica of Bom Jesus", 15.5009, 73.9116)
out, lines = logged(goa)
check("off: highlights log line keeps its format and adds google=off", len(lines) == 1 and lines[0].startswith("[IMAGES] 7 lookups in ")
      and lines[0].endswith("none 3, pexels 3, wikipedia 1, google=off"), lines)
check("off: no Google request for a whole highlights response", google_free(), NET.hosts())
os.environ["GOOGLE_IMAGES_ENABLED"] = "true"
fresh()
_, lines = logged(goa)
check("on: log line as before (no google=off)", len(lines) == 1 and lines[0].endswith("none 7"), lines)
os.environ["GOOGLE_IMAGES_ENABLED"] = "false"

fresh()
wiki_hits = []


def wiki_429(url, **k):
    if "wikipedia" in url:
        wiki_hits.append(url)
        return Res(429, {"error": "too many"}, headers={})
    return Res(404, {})


NET.get = wiki_429
t0 = time.monotonic()
out, lines = logged(goa)
check("429: highlights still returned, placeholders, no waiting", len(out["activities"]) == 5 and all(a["photos"] == [] for a in out["activities"])
      and time.monotonic() - t0 < 1.5, time.monotonic() - t0)
check("429: one request, one 429 log line (not one per place)", len(wiki_hits) == 1 and sum("429" in ln for ln in lines) == 1
      and len(lines) == 2, (len(wiki_hits), lines))
out, lines = logged(goa)
check("429: during the 60 s no Wikipedia request and no new 429 line", len(wiki_hits) == 1 and not any("429" in ln for ln in lines), lines)
FAKE_REDIS.d.pop(IS.WIKI_COOLDOWN_KEY, None)
check("429: the skip is in this process (Redis flag gone, still skipped)", IS.resolve_place_image("Fort X", "Goa", 15.5, 73.9, "Sights") is None and len(wiki_hits) == 1)
left = IS._wiki_blocked_until - time.monotonic()
check("429: the skip lasts 60 s", 55 < left <= 60, left)
check("429: nothing cached as 'no picture'", not FAKE_REDIS.keys_like("img:v2:"))
IS._wiki_blocked_until = time.monotonic() - 0.01            # 60 s later
IS.resolve_place_image("Fort X", "Goa", 15.5, 73.9, "Sights")
check("429: after 60 s Wikipedia is asked again", len(wiki_hits) == 2, len(wiki_hits))

# a 429 in the middle of the per-place lookups: the places already queued for a slot are skipped, one line
fresh()
wiki_hits.clear()


def geo_429(url, params=None, **k):
    wiki_hits.append(params)
    if (params or {}).get("list") == "geosearch":
        time.sleep(0.2)
        return Res(429, {"error": "too many"}, headers={"Retry-After": "5"})
    return Res(200, {"query": {"pages": []}})


NET.get = geo_429
out, lines = logged(goa)
geo = sum(1 for p_ in wiki_hits if (p_ or {}).get("list") == "geosearch")
check("429 mid-batch: at most the 2 running requests, the waiting ones are skipped", geo <= 2, geo)
check("429 mid-batch: one log line, highlights fine", sum("429" in ln for ln in lines) == 1 and len(out["activities"]) == 5, lines)

os.environ["WIKIMEDIA_USER_AGENT"] = "VoyageAI/1.0 (https://example.org/; contact@example.org)"
fresh()
IS.resolve_place_image("Hawa Mahal", "Jaipur", 26.92, 75.82, "Sights")
check("Wikipedia User-Agent: app name + contact from WIKIMEDIA_USER_AGENT", NET.calls and all(
    c[3].get("User-Agent") == "VoyageAI/1.0 (https://example.org/; contact@example.org)" for c in NET.calls if "wikipedia" in c[1]))
os.environ.pop("WIKIMEDIA_USER_AGENT")

for key in redis_conn.scan_iter("rl:*"):
    redis_conn.delete(key)
print(f"\n{sum(results)}/{len(results)} passed", flush=True)
os._exit(0 if all(results) else 1)
