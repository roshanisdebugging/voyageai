"""
Jarvis chat: real Google places for "nearest hospital", "medical shop near me", "cafe near Hawa Mahal".
Run from backend/: python -m tests.test_tourguide_places
No real Google, OpenAI or Gemini call: httpx (Places searchNearby), the named-place lookup, the model and the cost
guard are fakes. Uses the local Redis for the 60 s cache (tg:places:* keys and gmaps:paused:nearby are removed).
"""
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

import dotenv

dotenv.load_dotenv = lambda *a, **k: None
os.environ.setdefault("DATABASE_URL", "postgresql://x:y@127.0.0.1:1/none")
os.environ["AI_PROVIDER"] = "mock"
os.environ.pop("TOURGUIDE_PRIMARY", None)

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)

import httpx  # noqa: E402

import places as places_mod  # noqa: E402
import tour_guide_service as tg  # noqa: E402
from redis_client import redis_conn  # noqa: E402
from services import google_maps_service as gms  # noqa: E402

results = []


def check(name, cond, info=None):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if (info is not None and not cond) else ""))


def clean_redis():
    for pattern in ("tg:places:*", "gmaps:paused:nearby"):
        for key in redis_conn.scan_iter(pattern):
            redis_conn.delete(key)
    gms._in_memory_cache.pop("gmaps:paused:nearby", None)


clean_redis()

# ---------------------------------------------------------------- 1. detect_place_intent
CASES = [
    # (message, category, place_text)
    ("nearest hospital", "hospital", None),
    ("Hospital kahan hai?", "hospital", None),
    ("mujhe doctor chahiye", "hospital", None),
    ("ambulance bulao", "hospital", None),
    ("paas mein koi aspatal hai?", "hospital", None),
    ("मेरे पास अस्पताल कहाँ है", "hospital", None),
    ("EMERGENCY clinic near me", "hospital", None),
    ("medical shop near me", "pharmacy", None),
    ("chemist kahan milega", "pharmacy", None),
    ("medicine ki dukaan batao", "pharmacy", None),
    ("दवा की दुकान", "pharmacy", None),
    ("24x7 pharmacy", "pharmacy", None),
    ("pharmacy near AIIMS hospital", "pharmacy", "AIIMS hospital"),
    ("best street food near me", "restaurant", None),
    ("khana kahan milega", "restaurant", None),
    ("restaurant near Hawa Mahal", "restaurant", "Hawa Mahal"),
    ("Hawa Mahal ke paas achha dhaba batao", "restaurant", "Hawa Mahal"),
    ("पास में खाना कहाँ मिलेगा", "restaurant", None),
    ("cafe near Hawa Mahal", "cafe", "Hawa Mahal"),
    ("Coffee near India Gate please", "cafe", "India Gate"),
    ("chai kahan milegi", "cafe", None),
    ("cafe Hawa Mahal ke paas", "cafe", "Hawa Mahal"),
    ("yahan ke paas chai", "cafe", None),
    ("mere ghar ke paas hospital", "hospital", None),
    ("nearby cafe", "cafe", None),
    ("near Hawa Mahal, cafe chahiye", "cafe", "Hawa Mahal"),
    ("Haan, Amer Fort ke paas restaurant", "restaurant", "Amer Fort"),
    ("Blue Tokai cafe ke paas pharmacy", "pharmacy", "Blue Tokai cafe"),
]
for msg, cat, place in CASES:
    got = tg.detect_place_intent(msg)
    check(f"intent: {msg!r} -> {cat}, place={place!r}",
          got is not None and got["category"] == cat and got["place_text"] == place, got)

NOT_PLACES = [
    "Hawa Mahal ke baare mein batao",
    "Jaipur ka famous khana kya hai?",
    "best time to visit Jaipur",
    "kya mujhe malaria ki medicine leni chahiye?",
    "street food tour ideas for Delhi",
    "AIIMS hospital ke paas",
    "who will win the IPL",
    "",
]
for msg in NOT_PLACES:
    check(f"not a place lookup: {msg!r}", tg.detect_place_intent(msg) is None, tg.detect_place_intent(msg))

# ---------------------------------------------------------------- fakes: Google over httpx, named lookup, model
http_calls = []
responder = {"fn": None}


class FakeResp:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body
        self.text = json.dumps(body)

    def json(self):
        return self._body


