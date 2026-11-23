"""
Voice "category near a place" (search_nearby): "Hawa Mahal ke paas achha restaurant dikhao", "India Gate ke paas cafe",
"achha restaurant dikhao". App DB = SQLite, Redis = local, OpenAI and Google Text Search simulated (no real calls).
Checks: ONE Text Search per request (never Place Details), the query / includedType / locationBias sent, the ranking
(category first, the landmark itself dropped, same-name merge; speech by rating and distance), the map_results ui
action, at most three names spoken with a rough distance from the device, where the search happens (a place the user
said > "near me" / no place = the device location > one question; the trip is only a soft hint for X, never the
default), the Food page only on request, the quota message, and that a named place still goes through search_places.
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
from voice import agent, pages  # noqa: E402
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
check("search_nearby: category required; near and near_me optional", nearby_schema["required"] == ["category"]
      and {"near", "near_me"} <= set(nearby_schema["properties"]))
prompt = " ".join(agent.build_system_prompt("/home", None).split())
check("prompt: kind + place -> search_nearby, never search_places on the landmark alone",
      "ALWAYS use search_nearby, NEVER search_places on the landmark alone" in prompt and "Howrah ke paas achha restaurant" in prompt)
check("prompt: the Food page only when asked for the page; 'khana kahan milega' is search_nearby",
      "navigate to food ONLY when the user asks for the page itself" in prompt and "navigate to food instead" not in prompt
      and "Asking where to eat is search_nearby, never navigate" in prompt)
check("prompt: never add the trip's city to near", "Do NOT add the open trip's city" in prompt)
check("pages: food meaning says page only", "ONLY when the user asks for the page itself" in pages.MEANINGS["food"])

TRIP_ID = add_trip(USER, "Jaipur", 26.9124, 75.7873)
TRIP = agent.TripInfo(title="Jaipur Trip", start_date=None, end_date=None, id=TRIP_ID)

# ---------------- (a) "mere aaspas khane ki achhi jagah" -> the device location
r = run("mere aaspas khane ki achhi jagah", {"category": "good restaurant", "near": None, "near_me": True},
        trip=TRIP, location=ME)
call = FakeTextSearch.calls[0] if FakeTextSearch.calls else {}
check("(a) ONE Text Search: 'good restaurants', 3 km bias around the device (not the trip), ratings asked",
      len(FakeTextSearch.calls) == 1 and call.get("query") == "good restaurants" and call.get("included_type") == "restaurant"
      and call.get("bias") == (ME[0], ME[1], places.NEAR_BIAS_RADIUS_M) and call.get("with_rating") is True, call)
check("(a) reply 'Aapke aaspas ye restaurants mile: A, lagbhag N kilometer; ...'",
      r.reply_text.startswith("Aapke aaspas ye restaurants mile: Tattoo Cafe & Lounge, lagbhag 4.1 kilometer; ")
      and r.reply_text.endswith("Map par dikha diye.") and r.reply_text.count("lagbhag") == 3, r.reply_text)
ra = next((a for a in r.ui_actions if a.get("type") == "map_results"), {})
names = [p["name"] for p in ra.get("places", [])]
check("(a) map_results then navigate /map; title 'Aapke aaspas restaurants'",
      [a["type"] for a in r.ui_actions] == ["map_results", "navigate"] and r.ui_actions[1]["to"] == "/map"
      and ra.get("title") == "Aapke aaspas restaurants", (r.ui_actions[1:], ra.get("title")))
check("(a) the landmark itself is kept only if near; duplicate + outside India dropped; restaurants first",
      names[:4] == ["Tattoo Cafe & Lounge", "Wind View Cafe", "LMB", "Suvarna Mahal"] and "Dubai Restaurant" not in names
      and names.count("LMB") == 1 and len(names) <= 6, names)
first = ra["places"][0] if ra.get("places") else {}
check("(a) each place has name, lat/lng, place id, rating, category", first.get("place_id") == "ChIJtattoo00000001"
      and first.get("rating") == 4.4 and first.get("category") == "restaurant", first)
check("(a) at most three names spoken", "Suvarna" not in r.reply_text)
r = run("restaurants near me", {"category": "restaurant", "near": "near me"}, location=ME, lang="en")
check("(a) 'near me' written into near counts as the device; English 'Restaurants around you: ..., about 4.1 km; ...'",
      FakeTextSearch.calls[0].get("bias") == (ME[0], ME[1], places.NEAR_BIAS_RADIUS_M)
      and r.reply_text.startswith("Restaurants around you: Tattoo Cafe & Lounge, about 4.1 km; "), r.reply_text)
r = run("mere aaspas ATM", {"category": "atm", "near_me": True}, trip=TRIP)
check("(a) near me without a location -> 'Kahan ke paas dekhun?', no call (never the trip)",
      r.reply_text == "Kahan ke paas dekhun?" and r.error_code == "no_area" and FakeTextSearch.calls == [], r.reply_text)

# ---------------- (b) "Howrah ke paas achha restaurant" -> Howrah, not the device
r = run("Howrah ke paas achha restaurant", {"category": "good restaurant", "near": "Howrah"}, trip=TRIP, location=ME)
call = FakeTextSearch.calls[0] if FakeTextSearch.calls else {}
check("(b) query 'good restaurants near Howrah' (the trip's city NOT added); never biased to the device",
      call.get("query") == "good restaurants near Howrah" and call.get("bias") != (ME[0], ME[1], places.NEAR_BIAS_RADIUS_M), call)
check("(b) the open trip is only a soft 50 km hint", call.get("bias") == (26.9124, 75.7873, places.TRIP_HINT_RADIUS_M), call.get("bias"))
check("(b) reply 'Howrah ke paas ye restaurants mile: A, B, C.' (no distance: Howrah's own position isn't fetched)",
      r.reply_text == "Howrah ke paas ye restaurants mile: Tattoo Cafe & Lounge, Wind View Cafe, LMB. Map par dikha diye.", r.reply_text)
r = run("Howrah ke paas achha restaurant", {"category": "good restaurant", "near": "Howrah"}, location=ME)
check("(b) no trip open: no bias at all (X wins over the device)", FakeTextSearch.calls[0].get("bias") is None)

# ---------------- (c) "Hawa Mahal ke paas cafe" -> Hawa Mahal
r = run("Hawa Mahal ke paas cafe", {"category": "cafe", "near": "Hawa Mahal"}, trip=TRIP, location=ME)
call = FakeTextSearch.calls[0] if FakeTextSearch.calls else {}
check("(c) query 'cafes near Hawa Mahal', includedType cafe", call.get("query") == "cafes near Hawa Mahal"
      and call.get("included_type") == "cafe", call)
ra = next((a for a in r.ui_actions if a.get("type") == "map_results"), {})
check("(c) Hawa Mahal itself is not a result; reply 'Hawa Mahal ke paas ye cafes mile: ...'",
      "Hawa Mahal" not in [p["name"] for p in ra.get("places", [])] and r.reply_text.startswith("Hawa Mahal ke paas ye cafes mile: "),
      r.reply_text)
conv = f"conv_nb_{uuid.uuid4().hex[:6]}"
A.remember_place(redis_conn, USER, conv, {"place_id": "ChIJoldPlace0001", "name": "Amber Fort", "address": "Jaipur"})
run("Hawa Mahal ke paas cafe", {"category": "cafe", "near": "Hawa Mahal"}, conv=conv)
check("(c) after a list the remembered place is forgotten (save asks which one)", A._last_place(redis_conn, USER, conv) is None)

# ---------------- (d) "achha restaurant dikhao": device location, else one question (never the trip)
r = run("achha restaurant dikhao", {"category": "good restaurant"}, trip=TRIP, location=ME)
call = FakeTextSearch.calls[0] if FakeTextSearch.calls else {}
check("(d) with a location (trip open too): the device, 'Aapke aaspas ...'",
      call.get("bias") == (ME[0], ME[1], places.NEAR_BIAS_RADIUS_M) and call.get("query") == "good restaurants"
      and r.reply_text.startswith("Aapke aaspas ye restaurants mile: "), (call, r.reply_text))
r = run("achha restaurant dikhao", {"category": "good restaurant"}, trip=TRIP)
check("(d) without a location (trip open): ONE question 'Kahan ke paas dekhun?', no Google call",
      r.reply_text == "Kahan ke paas dekhun?" and r.error_code == "no_area" and FakeTextSearch.calls == [] and r.ui_actions == [],
      r.reply_text)
r = run("where can I eat", {"category": "restaurant"}, lang="en")
check("(d) English question", r.reply_text == "Near which place should I look?", r.reply_text)
r = run("khana kahan milega", {"category": "khana"}, location=ME)
check("(d) 'khana kahan milega' -> restaurants around the device", FakeTextSearch.calls[0].get("query") == "restaurants"
      and r.reply_text.startswith("Aapke aaspas ye restaurants mile: "), r.reply_text)
r = run("restaurant dikhao", {"category": ""}, location=ME)
check("no category -> asks what to look for, no call", r.error_code == "no_category" and FakeTextSearch.calls == [], r.reply_text)

# ---------------- categories: one call each, the right query and type
for said, query, gtype in [("chai", "chai spots", None), ("street food", "street food spots", None),
                           ("cheap hotel", "cheap hotels", "lodging"), ("atm", "ATMs", "atm"),
                           ("petrol pump", "petrol pumps", "gas_station"), ("hospital", "hospitals", "hospital"),
                           ("pharmacy", "pharmacies", "pharmacy"), ("toilet", "toilets", "public_bathroom"),
                           ("rooftop bar", "rooftop bar", "bar"), ("momos", "momos", None)]:
    run(f"{said} near Howrah", {"category": said, "near": "Howrah"})
    c0 = FakeTextSearch.calls[0] if FakeTextSearch.calls else {}
    check(f"category '{said}' -> '{query} near Howrah', type {gtype}", len(FakeTextSearch.calls) == 1
          and c0.get("query") == f"{query} near Howrah" and c0.get("included_type") == gtype, c0)

# ---------------- ranking for speech: rating and distance
near_good = place("ChIJnear000000001", "Paas Wala Dhaba", ME[0] + 0.004, ME[1], ["restaurant"], 4.2)    # ~0.45 km
far_best = place("ChIJfar0000000001", "Door Ka Bistro", ME[0] + 0.045, ME[1], ["restaurant"], 4.6)     # ~5 km
order = [x["name"] for x in lookups.rank_for_speech([far_best, near_good], ME, ("restaurant",))]
check("ranked by rating and distance: a close 4.2 beats a 5 km 4.6", order == ["Paas Wala Dhaba", "Door Ka Bistro"], order)
order = [x["name"] for x in lookups.rank_for_speech([dict(near_good), dict(far_best)], None, ("restaurant",))]
check("without an origin: rating only", order == ["Door Ka Bistro", "Paas Wala Dhaba"], order)
check("rough distance words", [lookups.rough_distance(m, "hi") for m in (430, 1234, 12600)]
      == ["lagbhag 450 meter", "lagbhag 1.2 kilometer", "lagbhag 13 kilometer"]
      and lookups.rough_distance(1000, "en") == "about 1 km", [lookups.rough_distance(m, "hi") for m in (430, 1234, 12600)])

# ---------------- (e) "food page kholo" -> the Food page
r = run("food page kholo", {"page": "food"}, tool="navigate")
check("(e) 'food page kholo' -> navigate /food", r.ui_actions == [{"type": "navigate", "to": "/food"}] and r.action == "navigate:food",
      (r.ui_actions, r.action))

# ---------------- (f) a named place only still uses search_places
FakeTextSearch.answer = [place("ChIJhawaMahal0001", "Hawa Mahal", 26.9239, 75.8267, ["tourist_attraction", "historical_landmark"])]
r = run("Hawa Mahal dikhao", {"query": "Hawa Mahal Jaipur", "show": True}, tool="search_places", location=ME)
call = FakeTextSearch.calls[0] if FakeTextSearch.calls else {}
check("(f) 'Hawa Mahal dikhao' -> search_places: one plain Text Search (no type, no bias, no rating), one pin",
      len(FakeTextSearch.calls) == 1 and call.get("query") == "Hawa Mahal Jaipur" and not call.get("included_type")
      and not call.get("bias") and not call.get("with_rating") and r.action == "map_focus"
      and [a["type"] for a in r.ui_actions] == ["map_focus", "navigate"], (call, r.action))
FakeTextSearch.answer = RESTAURANTS

# ---------------- (g) quota / paused key
FakeTextSearch.raise_quota = True
r = run("Hawa Mahal ke paas restaurant", {"category": "restaurant", "near": "Hawa Mahal"})
check("(g) quota -> the map search message 'Map search abhi available nahi hai.', nothing on the map",
      r.reply_text == lookups.MAPS_UNAVAILABLE["hi"] == "Map search abhi available nahi hai."
      and r.error_code == "maps_unavailable" and r.ui_actions == [], r.reply_text)
r = run("cafes near me", {"category": "cafe", "near_me": True}, location=ME, lang="en")
check("(g) English quota message (near me too)", r.reply_text == lookups.MAPS_UNAVAILABLE["en"], r.reply_text)
FakeTextSearch.raise_quota = False
FakeTextSearch.answer = []
r = run("Howrah ke paas petrol pump", {"category": "petrol pump", "near": "Howrah"})
check("nothing found -> says so, no map", r.reply_text == "Howrah ke paas koi petrol pumps nahi mile."
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
    found = places.search_category("cafe", near="unit test place", bias=(26.9, 75.8), bias_radius_m=places.NEAR_BIAS_RADIUS_M)
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
