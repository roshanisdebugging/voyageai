"""
Itinerary generation reliability: OpenAI (90 s) -> Groq (60 s) -> stop. No Gemini.
Run from backend/: python -m tests.test_itinerary_reliability
No real AI call: requests.post inside openai_client is a fake routed by URL (OpenAI / Groq); Gemini is counted
and must never be called. A throwaway SQLite database holds the trips; the itinerary cache is patched out.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

import dotenv

dotenv.load_dotenv = lambda *a, **k: None   # never read the real backend/.env (keys)
os.environ["DATABASE_URL"] = "postgresql://x:y@127.0.0.1:1/none"
os.environ["AI_PROVIDER"] = "openai"
os.environ["OPENAI_API_KEY"] = "test-openai-key-not-real"
os.environ["GROQ_API_KEY"] = "test-groq-key-not-real"
os.environ["OPENAI_MODEL"] = "gpt-4.1-mini"
os.environ["OPENAI_REASONING_EFFORT"] = "low"     # the owner's .env has this; gpt-4.1-mini must still not get it
for k in ("GROQ_MODEL", "OPENAI_ITINERARY_TIMEOUT_S", "GROQ_ITINERARY_TIMEOUT_S"):
    os.environ.pop(k, None)

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)
SCRATCH = tempfile.mkdtemp(prefix="voyageai_test_")

import requests  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

import database  # noqa: E402

database.engine = create_engine(f"sqlite:///{os.path.join(SCRATCH, 'app.db')}", connect_args={"check_same_thread": False})
database.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=database.engine)

import models_db  # noqa: E402,F401
import models_itinerary  # noqa: E402
import models_trip  # noqa: E402
import models_place  # noqa: E402,F401
import ai_provider  # noqa: E402
import itinerary_service  # noqa: E402
import openai_client  # noqa: E402

database.Base.metadata.create_all(bind=database.engine)
results = []


def check(name, cond, info=None):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if (info is not None and not cond) else ""))


# ---------------------------------------------------------------- fakes
itinerary_service.get_cached_itinerary = lambda key: None
itinerary_service.set_cached_itinerary = lambda key, value: None
sleeps = []
ai_provider._sleep = lambda s: sleeps.append(s)

gemini_calls = []
ai_provider.GeminiProvider._execute_gemini_request = lambda self, *a, **k: gemini_calls.append(1) or (_ for _ in ()).throw(
    AssertionError("Gemini must not be called"))
ai_provider.GeminiProvider.generate_itinerary_json = lambda self, *a, **k: gemini_calls.append(1) or (_ for _ in ()).throw(
    AssertionError("Gemini must not be called"))


class Resp:
    def __init__(self, status, body=None, headers=None):
        self.status_code = status
        self._body = body if body is not None else {}
        self.headers = headers or {}
        self.text = json.dumps(self._body)

    def json(self):
        return self._body


def answer(text):
    return Resp(200, {"choices": [{"message": {"content": text}, "finish_reason": "stop"}]})


calls = []           # (who, body, timeout)
script = {"OPENAI": [], "GROQ": []}   # per provider: list of responses / exceptions, used in order


def fake_post(url, headers=None, json=None, timeout=None, **kw):
    who = "GROQ" if "api.groq.com" in url else "OPENAI" if "api.openai.com" in url else "OTHER"
    if who == "OTHER":
        gemini_calls.append(url)
        raise AssertionError(f"unexpected URL {url}")
    calls.append((who, dict(json), timeout, headers.get("Authorization", "")))
    step = script[who].pop(0) if script[who] else Resp(500, {"error": {"code": "script_empty"}})
    if isinstance(step, Exception):
        raise step
    return step


openai_client.requests.post = fake_post

GOA = {"name": "Goa", "country": "India", "latitude": 15.2993, "longitude": 74.124}


def make_trip(days=3):
    import uuid
    from datetime import date, timedelta
    start = date(2027, 2, 10)
    trip = models_trip.TripModel(
        id=f"trip_{uuid.uuid4().hex[:8]}", user_id="u_test", title=f"Goa {days} days",
        itinerary_status="GENERATING", start_date=start.isoformat(),
        end_date=(start + timedelta(days=days - 1)).isoformat(), total_days=days,
        destination_json=json.dumps(GOA), travelers_json=json.dumps([{"type": "ADULT"}, {"type": "ADULT"}]),
        preferences_snapshot_json=json.dumps({"travelStyles": ["relaxed"]}),
        budget_json=json.dumps({"level": "moderate"}), created_at="2026-11-24T00:00:00Z", updated_at="2026-11-24T00:00:00Z")
    db = database.SessionLocal()
    db.add(trip)
    db.commit()
    tid = trip.id
    db.close()
    return tid


def valid_json_for(trip_id):
    """A valid itinerary for this trip (the mock provider's output passes the schema + integrity check)."""
    db = database.SessionLocal()
    trip = db.query(models_trip.TripModel).filter_by(id=trip_id).first()
    ai_input = {"destination": trip.destination, "origin": None, "startDate": trip.start_date, "endDate": trip.end_date,
                "totalDays": trip.total_days, "travelersCount": 2, "adultsCount": 2, "childrenCount": 0,
                "budget": trip.budget, "preferencesSnapshot": trip.preferences_snapshot}
    db.close()
    return ai_provider.MockAIProvider().generate_itinerary_json(ai_input, "")


def run(trip_id):
    status = itinerary_service.process_async_itinerary_generation(trip_id, database.SessionLocal)
    db = database.SessionLocal()
    trip = db.query(models_trip.TripModel).filter_by(id=trip_id).first()
    itin = db.query(models_itinerary.ItineraryModel).filter_by(trip_id=trip_id).first()
    out = (status, trip.itinerary_status, itin.provider_name if itin else None)
    db.close()
    return out


def reset(openai=(), groq=()):
    calls.clear()
    sleeps.clear()
    gemini_calls.clear()
    script["OPENAI"] = list(openai)
    script["GROQ"] = list(groq)


def who_called():
    return [c[0] for c in calls]


# ---------------------------------------------------------------- 1. OpenAI ReadTimeout -> no retry -> Groq
tid = make_trip(3)
good = valid_json_for(tid)
reset(openai=[requests.exceptions.ReadTimeout()], groq=[answer(good)])
status, istatus, provider = run(tid)
check("ReadTimeout: OpenAI tried once, NOT retried, then Groq", who_called() == ["OPENAI", "GROQ"], who_called())
check("ReadTimeout: no backoff sleep", sleeps == [], sleeps)
check("ReadTimeout -> Groq answers: READY, provider_name GROQ", (status, istatus, provider) == ("READY", "READY", "GROQ"),
      (status, istatus, provider))
check("Gemini never called", gemini_calls == [])
groq_body, groq_timeout = calls[1][1], calls[1][2]
check("Groq: OpenAI-compatible endpoint, Groq key, JSON mode, temperature 0.2, gpt-oss-120b",
      calls[1][3] == "Bearer test-groq-key-not-real" and groq_body["response_format"] == {"type": "json_object"}
      and groq_body["temperature"] == 0.2 and groq_body["model"] == "openai/gpt-oss-120b", groq_body)
check("Groq timeout: 10 s connect, 60 s read by default", groq_timeout == (10.0, 60.0), groq_timeout)
check("Groq: explicit output limit 16384 (the default cut a 6-day plan off)",
      groq_body.get("max_completion_tokens") == 16384, groq_body.get("max_completion_tokens"))

# ---------------------------------------------------------------- 2. OpenAI 503 once -> one retry -> success
tid = make_trip(3)
good = valid_json_for(tid)
reset(openai=[Resp(503, {"error": {"code": "overloaded"}}), answer(good)])
status, istatus, provider = run(tid)
check("503 once: one retry with OpenAI, no Groq", who_called() == ["OPENAI", "OPENAI"], who_called())
check("503 once: 1-2 s jittered backoff", len(sleeps) == 1 and 1.0 <= sleeps[0] <= 2.0, sleeps)
check("503 once -> READY with provider_name OPENAI", (status, provider) == ("READY", "OPENAI"), (status, provider))

reset(openai=[requests.exceptions.ConnectionError(), answer(good)])
tid2 = make_trip(3)
reset(openai=[requests.exceptions.ConnectionError(), answer(valid_json_for(tid2))])
status, _, provider = run(tid2)
check("connection error: one retry, then OpenAI answers", who_called() == ["OPENAI", "OPENAI"] and provider == "OPENAI",
      who_called())

tid3 = make_trip(3)
reset(openai=[Resp(401, {"error": {"code": "invalid_api_key"}})], groq=[answer(valid_json_for(tid3))])
status, _, provider = run(tid3)
check("401 (bad OpenAI key): no OpenAI retry, straight to Groq", who_called() == ["OPENAI", "GROQ"] and provider == "GROQ",
      who_called())

# ---------------------------------------------------------------- 3. both fail -> FAILED, no Gemini
tid = make_trip(3)
reset(openai=[Resp(500), Resp(500)], groq=[Resp(500)])
status, istatus, provider = run(tid)
check("OpenAI + Groq fail: trip FAILED, nothing saved", (status, istatus, provider) == ("FAILED", "FAILED", None),
      (status, istatus, provider))
check("OpenAI + Groq fail: OpenAI x2 (5xx retry), Groq x1, then stop", who_called() == ["OPENAI", "OPENAI", "GROQ"], who_called())
check("OpenAI + Groq fail: Gemini never called", gemini_calls == [])

# ---------------------------------------------------------------- 4. no GROQ_API_KEY
os.environ.pop("GROQ_API_KEY")
tid = make_trip(3)
reset(openai=[requests.exceptions.ReadTimeout()])
try:
    status, istatus, provider = run(tid)
    crashed = False
except Exception as e:  # pragma: no cover
    crashed, status, istatus = True, None, str(e)
check("no GROQ_API_KEY: no crash, Groq skipped (no Groq request), trip FAILED",
      not crashed and who_called() == ["OPENAI"] and (status, istatus) == ("FAILED", "FAILED"), (who_called(), status))
os.environ["GROQ_API_KEY"] = "test-groq-key-not-real"

# ---------------------------------------------------------------- 5. Groq 429
tid = make_trip(3)
reset(openai=[requests.exceptions.ReadTimeout()],
      groq=[Resp(429, {"error": {"code": "rate_limit_exceeded"}}, {"retry-after": "30"})])
status, istatus, _ = run(tid)
check("Groq 429 retry-after 30 s: no retry, clean FAILED", who_called() == ["OPENAI", "GROQ"] and status == "FAILED"
      and sleeps == [], (who_called(), sleeps))

tid = make_trip(3)
reset(openai=[requests.exceptions.ReadTimeout()],
      groq=[Resp(429, {"error": {"code": "rate_limit_exceeded"}}, {"retry-after": "2"}), answer(valid_json_for(tid))])
status, _, provider = run(tid)
check("Groq 429 retry-after 2 s: waits 2 s, retries once, GROQ answers",
      who_called() == ["OPENAI", "GROQ", "GROQ"] and sleeps == [2.0] and provider == "GROQ", (who_called(), sleeps))

# ---------------------------------------------------------------- 6. timeouts
tid = make_trip(6)
good6 = valid_json_for(tid)
reset(openai=[answer(good6)])
status, _, provider = run(tid)
check("6-day trip on OpenAI: READY, provider OPENAI", (status, provider) == ("READY", "OPENAI"))
check("OpenAI itinerary timeout: 10 s connect, 90 s read by default", calls[0][2] == (10.0, 90.0), calls[0][2])
os.environ["OPENAI_ITINERARY_TIMEOUT_S"] = "150"
os.environ["GROQ_ITINERARY_TIMEOUT_S"] = "45"
check("OPENAI_ITINERARY_TIMEOUT_S / GROQ_ITINERARY_TIMEOUT_S read from env",
      ai_provider.itinerary_openai_timeout() == 150.0 and ai_provider.itinerary_groq_timeout() == 45.0)
os.environ["OPENAI_ITINERARY_TIMEOUT_S"] = "nonsense"
check("bad timeout value -> default 90", ai_provider.itinerary_openai_timeout() == 90.0)
os.environ.pop("OPENAI_ITINERARY_TIMEOUT_S")
os.environ.pop("GROQ_ITINERARY_TIMEOUT_S")

reset(openai=[answer("{}")])
openai_client.chat_json("x")   # a short non-itinerary call
check("other OpenAI calls keep their own timeout (30 s here)", calls[0][2] == 30, calls[0][2])

# ---------------------------------------------------------------- 7. reasoning_effort
check("gpt-4.1-mini itinerary request carries no reasoning_effort (OPENAI_REASONING_EFFORT=low is set)",
      all("reasoning_effort" not in body for who, body, _, _ in calls if who == "OPENAI"))
tid = make_trip(3)
reset(openai=[requests.exceptions.ReadTimeout()], groq=[answer(valid_json_for(tid))])
run(tid)
check("Groq gpt-oss-120b (a reasoning model) gets reasoning_effort, first try",
      calls[1][1].get("reasoning_effort") == "low" and len([c for c in calls if c[0] == "GROQ"]) == 1)

# ---------------------------------------------------------------- 8. invalid output
tid = make_trip(3)
reset(openai=[requests.exceptions.ReadTimeout()], groq=[answer("this is not json"), answer("{\"days\": \"nope\"}")])
status, istatus, provider = run(tid)
check("invalid JSON from Groq: one Groq retry, then FAILED", who_called() == ["OPENAI", "GROQ", "GROQ"]
      and (status, istatus, provider) == ("FAILED", "FAILED", None), (who_called(), status))
check("the Groq retry uses the correction prompt", "IMPORTANT CORRECTION" in calls[2][1]["messages"][0]["content"])

tid = make_trip(3)
reset(openai=[answer("{\"bad\": true}"), answer(valid_json_for(tid))])
status, _, provider = run(tid)
check("invalid output from OpenAI: one OpenAI retry fixes it, provider OPENAI",
      who_called() == ["OPENAI", "OPENAI"] and provider == "OPENAI", who_called())

tid = make_trip(3)
reset(openai=[answer("{\"bad\": true}"), answer("{\"bad\": 2}")], groq=[answer(valid_json_for(tid))])
status, _, provider = run(tid)
check("OpenAI invalid twice -> next step Groq answers, provider GROQ",
      who_called() == ["OPENAI", "OPENAI", "GROQ"] and provider == "GROQ", who_called())

# ---------------------------------------------------------------- 9. the old fallback object can't reach Gemini
reset(openai=[Resp(500), Resp(500)], groq=[Resp(500)])
try:
    ai_provider.FallbackAIProvider([ai_provider.OpenAIProvider(), ai_provider.GeminiProvider()]).generate_itinerary_json({}, "p")
    raised = False
except ai_provider.ItineraryGenerationError:
    raised = True
check("FallbackAIProvider.generate_itinerary_json uses OpenAI -> Groq, never Gemini",
      raised and gemini_calls == [] and who_called() == ["OPENAI", "OPENAI", "GROQ"], who_called())

passed = sum(1 for _, ok in results if ok)
print(f"\n{passed}/{len(results)} passed")
sys.exit(0 if passed == len(results) else 1)