class FakeAsyncClient:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):
        http_calls.append({"url": url, "headers": headers or {}, "json": json})
        return responder["fn"](url, json)

    async def get(self, url, headers=None, **k):
        http_calls.append({"url": url, "headers": headers or {}, "json": None})
        return FakeResp(500, {})


httpx.AsyncClient = FakeAsyncClient
gms.GOOGLE_MAPS_SERVER_KEY = "test-key-not-real"

JAIPUR = (26.9124, 75.7873)


def gplace(name, dlat, dlng, *, rating=4.2, count=120, open_now=None, phone=None, uri=None, addr=None, types=None):
    p = {"displayName": {"text": name}, "formattedAddress": addr or f"{name} Road, Jaipur",
         "location": {"latitude": JAIPUR[0] + dlat, "longitude": JAIPUR[1] + dlng},
         "rating": rating, "userRatingCount": count}
    types = types or (["pharmacy", "health", "store"] if "Pharmacy" in name else ["cafe", "food"] if "Cafe" in name
                      else ["hospital", "health"])
    p["primaryType"], p["types"] = types[0], types
    if open_now is not None:
        p["currentOpeningHours"] = {"openNow": open_now}
    if phone:
        p["nationalPhoneNumber"] = phone
    if uri:
        p["googleMapsUri"] = uri
    return p


HOSPITALS = [
    gplace("City Care Hospital", 0.004, 0, open_now=False, phone="0141 222 3333", uri="https://maps.google.com/?cid=1"),
    gplace("SMS Hospital", 0.012, 0, open_now=True, phone="0141 251 8222", uri="https://maps.google.com/?cid=2"),
    gplace("Fortis Escorts", 0.020, 0, open_now=None),
]


def nearby_ok(places_list):
    return lambda url, body: FakeResp(200, {"places": places_list})


named_calls = []


class FakeSearch:
    def __init__(self, results=None, unavailable=False):
        self.results = results or []
        self.unavailable = unavailable
        self.google_calls = 1
        self.ambiguous = False


named = {"fn": lambda q: FakeSearch([{"name": "Hawa Mahal", "latitude": 26.9239, "longitude": 75.8267}])}


def fake_named(q):
    named_calls.append(q)
    return named["fn"](q)


places_mod.search_places_detailed = fake_named

llm = {"calls": 0, "prompt": None, "system": None, "answer": "Sabse paas City Care Hospital hai, 450 m door."}


def fake_openai(prompt, system_prompt, temperature=0.4):
    llm["calls"] += 1
    llm["prompt"], llm["system"] = prompt, system_prompt
    yield llm["answer"]


tg._openai_stream = fake_openai
tg._gemini_chain = lambda *a, **k: (None, False)
tg.evaluate_cost_guards = lambda m: (True, tg.ESSENTIAL_GATE if any(w in m.lower() for w in ("hospital", "medical", "doctor")) else "PASSED_TO_LLM", "")
saved = []
tg._save_exchange = lambda *a, **k: saved.append(a)
lines = []


class Grab(logging.Handler):
    def emit(self, record):
        lines.append(record.getMessage())


tg.turn_log.addHandler(Grab())


def reset(fn=None):
    http_calls.clear()
    named_calls.clear()
    saved.clear()
    lines.clear()
    llm.update(calls=0, prompt=None, system=None)
    responder["fn"] = fn
    clean_redis()


def ask(msg, lat=JAIPUR[0], lng=JAIPUR[1], mode="local"):
    return tg.process_concierge_message("user_1", msg, mode=mode, lat=lat if mode == "local" else None,
                                        lng=lng if mode == "local" else None, recent_history=[],
                                        device_lat=lat, device_lng=lng)


# ---------------------------------------------------------------- 2. the Google call: types, mask, no Details
reset(nearby_ok(HOSPITALS))
out = ask("nearest hospital")
nearby = [c for c in http_calls if "places:searchNearby" in c["url"]]
check("hospital: exactly one Google call, searchNearby", len(http_calls) == 1 and len(nearby) == 1, [c["url"] for c in http_calls])
check("no Place Details call (no /v1/places/{id} GET)", not any(c["json"] is None for c in http_calls))
req = nearby[0]
check("field mask is exactly the essentials", req["headers"].get("X-Goog-FieldMask") == (
    "places.displayName,places.formattedAddress,places.location,places.rating,places.userRatingCount,"
    "places.currentOpeningHours.openNow,places.nationalPhoneNumber,places.googleMapsUri,"
    "places.primaryType,places.types"), req["headers"].get("X-Goog-FieldMask"))
