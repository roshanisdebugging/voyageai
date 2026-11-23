"""
Voice "category near a place" (search_nearby): "Hawa Mahal ke paas achha restaurant dikhao", "India Gate ke paas cafe",
"achha restaurant dikhao". App DB = SQLite, Redis = local, OpenAI and Google Text Search simulated (no real calls).
Checks: ONE Text Search per request (never Place Details), the query / includedType / locationBias sent, the ranking
(category first, the landmark itself dropped, same-name merge), the map_results ui action, at most three names spoken,
where the search happens (landmark > open trip > device location > one question), the quota message, and that a
named place still goes through search_places.
Run from backend/: python -m tests.test_voice_nearby
"""
import json
import os
import sys
import tempfile
import uuid
from datetime import timedelta
from pathlib import Path
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
SCRATCH = tempfile.mkdtemp(prefix="voyageai_test_")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

import database  # noqa: E402

database.engine = create_engine(f"sqlite:///{os.path.join(SCRATCH, 'nearby.db')}", connect_args={"check_same_thread": False})
database.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=database.engine)

import main  # noqa: E402,F401  (registers all models)
import openai_client  # noqa: E402
import places  # noqa: E402
from models_trip import TripModel  # noqa: E402
from redis_client import redis_conn  # noqa: E402
from services import google_maps_service as gms  # noqa: E402
from trip_lifecycle import today_ist  # noqa: E402
from voice import agent  # noqa: E402
from voice.tools import actions as A  # noqa: E402
from voice.tools import lookups  # noqa: E402

database.Base.metadata.create_all(bind=database.engine)

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail != "" else ""), flush=True)


USER = f"usr_nb_{uuid.uuid4().hex[:8]}"
TODAY = today_ist()
ME = (26.9124, 75.7873)   # the device, Jaipur


def add_trip(user, dest, lat, lng):
    tid = f"trip_{uuid.uuid4().hex[:10]}"
    with database.SessionLocal() as db:
        db.add(TripModel(id=tid, user_id=user, title=f"{dest} Trip", status="PLANNING",
                         start_date=(TODAY + timedelta(days=1)).isoformat(), end_date=(TODAY + timedelta(days=3)).isoformat(),
                         total_days=3, destination_json=json.dumps({"name": dest, "country": "India", "latitude": lat, "longitude": lng}),
                         travelers_json="[]", created_at="2026-11-01", updated_at="2026-11-01"))
        db.commit()
    return tid


def place(pid, name, lat, lng, types, rating=None, address="Jaipur, Rajasthan, India"):
    out = {"id": pid, "place_id": pid, "name": name, "city": address, "region": address, "country": "India",
           "latitude": lat, "longitude": lng, "displayName": address, "types": types}
    if rating is not None:
        out["rating"] = rating
    return out


RESTAURANTS = [
    place("ChIJhawaMahal0001", "Hawa Mahal", 26.9239, 75.8267, ["tourist_attraction", "historical_landmark"], 4.5),
    place("ChIJtattoo00000001", "Tattoo Cafe & Lounge", 26.9241, 75.8270, ["restaurant", "cafe", "food"], 4.4),
    place("ChIJwindview000001", "Wind View Cafe", 26.9238, 75.8265, ["restaurant", "food"], 4.3),
    place("ChIJlmb00000000001", "LMB", 26.9220, 75.8240, ["restaurant", "food"], 4.1),
    place("ChIJlmb00000000002", "LMB", 26.9221, 75.8241, ["restaurant", "food"], 4.1),       # same place again
    place("ChIJparkJal0000001", "Ram Niwas Garden", 26.9110, 75.8190, ["park"]),               # not a restaurant
    place("ChIJdubai000000001", "Dubai Restaurant", 25.2048, 55.2708, ["restaurant"], 4.9),   # outside India
    place("ChIJsuvarna0000001", "Suvarna Mahal", 26.9250, 75.8100, ["restaurant", "food"]),
]


