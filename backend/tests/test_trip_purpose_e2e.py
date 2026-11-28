"""
End to end: the trip purpose and base area reach the itinerary prompt (feat/trip-purpose, the "pure tourist plan" bug).

Evidence: voice read back "... event ke liye, Electronic City ke paas" and the trip was created, but the trips row had
purpose_type NULL and the itinerary was a Luxury / Nightlife tourist plan. Cause: the frontend's sanitizePrefill
(src/voice/uiActions.ts) dropped purposeType / purposeText / baseArea from the voice prefill, so the wizard never sent
them; and for every trip the Travel Style line came from the account's saved preferences.

This test runs the REAL path with a fake LLM and a fake Google (no real AI or Google call):
  VOICE: run_agent turns -> the open_review prefill -> the REAL frontend sanitizePrefill + wizard state + payload builder
         (node frontend/tests/wizardBridge.mjs) -> the WS dispatch main.process_ws_action("trips:create")
  FORM:  the wizard's state -> the REAL payload builder (wizardBridge.mjs form) -> POST /api/trips (the REST fallback)
then the itinerary job (itinerary_service.process_async_itinerary_generation, what worker.py runs) and checks:
  (a) the trips row holds purpose_type=event, purpose_text and base_area_json;
  (b) the exact prompt given to the fake LLM has the event block, the base area name and no account style
      (the account here prefers LUXURY, NIGHTLIFE);
  (c) the cache key differs from the leisure key and no old cached (tourist) plan is used.
A leisure trip through the same path is the control: no block, the style line and key exactly as before.
App DB = SQLite, Redis = local. Run from backend/: python -m tests.test_trip_purpose_e2e
"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import uuid
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import dotenv

dotenv.load_dotenv = lambda *a, **k: None
os.environ["DATABASE_URL"] = "postgresql://x:y@127.0.0.1:1/none"
os.environ["AI_PROVIDER"] = "mock"
os.environ["OPENAI_API_KEY"] = "test-key-not-real"
os.environ["VOICE_TTS_ENABLED"] = "false"
os.environ.pop("VOICE_DEBUG_STORE", None)

BACKEND_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIR = BACKEND_DIR.parent / "frontend"
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)
SCRATCH = tempfile.mkdtemp(prefix="voyageai_test_")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

import database  # noqa: E402

database.engine = create_engine(f"sqlite:///{os.path.join(SCRATCH, 'e2e.db')}", connect_args={"check_same_thread": False})
database.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=database.engine)

import main  # noqa: E402
import ai_provider  # noqa: E402
import itinerary_service as I  # noqa: E402
import openai_client  # noqa: E402
import place_verify  # noqa: E402
import places  # noqa: E402
import trip_lifecycle  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from models_trip import TripModel  # noqa: E402
from redis_client import redis_conn  # noqa: E402
from trip_lifecycle import budget_level_for, today_ist  # noqa: E402
from voice import agent, draft as D, pending as P  # noqa: E402

main.SessionLocal = database.SessionLocal
database.Base.metadata.create_all(bind=database.engine)

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if (detail != "" and not cond) else ""), flush=True)


TODAY = today_ist()
iso = lambda n: (TODAY + timedelta(days=n)).isoformat()  # noqa: E731
START, END = iso(13), iso(16)     # like 11 -> 14 December: 4 days, 3 nights
USER_ID = f"usr_e2e_{uuid.uuid4().hex[:6]}"
AUTH_USER = SimpleNamespace(id=USER_ID)
# The account's saved preferences, as in the evidence (Kerala and Goa trips came out "Luxury ... Nightlife").
PREFS = SimpleNamespace(userId=USER_ID, travelStyles=["LUXURY", "NIGHTLIFE"], budgetLevel="PREMIUM", transportPreferences=[],
                        dietaryPreferences=[], foodInterests=[], activityInterests=[])
SESSION = (AUTH_USER, None, PREFS)


def pl(pid, name, lat, lng, city):
    return [{"id": pid, "place_id": pid, "name": name, "latitude": lat, "longitude": lng, "city": city}]


PLACES = {"bengaluru": pl("ChIJblr", "Bengaluru", 12.97, 77.59, "Bengaluru, Karnataka, India"),
          "kolkata": pl("ChIJkol", "Kolkata", 22.57, 88.36, "Kolkata, West Bengal, India"),
          "electronic city, bengaluru": pl("ChIJec", "Electronic City", 12.845, 77.66, "Bengaluru, Karnataka, India")}
fake_search = lambda q: PLACES.get(q.strip().lower(), [])  # noqa: E731


class FakeTools:
    queue = []

    def __call__(self, messages, tools, **kw):
        if not FakeTools.queue:
            return {"content": "Theek hai.", "tool_calls": []}
        return {"content": None, "tool_calls": [{"name": "update_trip_draft", "arguments": FakeTools.queue.pop(0)}]}


def ra(text, conv, args=None):
    FakeTools.queue = [args] if args is not None else []
    return agent.run_agent(text, "hi", user_id=USER_ID, conversation_id=conv, screen="/home", trip=None, redis_conn=redis_conn)


def bridge(mode, obj):
    """The REAL frontend code (tsload + TypeScript), as the browser runs it."""
    out = subprocess.run(["node", "tests/wizardBridge.mjs", mode, json.dumps(obj), TODAY.isoformat()], cwd=FRONTEND_DIR,
                         capture_output=True, text=True, encoding="utf-8", timeout=120)
    if out.returncode != 0:
        raise RuntimeError(out.stderr[-400:])
    return json.loads(out.stdout)


# ---------------------------------------------------------------- the fake LLM and the cache
PROMPTS, CACHE_ASKED, CACHE_SET = [], [], []
LEISURE_KEY_SEEN = []
TOURIST_PLAN = {"title": "Old cached tourist plan", "days": [], "transportSuggestions": []}   # must never be used


def fake_cache_get(key):
    CACHE_ASKED.append(key)
    # An old plan is cached under the leisure (tourist) key; a purpose trip must never read it.
    return TOURIST_PLAN if ":purpose_" not in key else None


def plan_json(start_iso):
    from datetime import date
    s = date.fromisoformat(start_iso)
    days = []
    for d in range(4):
        days.append({"dayNumber": d + 1, "date": (s + timedelta(days=d)).isoformat(), "title": f"Day {d + 1}",
                     "summary": "Around the base area.", "activities": [
                         {"timeSlot": "09:00 AM", "title": f"Breakfast {d}", "description": "x", "activityType": "DINING",
                          "locationName": f"Cafe {d}, Electronic City Phase 1", "latitude": 12.84 + d / 1000, "longitude": 77.66,
                          "estimatedCostInr": 200}]})
    return json.dumps({"title": "Plan", "days": days, "transportSuggestions": []})


def fake_generate(prompt, validate_output, correction_prompt):
    PROMPTS.append(prompt)
    schema, err = validate_output(plan_json(START))
    assert schema is not None, err
    return schema, "OPENAI"


def run_job(trip_id):
    with mock.patch.object(I, "get_cached_itinerary", fake_cache_get), \
            mock.patch.object(I, "set_cached_itinerary", lambda key, data: CACHE_SET.append(key)), \
            mock.patch.object(ai_provider, "ai_provider_name", lambda: "openai"), \
            mock.patch.object(ai_provider, "generate_itinerary", fake_generate), \
            mock.patch.object(place_verify, "should_verify", lambda who: False):
        return I.process_async_itinerary_generation(trip_id, database.SessionLocal)


def row(trip_id):
    with database.SessionLocal() as db:
        t = db.query(TripModel).filter(TripModel.id == trip_id).one()
        return t.purpose_type, t.purpose_text, t.base_area_json, t.budget


def assert_event_trip(label, trip_id, want_text):
    ptype, ptext, area_json, budget = row(trip_id)
    area = json.loads(area_json) if area_json else {}
    check(f"[{label}] (a) trips row: purpose_type=event", ptype == "event", ptype)
    check(f"[{label}] (a) trips row: purpose_text", ptext == want_text, ptext)
    check(f"[{label}] (a) trips row: base_area_json = Electronic City with coordinates",
          area.get("name") == "Electronic City" and area.get("id") == "ChIJec" and area.get("latitude") == 12.845, area)
    n = len(PROMPTS)
    status = run_job(trip_id)
    check(f"[{label}] the job ran: READY, the fake LLM was called once", status == "READY" and len(PROMPTS) == n + 1, status)
    prompt = PROMPTS[-1]
    check(f"[{label}] (b) prompt: the event block", "TRIP PURPOSE (" in prompt and "- Purpose type: event" in prompt
          and I.PURPOSE_RULES["event"] in prompt)
    check(f"[{label}] (b) prompt: the words as quoted data", f'<traveller_words>"{want_text}"</traveller_words>' in prompt)
    check(f"[{label}] (b) prompt: the base area name and 15 km", '- Base area: "Electronic City" (latitude 12.845, longitude 77.66)'
          in prompt and 'within 15 km of the base area "Electronic City"' in prompt)
    check(f"[{label}] (b) prompt: no account style (LUXURY / NIGHTLIFE) in the Travel Style line",
          "- Travel Style: not applicable, follow the purpose rules" in prompt and "LUXURY" not in prompt
          and "NIGHTLIFE" not in prompt)
    check(f"[{label}] (b) prompt: account style preferences do not apply", "saved account style preferences" in prompt
          and "do not apply to this trip" in prompt)
    key = CACHE_ASKED[-1]
    check(f"[{label}] (c) cache key has the purpose and the area", key.endswith(":purpose_event:area_ChIJec:pv3") and "luxury" not in key and "nightlife" not in key, key)
    check(f"[{label}] (c) cache key differs from the leisure key", key != LEISURE_KEY, f"{key} vs {LEISURE_KEY}")
    check(f"[{label}] (c) no old cached plan used (the model made it, cached under the purpose key)",
          CACHE_SET[-1] == key and not any(k == LEISURE_KEY for k in CACHE_ASKED[-1:]))
    with database.SessionLocal() as db:
        from models_itinerary import ItineraryModel
        itin = db.query(ItineraryModel).filter(ItineraryModel.trip_id == trip_id).one()
        check(f"[{label}] (c) the saved itinerary came from the model, not the cache", itin.provider_name == "OPENAI", itin.provider_name)
    return prompt, budget


LEISURE_KEY = f"itinerary:bengaluru:4d:luxury_nightlife:{budget_level_for(12000, 4, 1, 0).lower()}:from_kolkata"

with mock.patch.object(openai_client, "chat_tools", FakeTools()), mock.patch.object(places, "search_places", fake_search), \
        mock.patch.object(trip_lifecycle, "enqueue_itinerary_generation", lambda tid: True), \
        mock.patch("media_service.media_service.resolve_cover_media", lambda d: {}):
    # ------------------------------------------------------------ VOICE
    print("\n== VOICE: draft -> prefill -> real frontend code -> WS trips:create -> the job")
    conv = f"conv_e2e_{uuid.uuid4().hex[:6]}"
    ra("Bengaluru jaana hai", conv, {"destination": "Bengaluru"})
    ra("dates", conv, {"start_date": START, "end_date": END})
    ra("ek banda", conv, {"adults": 1, "children": 0})
    ra("12 hazaar, Kolkata se", conv, {"budget_inr": 12000, "origin_city": "Kolkata"})
    ra("hackathon ke liye", conv, {"purpose": "hackathon ke liye"})
    r = ra("Electronic City mein", conv, {"base_area": "Electronic City"})
    check("voice read-back says the word said ('hackathon', not 'event')",
          "hackathon ke liye, Electronic City ke paas. Sahi hai?" in r.reply_text, r.reply_text)
    r = ra("हाँ, ठीक है", conv)
    prefill = next((a["prefill"] for a in r.ui_actions if a.get("type") == "open_review"), None)
    check("voice prefill (backend) carries the three fields", prefill and prefill.get("purposeType") == "event"
          and prefill.get("purposeText") == "hackathon" and (prefill.get("baseArea") or {}).get("name") == "Electronic City",
          prefill)
    payload = bridge("voice", prefill)
    print(f"   wizard payload keys (voice): {sorted(payload)}")
    check("REAL frontend: the createTrip payload keeps purposeType / purposeText / baseArea",
          {"purposeType", "purposeText", "baseArea"} <= set(payload) and payload["purposeType"] == "event", sorted(payload))
    payload["clientRequestId"] = f"req_{uuid.uuid4().hex[:8]}"
    with database.SessionLocal() as db:
        created = asyncio.run(main.process_ws_action("trips:create", payload, db, None, session=SESSION))
    check("WS trips:create response carries the fields", created["purposeType"] == "event" and created["baseArea"]["name"]
          == "Electronic City")
    _, budget = assert_event_trip("voice", created["id"], "hackathon")
    print(f"   budget level for Rs 12,000, 1 adult, 4 days: {budget.get('level')} (per person per day {12000 // 4})")
    check("budget 12,000 for 1 person, 4 days -> MODERATE, not PREMIUM (from the amount, not the account)",
          budget.get("level") == "MODERATE", budget)
    D.delete(redis_conn, USER_ID, conv)
    P.clear(redis_conn, USER_ID, conv)
    agent.clear_memory(redis_conn, USER_ID, conv)

    # ------------------------------------------------------------ FORM
    print("\n== FORM: wizard state -> real payload builder -> POST /api/trips (REST fallback) -> the job")
    BLR = dict(PLACES["bengaluru"][0], country="India", city="Bengaluru", region="Karnataka")
    KOL = dict(PLACES["kolkata"][0], country="India", city="Kolkata", region="West Bengal")
    EC = {"id": "ChIJec", "name": "Electronic City", "city": "Bengaluru", "region": "Karnataka", "country": "India",
          "latitude": 12.845, "longitude": 77.66}
    state = {"destination": BLR, "origin": KOL, "startDate": START, "endDate": END, "adults": 1, "children": 0, "styles": [],
             "budgetAmount": 12000, "planCardId": None, "purposeType": "event", "purposeText": "Hackathon at a tech park",
             "baseArea": EC}
    form_payload = bridge("form", state)
    print(f"   wizard payload keys (form):  {sorted(form_payload)}")
    check("REAL frontend: the form payload keeps the three fields",
          {"purposeType", "purposeText", "baseArea"} <= set(form_payload), sorted(form_payload))
    form_payload["clientRequestId"] = f"req_{uuid.uuid4().hex[:8]}"
    with mock.patch.object(main.auth, "get_session_user", lambda db, token: SESSION), TestClient(main.app) as client:
        res = client.post("/api/trips", json=form_payload, headers={"Authorization": "Bearer test-token-not-real"})
    check("POST /api/trips -> 201 with the fields", res.status_code == 201 and res.json().get("purposeType") == "event",
          f"{res.status_code} {res.text[:200]}")
    assert_event_trip("form", res.json()["id"], "Hackathon at a tech park")

    # ------------------------------------------------------------ CONTROL: leisure through the same path
    print("\n== CONTROL: a leisure trip, same path: planned exactly as before")
    leisure = bridge("form", dict(state, purposeType="leisure", purposeText="", baseArea=None))
    leisure["clientRequestId"] = f"req_{uuid.uuid4().hex[:8]}"
    with database.SessionLocal() as db:
        lt = asyncio.run(main.process_ws_action("trips:create", leisure, db, None, session=SESSION))
    check("leisure row: purpose_type leisure, no text, no area", row(lt["id"])[:3] == ("leisure", None, None), row(lt["id"]))
    n = len(PROMPTS)
    status = run_job(lt["id"])
    check("leisure: the cache is asked with exactly the old key", CACHE_ASKED[-1] == LEISURE_KEY, CACHE_ASKED[-1])
    # The stub's cached plan has no days, so the job rejects it and asks the model (existing behaviour): that gives
    # the real leisure prompt the job builds.
    check("leisure: READY, the model asked once", status == "READY" and len(PROMPTS) == n + 1, f"{status} {len(PROMPTS) - n}")
    check("leisure prompt (from the job): the Travel Style line as before (account style), no purpose block",
          "- Travel Style: LUXURY, NIGHTLIFE" in PROMPTS[-1] and "TRIP PURPOSE" not in PROMPTS[-1])

with database.SessionLocal() as db:
    db.query(TripModel).filter(TripModel.user_id == USER_ID).delete()
    db.commit()

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