check("hospital: includedTypes [hospital], DISTANCE, 10 results, 3000 m around the device",
      req["json"]["includedTypes"] == ["hospital"] and req["json"]["rankPreference"] == "DISTANCE"
      and req["json"]["maxResultCount"] == 10 and req["json"]["locationRestriction"]["circle"]["radius"] == 3000.0
      and req["json"]["locationRestriction"]["circle"]["center"] == {"latitude": JAIPUR[0], "longitude": JAIPUR[1]},
      req["json"])
check("hospital: reply starts with the 112/108 line", out["reply"].startswith("Emergency ho to 112 ya 108 dial karein."),
      out["reply"])
check("hospital: emergency flag for the call strip", out["emergency"] is True and out["needs_location"] is False)
names = [p["name"] for p in out["places"]]
check("hospital: open now, then unknown, then closed", names == ["SMS Hospital", "Fortis Escorts", "City Care Hospital"], names)
p0 = out["places"][0]
check("place fields: name, address, lat, lng, distance_m, rating, open_now, phone, maps_url",
      {"name", "address", "lat", "lng", "distance_m", "rating", "open_now", "phone", "maps_url"} <= set(p0)
      and p0["phone"] == "0141 251 8222" and p0["maps_url"] == "https://maps.google.com/?cid=2"
      and p0["open_now"] is True and 1200 < p0["distance_m"] < 1450, p0)
check("unknown open-now stays None (never guessed)", out["places"][1]["open_now"] is None)
check("no model card when places are shown", out["card"] is None)
check("place_intent says device", out["place_intent"] == {"category": "hospital", "source": "device", "near": None},
      out["place_intent"])

check("card data shape unchanged (no place types sent)", set(p0) == {
    "name", "address", "lat", "lng", "distance_m", "rating", "rating_count", "open_now", "phone", "maps_url"}, sorted(p0))

# prompt block = only the returned places (hospital: the first two), no phone
pr = llm["prompt"] or ""
check("prompt has the VERIFIED PLACES (Google) block", "VERIFIED PLACES (Google" in pr)
check("prompt block (hospital): only the first two", all(n in pr for n in names[:2]) and names[2] not in pr
      and pr.count(" | open now: ") == 2, pr)
check("prompt block: open now yes/no/unknown + rating", "SMS Hospital | 1.3 km | open now: yes | rating: 4.2 (120 reviews)" in pr, pr)
check("prompt has the address, no phone number", "0141" not in pr and "address: SMS Hospital Road, Jaipur" in pr)
check("system prompt has the 'only these places' rules", "Name ONLY places listed in the VERIFIED PLACES block" in llm["system"]
      and "Never invent phone numbers" in llm["system"])
check("the places prompt replaces the general ones (no delivery apps, no tips)", llm["system"] == tg.guide_places.places_system_prompt("hospital")
      and "Blinkit" not in llm["system"] and "quick delivery" not in llm["system"])
check("old pharmacy note not added (no second Google call)", "Nearby verified stores" not in pr)

hist = saved[0][5]
check("history metadata keeps places but not phone or address",
      hist["places"] and all("phone" not in p and "address" not in p for p in hist["places"])
      and hist["places"][0]["name"] == "SMS Hospital", hist.get("places"))
check("the live response still has the phone", out["places"][0]["phone"] == "0141 251 8222")
check("log: category, source, results, cache hit, latency",
      any("[TOURGUIDE PLACES] category=hospital source=device status=ok results=3 cache_hit=false radius_m=3000 google_calls=1"
          in l and " ms=" in l for l in lines), lines)

# cache: same category + same spot within 60 s -> no Google call
http_calls.clear()
lines.clear()
out2 = ask("hospital kahan hai")
check("cache hit: no second Google call", http_calls == [] and [p["name"] for p in out2["places"]] == names)
check("cache hit logged", any("cache_hit=true" in l for l in lines), lines)
check("cache key: category + lat/lng to 3 decimals, 60 s",
      0 < redis_conn.ttl(f"tg:places:hospital:{round(JAIPUR[0], 3)}:{round(JAIPUR[1], 3)}") <= 60)