class FakeTextSearch:
    """Stands in for google_maps_service.text_search_places; records every call (= one Google request)."""
    calls = []
    answer = RESTAURANTS
    raise_quota = False

    async def __call__(self, query, counter=None, **kw):
        FakeTextSearch.calls.append({"query": query, **kw})
        if counter is not None:
            counter.count += 1
        if FakeTextSearch.raise_quota:
            raise gms.GoogleQuotaError("textsearch")
        return [dict(r) for r in FakeTextSearch.answer]


class FakeLLM:
    queue = []

    def __call__(self, messages, tools, **kw):
        FakeLLM.last_tools = tools
        FakeLLM.last_messages = messages
        name, args = FakeLLM.queue.pop(0)
        return {"content": None, "tool_calls": [{"name": name, "arguments": args}]}


def details_forbidden(*a, **k):
    raise AssertionError("Place Details must not be called by search_nearby")


def run(text, tool_args, *, trip=None, location=None, lang="hi", conv=None, tool="search_nearby"):
    FakeTextSearch.calls = []
    FakeLLM.queue = [(tool, tool_args)]
    return agent.run_agent(text, lang, user_id=USER, conversation_id=conv or f"conv_nb_{uuid.uuid4().hex[:6]}",
                           screen="/home", trip=trip, redis_conn=redis_conn, location=location)


patches = [mock.patch.object(gms, "text_search_places", FakeTextSearch()),
           mock.patch.object(openai_client, "chat_tools", FakeLLM())]
for name in ("get_place_details", "place_details", "get_place_details_full"):
    if hasattr(gms, name):
        patches.append(mock.patch.object(gms, name, details_forbidden))
for p in patches:
    p.start()

# ---------------- the tool and the prompt
check("search_nearby is offered next to search_places", {"search_nearby", "search_places"} <= agent.TOOL_NAMES)
nearby_schema = next(t for t in agent.TOOLS if t["function"]["name"] == "search_nearby")["function"]["parameters"]
check("search_nearby: category required, near optional", nearby_schema["required"] == ["category"]
      and "near" in nearby_schema["properties"])
prompt = agent.build_system_prompt("/home", None)
check("prompt: kind + place -> search_nearby, never search_places on the landmark alone",
      "ALWAYS use\n  search_nearby, NEVER search_places on the landmark alone" in prompt
      and "Hawa Mahal ke paas achha restaurant dikhao" in prompt)

# ---------------- (a) category + landmark
r = run("Hawa Mahal ke paas achha restaurant dikhao", {"category": "good restaurant", "near": "Hawa Mahal Jaipur"})
call = FakeTextSearch.calls[0] if FakeTextSearch.calls else {}
check("(a) exactly ONE Text Search call", len(FakeTextSearch.calls) == 1, len(FakeTextSearch.calls))
check("(a) query 'good restaurants near Hawa Mahal Jaipur', includedType restaurant, ratings asked",
      call.get("query") == "good restaurants near Hawa Mahal Jaipur" and call.get("included_type") == "restaurant"
      and call.get("with_rating") is True and call.get("bias") is None, call)
ra = next((a for a in r.ui_actions if a.get("type") == "map_results"), {})
names = [p["name"] for p in ra.get("places", [])]
check("(a) chip title 'Hawa Mahal ke paas restaurants'", ra.get("title") == "Hawa Mahal ke paas restaurants", ra.get("title"))
check("(a) map_results then navigate /map", [a["type"] for a in r.ui_actions] == ["map_results", "navigate"]
      and r.ui_actions[1]["to"] == "/map" and r.action == "map_results", r.ui_actions)
check("(a) the landmark itself, the duplicate and the place outside India are dropped; restaurants first",
      names == ["Tattoo Cafe & Lounge", "Wind View Cafe", "LMB", "Suvarna Mahal", "Ram Niwas Garden"], names)
first = ra["places"][0] if ra.get("places") else {}
check("(a) each place has name, lat/lng, place id, rating, category", first.get("place_id") == "ChIJtattoo00000001"
      and first.get("rating") == 4.4 and first.get("category") == "restaurant" and abs(first["lat"] - 26.9241) < 1e-9, first)
check("(a) at most 6 places on the map", len(ra.get("places", [])) <= 6)
check("(a) spoken: three names only, in Hinglish",
      r.reply_text == "Hawa Mahal ke paas ye restaurants mile: Tattoo Cafe & Lounge, Wind View Cafe, LMB. Map par dikha diye.",
      r.reply_text)