# ---------------------------------------------------------------- 3. pharmacy types, radius widening
calls_by_radius = []


def empty_then_found(url, body):
    calls_by_radius.append(body["locationRestriction"]["circle"]["radius"])
    if body["locationRestriction"]["circle"]["radius"] < 5000:
        return FakeResp(200, {})
    return FakeResp(200, {"places": [gplace("Apollo Pharmacy", 0.05, 0, open_now=True, phone="1860 500 0101")]})


reset(empty_then_found)
out = ask("medical shop near me")
check("pharmacy: still 5 results", http_calls[0]["json"]["maxResultCount"] == 5)
check("pharmacy: includedTypes [pharmacy, drugstore]", http_calls[0]["json"]["includedTypes"] == ["pharmacy", "drugstore"],
      http_calls[0]["json"]["includedTypes"])
check("nothing at 3 km -> one retry at 10 km", calls_by_radius == [3000.0, 10000.0], calls_by_radius)
check("pharmacy: the 10 km result is used", [p["name"] for p in out["places"]] == ["Apollo Pharmacy"] and not out["emergency"])
check("pharmacy reply has no 112 prefix (not a hospital)", not out["reply"].startswith("Emergency"))

calls_by_radius.clear()
reset(lambda url, body: (calls_by_radius.append(1), FakeResp(200, {}))[1])
out = ask("cafe kahan milega")
check("cafe: includedTypes [cafe]", http_calls and http_calls[0]["json"]["includedTypes"] == ["cafe"])
check("nothing at 10 km either: says so, no model call, no places", llm["calls"] == 0 and out["places"] == []
      and "10 km ke andar Google par koi cafe nahi mila" in out["reply"] and len(http_calls) == 2, out["reply"])

reset(nearby_ok([gplace("Laxmi Misthan Bhandar", 0.003, 0.001)]))
out = ask("khana kahan milega")
check("restaurant: includedTypes [restaurant]", http_calls[0]["json"]["includedTypes"] == ["restaurant"])

# ---------------------------------------------------------------- 4. named place ("cafe near Hawa Mahal")
reset(nearby_ok([gplace("Tattoo Cafe", 0.0118, 0.0396, rating=4.4, uri="https://maps.google.com/?cid=9")]))
out = ask("cafe near Hawa Mahal")
check("named: the app's named lookup is used for the place", named_calls == ["Hawa Mahal"], named_calls)
check("named: nearby search centred on Hawa Mahal, not the device",
      http_calls[0]["json"]["locationRestriction"]["circle"]["center"] == {"latitude": 26.9239, "longitude": 75.8267})
check("named: distances measured from Hawa Mahal", out["places"][0]["distance_m"] < 100, out["places"][0]["distance_m"])
check("named: place_intent source named, near Hawa Mahal",
      out["place_intent"] == {"category": "cafe", "source": "named", "near": "Hawa Mahal"}, out["place_intent"])
check("named: prompt says near Hawa Mahal", "near Hawa Mahal" in (llm["prompt"] or ""))

reset(nearby_ok([]))
named["fn"] = lambda q: FakeSearch([])
out = ask("cafe near Xyzabc Nagar")
check("named place not found: says so, no nearby call, no model call",
      http_calls == [] and llm["calls"] == 0 and "Google Maps par nahi mila" in out["reply"] and out["places"] == [], out["reply"])
named["fn"] = lambda q: FakeSearch(unavailable=True)
out = ask("cafe near Hawa Mahal")
check("named lookup quota: honest unavailable, no model call", llm["calls"] == 0 and "abhi check nahi ho pa rahe" in out["reply"])
named["fn"] = lambda q: FakeSearch([{"name": "Hawa Mahal", "latitude": 26.9239, "longitude": 75.8267}])

# ---------------------------------------------------------------- 5. Google errors -> honest, never invented
reset(lambda url, body: FakeResp(500, {"error": {"status": "INTERNAL"}}))
out = ask("nearest hospital")
check("Google 500: honest unavailable message, no places, no model call",
      out["places"] == [] and llm["calls"] == 0 and "Nearby places abhi check nahi ho pa rahe" in out["reply"], out)
check("Google 500 + hospital: still starts with 112/108", out["reply"].startswith("Emergency ho to 112 ya 108 dial karein."))
check("Google 500: nothing cached", redis_conn.get(f"tg:places:hospital:{round(JAIPUR[0], 3)}:{round(JAIPUR[1], 3)}") is None)

reset(lambda url, body: FakeResp(429, {"error": {"status": "RESOURCE_EXHAUSTED", "message": "Quota exceeded per day"}}))
out = ask("medical shop near me")
check("Google quota: unavailable + 112/108 for a medical shop", "abhi check nahi ho pa rahe" in out["reply"]
      and "112 ya 108" in out["reply"] and out["places"] == [], out["reply"])
http_calls.clear()
redis_conn.delete(f"tg:places:pharmacy:{round(JAIPUR[0], 3)}:{round(JAIPUR[1], 3)}")
out = ask("pharmacy kahan hai")
check("after a quota error nearby is paused: no further Google call", http_calls == [] and out["places"] == [])
clean_redis()

reset(nearby_ok(HOSPITALS))
gms.GOOGLE_MAPS_SERVER_KEY = ""
out = ask("nearest hospital")
check("no Google key: unavailable, never invented", out["places"] == [] and "abhi check nahi ho pa rahe" in out["reply"])
gms.GOOGLE_MAPS_SERVER_KEY = "test-key-not-real"

# ---------------------------------------------------------------- 6. missing location
reset(nearby_ok(HOSPITALS))
out = ask("nearest hospital", lat=None, lng=None)
check("no location: asks for it, needs_location flag, no Google, no model",
      out["needs_location"] is True and http_calls == [] and llm["calls"] == 0
      and "Location on kijiye" in out["reply"], out)
check("no location + hospital: still the 112/108 line first", out["reply"].startswith("Emergency ho to 112 ya 108"))
reset(nearby_ok(HOSPITALS))
out = ask("nearest hospital", mode="trip")
check("Trip mode: the device location is still used for places", len(http_calls) == 1 and out["places"])

# ---------------------------------------------------------------- 7. not a place question -> unchanged path
reset(nearby_ok(HOSPITALS))
llm["answer"] = "Hawa Mahal 1799 mein bana tha."
out = ask("Hawa Mahal ke baare mein batao")
check("plain question: no Google call, no block, places [] and no emergency",
      http_calls == [] and "VERIFIED PLACES" not in (llm["prompt"] or "") and out["places"] == [] and out["emergency"] is False)

# ---------------------------------------------------------------- 8. stream: prefix token first, places in done
reset(nearby_ok(HOSPITALS))
llm["answer"] = "SMS Hospital abhi khula hai, 1.3 km door."


async def run_stream(msg, **kw):
    out = []
    async for chunk in tg.stream_concierge_events("user_1", msg, recent_history=[], lat=JAIPUR[0], lng=JAIPUR[1],
                                                   device_lat=JAIPUR[0], device_lng=JAIPUR[1], **kw):
        name = chunk.split("\n", 1)[0].replace("event: ", "")
        out.append((name, json.loads(chunk.split("data: ", 1)[1])))
    return out


ev = asyncio.run(run_stream("nearest hospital"))
check("stream: first token is the 112/108 line", ev[1] == ("token", {"t": "Emergency ho to 112 ya 108 dial karein. "}), ev[:2])
done = ev[-1][1]
check("stream: done has places, emergency, reply with the prefix once",
      ev[-1][0] == "done" and [p["name"] for p in done["places"]] == names and done["emergency"] is True
      and done["reply"].count("Emergency ho to 112") == 1, done)

reset(nearby_ok(HOSPITALS))


async def run_stream_no_loc():
    out = []
    async for chunk in tg.stream_concierge_events("user_1", "nearest hospital", recent_history=[]):
        name = chunk.split("\n", 1)[0].replace("event: ", "")
        out.append((name, json.loads(chunk.split("data: ", 1)[1])))
    return out


ev = asyncio.run(run_stream_no_loc())
check("stream, no location: one token + done with needs_location, no model",
      [n for n, _ in ev] == ["start", "token", "done"] and ev[-1][1]["needs_location"] is True and llm["calls"] == 0, ev)

# ---------------------------------------------------------------- summary
clean_redis()
passed = sum(1 for _, ok in results if ok)
print(f"\n{passed}/{len(results)} passed")
sys.exit(0 if passed == len(results) else 1)