check("(a) the reply never names a fourth place", "Suvarna" not in r.reply_text)
r_en = run("good restaurants near India Gate", {"category": "cafe", "near": "India Gate Delhi"}, lang="en")
check("(a) English: 'Cafes near India Gate Delhi: ... Showing them on the map.'",
      r_en.reply_text.startswith("Cafes near India Gate Delhi: Tattoo Cafe & Lounge, Wind View Cafe, LMB.")
      and r_en.reply_text.endswith("Showing them on the map.") and "Hawa Mahal" not in r_en.reply_text
      and FakeTextSearch.calls[0]["included_type"] == "cafe", r_en.reply_text)

# a list leaves no single "this place": "yeh jagah save karo" must ask which one
conv = f"conv_nb_{uuid.uuid4().hex[:6]}"
A.remember_place(redis_conn, USER, conv, {"place_id": "ChIJoldPlace0001", "name": "Amber Fort", "address": "Jaipur"})
run("Hawa Mahal ke paas cafe", {"category": "cafe", "near": "Hawa Mahal Jaipur"}, conv=conv)
check("(a) after a list the remembered place is forgotten (save asks which one)", A._last_place(redis_conn, USER, conv) is None)

# ---------------- (b) category only, trip open -> the trip's destination
tid = add_trip(USER, "Jaipur", 26.9124, 75.7873)
trip = agent.TripInfo(title="Jaipur Trip", start_date=None, end_date=None, id=tid)
r = run("achha restaurant dikhao", {"category": "good restaurant", "near": None}, trip=trip, location=(19.07, 72.87))
call = FakeTextSearch.calls[0] if FakeTextSearch.calls else {}
check("(b) one call: 'good restaurants in Jaipur' biased to the trip's destination (not the device)",
      len(FakeTextSearch.calls) == 1 and call.get("query") == "good restaurants in Jaipur"
      and call.get("bias") == (26.9124, 75.7873, places.NEAR_BIAS_RADIUS_M), call)
check("(b) spoken 'Jaipur mein ye restaurants mile: ...'", r.reply_text.startswith("Jaipur mein ye restaurants mile: "), r.reply_text)
other = add_trip(f"usr_nb_other_{uuid.uuid4().hex[:6]}", "Goa", 15.29, 74.12)
r = run("achha restaurant dikhao", {"category": "restaurant"}, trip=agent.TripInfo("Goa", None, None, id=other))
check("(b) another user's trip is never used (no trip, no location -> one question, no call)",
      r.error_code == "no_area" and FakeTextSearch.calls == [], r.reply_text)

# ---------------- (c) category only, no trip
r = run("achha restaurant dikhao", {"category": "good restaurant"})
check("(c) no trip, no location -> ONE short question, no Google call",
      r.reply_text == "Kis jagah ke paas dhoondhun?" and r.error_code == "no_area" and FakeTextSearch.calls == []
      and r.ui_actions == [], r.reply_text)
r = run("where can I find a good cafe", {"category": "cafe"}, lang="en")
check("(c) English question", r.reply_text == "Near which place should I look?", r.reply_text)
r = run("paas mein ATM kahan hai", {"category": "atm"}, location=ME)
call = FakeTextSearch.calls[0] if FakeTextSearch.calls else {}
check("(c') no trip but the device location -> 'ATMs' biased to the device",
      call.get("query") == "ATMs" and call.get("included_type") == "atm" and call.get("bias") == (ME[0], ME[1], places.NEAR_BIAS_RADIUS_M), call)
check("(c') spoken 'Aapke paas ye ATMs mile: ...'", r.reply_text.startswith("Aapke paas ye ATMs mile: "), r.reply_text)
r = run("restaurant dikhao", {"category": ""})
check("no category -> asks what to look for, no call", r.error_code == "no_category" and FakeTextSearch.calls == [], r.reply_text)

# ---------------- (d) a named place only still uses search_places
FakeTextSearch.answer = [place("ChIJhawaMahal0001", "Hawa Mahal", 26.9239, 75.8267, ["tourist_attraction", "historical_landmark"])]
r = run("Hawa Mahal dikhao", {"query": "Hawa Mahal Jaipur", "show": True}, tool="search_places")
call = FakeTextSearch.calls[0] if FakeTextSearch.calls else {}
check("(d) 'Hawa Mahal dikhao' -> search_places: one plain Text Search (no type, no bias, no rating), one pin",
      len(FakeTextSearch.calls) == 1 and call.get("query") == "Hawa Mahal Jaipur" and not call.get("included_type")
      and not call.get("bias") and not call.get("with_rating") and r.action == "map_focus"
      and [a["type"] for a in r.ui_actions] == ["map_focus", "navigate"], (call, r.action))
FakeTextSearch.answer = RESTAURANTS

# ---------------- (e) quota / paused key
FakeTextSearch.raise_quota = True
r = run("Hawa Mahal ke paas restaurant", {"category": "restaurant", "near": "Hawa Mahal Jaipur"})
check("(e) quota -> the map search message 'Map search abhi available nahi hai.', nothing on the map",
      r.reply_text == lookups.MAPS_UNAVAILABLE["hi"] == "Map search abhi available nahi hai."
      and r.error_code == "maps_unavailable" and r.ui_actions == [], r.reply_text)
r = run("cafe near India Gate", {"category": "cafe", "near": "India Gate"}, lang="en")
check("(e) English quota message", r.reply_text == lookups.MAPS_UNAVAILABLE["en"], r.reply_text)
FakeTextSearch.raise_quota = False
FakeTextSearch.answer = []
r = run("Hawa Mahal ke paas petrol pump", {"category": "petrol pump", "near": "Hawa Mahal Jaipur"})
check("nothing found -> says so, no map", r.reply_text == "Hawa Mahal Jaipur ke paas koi petrol pumps nahi mile."
      and r.ui_actions == [] and r.error_code == "not_found", r.reply_text)
FakeTextSearch.answer = RESTAURANTS

# ---------------- the real Google call shape (HTTP mocked): one request, field mask with rating, includedType, bias
for p in patches:
    p.stop()


class Resp:
    status_code = 200

    def json(self):
        return {"places": [{"id": "ChIJx", "displayName": {"text": "Cafe X"}, "formattedAddress": "Jaipur",
                            "location": {"latitude": 26.92, "longitude": 75.82}, "types": ["cafe"],
                            "rating": 4.6, "userRatingCount": 120}]}


sent = []


class FakeClient:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):
        sent.append({"url": url, "mask": headers.get("X-Goog-FieldMask"), "body": json})
        return Resp()


gms.cache.d.clear() if hasattr(gms.cache, "d") else None
for k in redis_conn.scan_iter("places:textsearch:*cafes near unit test*"):
    redis_conn.delete(k)
with mock.patch.object(gms, "GOOGLE_MAPS_SERVER_KEY", "test-key"), mock.patch.object(gms.httpx, "AsyncClient", FakeClient), \
        mock.patch.object(gms, "is_paused", mock.AsyncMock(return_value=False)):
    found = places.search_category("cafe", near="unit test place", bias=(26.9, 75.8))
body = sent[0]["body"] if sent else {}
check("Google: one Text Search request with rating fields, includedType and a locationBias circle",
      len(sent) == 1 and sent[0]["url"] == gms.TEXT_SEARCH_URL and "places.rating" in sent[0]["mask"]
      and body.get("includedType") == "cafe" and body.get("textQuery") == "cafes near unit test place"
      and body.get("locationBias", {}).get("circle", {}).get("radius") == float(places.NEAR_BIAS_RADIUS_M), sent)
check("Google: rating kept on the result", found.results and found.results[0].get("rating") == 4.6, found.results)
for k in redis_conn.scan_iter("places:textsearch:*cafes near unit test*"):
    redis_conn.delete(k)

for k in redis_conn.scan_iter(f"voice:*{USER}*"):
    redis_conn.delete(k)
print(f"\n{sum(results)}/{len(results)} passed", flush=True)
sys.exit(0 if all(results) else 1)
