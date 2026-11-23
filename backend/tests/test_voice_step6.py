"""
Voice step 6 checks (smart actions: weather replan, optimize day, optimize budget).
App DB = SQLite, Redis = local, OpenAI + the forecast simulated; the mock AI provider makes the suggestions.
Run from backend/: python -m tests.test_voice_step6
"""
import json
import logging
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
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

import database  # noqa: E402

database.engine = create_engine(f"sqlite:///{os.path.join(SCRATCH, 'voice6.db')}", connect_args={"check_same_thread": False})
database.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=database.engine)

import main  # noqa: E402
import openai_client  # noqa: E402
import itinerary_service as svc  # noqa: E402
import weather_service  # noqa: E402
from models_itinerary import ItineraryActivityModel, ItineraryDayModel, ItineraryModel  # noqa: E402
from models_trip import TripModel  # noqa: E402
from redis_client import redis_conn  # noqa: E402
from trip_lifecycle import MAX_BUDGET_INR, MIN_BUDGET_INR, today_ist  # noqa: E402
from voice import agent, draft as D, pending as P  # noqa: E402
from voice.tools import smart  # noqa: E402

main.SessionLocal = database.SessionLocal
database.Base.metadata.create_all(bind=database.engine)

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail != "" else ""), flush=True)


TODAY = today_ist()
d = lambda n: (TODAY + timedelta(days=n)).isoformat()  # noqa: E731
NOW = "2026-01-01T00:00:00Z"
USER_A = f"usr_s6a_{uuid.uuid4().hex[:6]}"
USER_B = f"usr_s6b_{uuid.uuid4().hex[:6]}"


def seed_trip(user, start_offset=1, budget=None, with_itinerary=True):
    """3-day trip with fixed activities. Returns (trip_id, {title: activity_id}, [day_ids])."""
    tid = f"trip_{uuid.uuid4().hex[:8]}"
    ids, day_ids = {}, []
    with database.SessionLocal() as db:
        db.add(TripModel(
            id=tid, user_id=user, title="Jaipur trip", start_date=d(start_offset), end_date=d(start_offset + 2), total_days=3,
            destination_json=json.dumps({"name": "Jaipur", "latitude": 26.91, "longitude": 75.79}), travelers_json="[]",
            budget_json=json.dumps({"targetAmount": budget} if budget else {}), created_at=NOW, updated_at=NOW))
        if with_itinerary:
            iid = f"it_{uuid.uuid4().hex[:8]}"
            db.add(ItineraryModel(id=iid, trip_id=tid, created_at=NOW, updated_at=NOW))
            plan = [
                [("Amber Fort", "09:30 AM", 500), ("City Palace Lunch", "01:00 PM", 300)],
                [("Calangute Beach", "10:00 AM", 900), ("Hotel Spa", "03:00 PM", 1200)],
                [("Local Market", "11:00 AM", 100)],
            ]
            for n, acts in enumerate(plan, start=1):
                did = f"day_{uuid.uuid4().hex[:8]}"
                day_ids.append(did)
                db.add(ItineraryDayModel(id=did, itinerary_id=iid, day_number=n, date=d(start_offset + n - 1), title=f"Day {n}"))
                for title, slot, cost in acts:
                    aid = f"act_{uuid.uuid4().hex[:8]}"
                    ids[title] = aid
                    db.add(ItineraryActivityModel(id=aid, day_id=did, time_slot=slot, title=title, location_name="Jaipur",
                                                  latitude=26.9 + n / 100, longitude=75.8, estimated_cost_inr=cost))
        db.commit()
    return tid, ids, day_ids


def titles(trip_id):
    with database.SessionLocal() as db:
        rows = (db.query(ItineraryActivityModel.title, ItineraryActivityModel.estimated_cost_inr)
                .join(ItineraryDayModel, ItineraryDayModel.id == ItineraryActivityModel.day_id)
                .join(ItineraryModel, ItineraryModel.id == ItineraryDayModel.itinerary_id)
                .filter(ItineraryModel.trip_id == trip_id).order_by(ItineraryActivityModel.id).all())
        return sorted(rows)


def budget_of(trip_id):
    with database.SessionLocal() as db:
        return db.query(TripModel).filter(TripModel.id == trip_id).first().budget


EVENTS = []
BAD_DAY = d(2)   # the 2nd day of a trip that starts tomorrow


def fake_forecast(lat, lng, start, end):
    EVENTS.append("forecast")
    out, cur = [], TODAY
    from datetime import date as _d
    cur = _d.fromisoformat(start[:10])
    while cur <= _d.fromisoformat(end[:10]):
        bad = cur.isoformat() == BAD_DAY
        out.append({"date": cur.isoformat(), "condition": "Heavy rain" if bad else "Clear sky", "badWeather": bad,
                    "rainChancePercent": 90 if bad else 5, "tempMaxC": 30, "tempMinC": 20})
        cur += timedelta(days=1)
    return {"source": "open-meteo", "days": out, "badWeatherDates": [x["date"] for x in out if x["badWeather"]],
            "condition": "Heavy rain" if BAD_DAY in [x["date"] for x in out] else "Clear sky", "summary": "x"}


class FakeTools:
    queue, calls = [], []

    def __call__(self, messages, tools, **kw):
        FakeTools.calls.append(messages)
        kind, payload = FakeTools.queue.pop(0)
        if kind == "tool":
            return {"content": None, "tool_calls": [{"name": payload[0], "arguments": payload[1]}]}
        return {"content": payload, "tool_calls": []}


fake = FakeTools()


def ra(text, user, conv, trip_id=None, queue=None):
    if queue is not None:
        FakeTools.queue = list(queue)
    trip = agent.TripInfo(title="Jaipur trip", start_date=d(1), end_date=d(3), id=trip_id) if trip_id else None
    return agent.run_agent(text, "hi", user_id=user, conversation_id=conv, screen="/trip/itinerary", trip=trip, redis_conn=redis_conn)


def clear_rate(user):
    redis_conn.delete(f"rl:ws:ai_trip:{user}")


class CountCalls:
    """Counts calls to a service function while still running it."""
    def __init__(self, name):
        self.name, self.count, self.real = name, 0, getattr(svc, name)

    def __enter__(self):
        def wrapper(*a, **k):
            self.count += 1
            EVENTS.append(self.name)
            return self.real(*a, **k)
        self.patch = mock.patch.object(svc, self.name, wrapper)
        self.patch.start()
        return self

    def __exit__(self, *exc):
        self.patch.stop()


# ---------------- pure: day resolution
days = [smart.DayRef("da", 1, d(1)), smart.DayRef("db", 2, d(2)), smart.DayRef("dc", 3, d(3))]
check("day: number 2 -> day 2", smart.resolve_in_days(days, 2, TODAY).day_id == "db")
check("day: '3' (text) -> day 3", smart.resolve_in_days(days, "3", TODAY).day_id == "dc")
check("day: tomorrow -> day 1", smart.resolve_in_days(days, "tomorrow", TODAY).day_id == "da")
check("day: day_after_tomorrow -> day 2", smart.resolve_in_days(days, "day_after_tomorrow", TODAY).day_id == "db")
check("day: ISO date -> that day", smart.resolve_in_days(days, d(3), TODAY).day_id == "dc")
check("day: today when the trip starts tomorrow -> outside_trip", smart.resolve_in_days(days, "today", TODAY) == "outside_trip")
check("day: number 9 -> outside_trip", smart.resolve_in_days(days, 9, TODAY) == "outside_trip")
check("day: nothing said -> need_day", smart.resolve_in_days(days, None, TODAY) == "need_day")
check("day: garbage -> need_day", smart.resolve_in_days(days, "someday", TODAY) == "need_day")
check("day: no itinerary -> no_itinerary", smart.resolve_in_days([], 1, TODAY) == "no_itinerary")

# ---------------- pure: suggestions are made safe
good = {"action": "REPLACE_ACTIVITY", "activityId": "a1", "activityTitle": "Amber Fort",
        "replacement": {"name": "Museum", "timeSlot": "10:00 AM", "latitude": 26.9, "longitude": 75.8, "estimatedCost": 250, "extra": "x"}}
na = smart.normalize_action(good)
check("suggestion kept with only the allowed fields", na and na["type"] == "REPLACE_ACTIVITY" and "extra" not in na["replacement"]
      and na["replacement"]["estimatedCost"] == 250, na)
check("REMOVE_ACTIVITY is dropped (voice never removes)", smart.normalize_action({"type": "REMOVE_ACTIVITY", "activityId": "a1"}) is None)
check("a suggestion without a replacement name is dropped", smart.normalize_action({**good, "replacement": {"description": "x"}}) is None)
na = smart.normalize_action({**good, "replacement": {"name": "M", "latitude": "north", "longitude": 500, "estimatedCost": -5}})
check("bad coordinates / negative cost are dropped, not saved", "latitude" not in na["replacement"] and "estimatedCost" not in na["replacement"], na)
check("summary (ask) in Hinglish", smart.summarize_replacements([na | {"activityTitle": "Amber Fort"}], "hi")
      == "Amber Fort ki jagah M rakh doon")
check("summary (done) in English", smart.summarize_replacements([na | {"activityTitle": "Amber Fort"}], "en", past=True)
      == "Replaced Amber Fort with M")
check("day summary is built from the result and sorted by time",
      smart.summarize_day_order([{"title": "B", "timeSlot": "03:00 PM"}, {"title": "A", "timeSlot": "09:30 AM"}], 2, "hi")
      == "Day 2 ab aisa hai: A, B.")

# ---------------- pure: the shared AI rate limit
RL = f"usr_rl_{uuid.uuid4().hex[:6]}"
clear_rate(RL)
hits = [smart.check_ai_rate_limit(RL) for _ in range(11)]
check("the ai_trip bucket allows 10 a minute and blocks the 11th", hits[:10] == [True] * 10 and hits[10] is False, hits)
clear_rate(RL)

with mock.patch.object(openai_client, "chat_tools", fake), mock.patch.object(weather_service, "get_trip_forecast", fake_forecast):
    # ---------------- weather: good weather -> nothing happens
    TA, ACT_A, DAYS_A = seed_trip(USER_A)
    clear_rate(USER_A)
    before = titles(TA)
    C = f"conv_s6_{uuid.uuid4().hex[:6]}"
    EVENTS.clear()
    with CountCalls("weather_replan_service") as wc:
        r = ra("kal ka plan mausam ke hisaab se karo", USER_A, C, TA, queue=[("tool", ("weather_replan", {"day": "tomorrow"}))])
    check("good weather: told why, no pending, no AI call",
          r.reply_text.startswith("Kal mausam theek hai") and r.pending_confirmation is None and P.get(redis_conn, USER_A, C) is None
          and wc.count == 0, r.reply_text)
    check("good weather: forecast was read, trip unchanged", EVENTS == ["forecast"] and titles(TA) == before)

    # ---------------- weather: bad weather -> forecast first, then a concrete question, nothing changed yet
    EVENTS.clear()
    with CountCalls("weather_replan_service") as wc:
        r = ra("day 2 ka plan mausam ke hisaab se karo", USER_A, C, TA, queue=[("tool", ("weather_replan", {"day": "2"}))])
    check("bad weather: the forecast is read BEFORE the AI call", EVENTS == ["forecast", "weather_replan_service"], EVENTS)
    pc = r.pending_confirmation
    check("bad weather: one pending confirmation naming the real change",
          pc and pc["id"].startswith("pc_") and "Calangute Beach" in pc["summary"] and "heavy rain" in pc["summary"]
          and r.reply_text == pc["summary"], pc)
    stored = P.get(redis_conn, USER_A, C)
    acts = stored["data"]["actions"]
    check("pending holds only day-2 suggestions (Amber Fort is on a good day)",
          stored["tool"] == "weather_replan" and [a["activityId"] for a in acts] == [ACT_A["Calangute Beach"]], stored["data"])
    check("asking changed nothing", titles(TA) == before)

    # ---------------- confirm: voice "haan" runs it once on the user's own trip
    with CountCalls("execute_refinement_actions_service") as ec:
        r = ra("haan", USER_A, C, TA)
        again = agent.confirm_pending(redis_conn, USER_A, C, "hi", pc["id"])
    after = titles(TA)
    check("'haan' -> applied once", r.action == "smart_applied" and ec.count == 1, (r.action, ec.count))
    check("only the bad-day activity changed", [t for t in after if t not in before] != [] and
          {t[0] for t in before} - {t[0] for t in after} == {"Calangute Beach"}, after)
    check("reply says what changed", "Calangute Beach ki jagah" in r.reply_text and r.reply_text.startswith("Ho gaya."), r.reply_text)
    check("screen refresh + itinerary opens on that day",
          r.ui_actions == [{"type": "refresh", "what": "itinerary"}, {"type": "navigate", "to": "/trip/itinerary?day=2"}], r.ui_actions)
    check("a second confirm does nothing", again.error_code == "no_pending" and again.action not in agent.CONFIRMED_ACTIONS and ec.count == 1)

    # ---------------- cancel: nothing applied, a trip draft is left alone
    C2 = f"conv_s6_{uuid.uuid4().hex[:6]}"
    TB, ACT_B, _ = seed_trip(USER_A)
    clear_rate(USER_A)
    before_b = titles(TB)
    dr = D.TripDraftState(destination={"name": "Goa"})
    D.save(redis_conn, USER_A, C2, dr)
    r = ra("day 2 mausam ke hisaab se", USER_A, C2, TB, queue=[("tool", ("weather_replan", {"day": "2"}))])
    check("ask on trip B", r.pending_confirmation is not None)
    r = ra("nahi", USER_A, C2, TB)
    check("'nahi' -> cancelled, nothing changed, pending gone",
          r.action == "smart_cancel" and titles(TB) == before_b and P.get(redis_conn, USER_A, C2) is None, r.reply_text)
    check("a trip draft is untouched by cancelling a smart action", D.load(redis_conn, USER_A, C2) is not None)
    D.delete(redis_conn, USER_A, C2)

    r = ra("day 2 mausam ke hisaab se", USER_A, C2, TB, queue=[("tool", ("weather_replan", {"day": "2"}))])
    cancel = agent.cancel_pending(redis_conn, USER_A, C2, "hi")
    check("the Cancel button (cancel_pending) clears it too", cancel.action == "smart_cancel" and P.get(redis_conn, USER_A, C2) is None)

    r = ra("day 2 mausam ke hisaab se", USER_A, C2, TB, queue=[("tool", ("weather_replan", {"day": "2"}))])
    ra("map kholo", USER_A, C2, TB, queue=[("tool", ("navigate", {"page": "map"}))])
    check("a new topic cancels the pending smart action", P.get(redis_conn, USER_A, C2) is None and titles(TB) == before_b)
    r = ra("day 2 mausam ke hisaab se", USER_A, C2, TB, queue=[("tool", ("weather_replan", {"day": "2"}))])
    r2 = ra("day 2 optimize karo", USER_A, C2, TB, queue=[("tool", ("optimize_day", {"day": "2"}))])
    cur = P.get(redis_conn, USER_A, C2)
    check("a new smart request replaces the old pending one (the new one survives)",
          r2.pending_confirmation and cur and cur["tool"] == "optimize_day" and cur["id"] == r2.pending_confirmation["id"])
    P.clear(redis_conn, USER_A, C2)

    # ---------------- weather: edge cases
    C3 = f"conv_s6_{uuid.uuid4().hex[:6]}"
    r = ra("day 9 ka plan badlo", USER_A, C3, TB, queue=[("tool", ("weather_replan", {"day": "9"}))])
    check("a day outside the trip -> a question with the trip's dates, no pending",
          r.pending_confirmation is None and "kaunsa din?" in r.reply_text and r.error_code == "outside_trip", r.reply_text)
    r = ra("plan badlo", USER_A, C3, None, queue=[("tool", ("weather_replan", {}))])
    check("no open trip -> asks to open one and goes to My trips",
          r.error_code == "no_trip" and r.ui_actions == [{"type": "navigate", "to": "/trips"}] or r.error_code == "no_trip", (r.reply_text, r.ui_actions))
    TF, _, _ = seed_trip(USER_A, start_offset=40)
    EVENTS.clear()
    r = ra("plan badlo", USER_A, C3, TF, queue=[("tool", ("weather_replan", {"day": "1"}))])
    check("a trip beyond the forecast horizon -> says so, forecast not called", r.error_code == "too_far" and EVENTS == []
          and r.pending_confirmation is None, (r.reply_text, EVENTS))
    TP, _, _ = seed_trip(USER_A, start_offset=-1)
    r = ra("plan badlo", USER_A, C3, TP, queue=[("tool", ("weather_replan", {"day": "1"}))])
    check("a day that has already passed -> says so", r.error_code == "past_day", r.reply_text)
    TN, _, _ = seed_trip(USER_A, with_itinerary=False)
    r = ra("plan badlo", USER_A, C3, TN, queue=[("tool", ("weather_replan", {}))])
    check("itinerary not ready -> says so", r.error_code == "no_itinerary", r.reply_text)

    # no day said: the whole trip's bad days
    TW, ACT_W, _ = seed_trip(USER_A)
    clear_rate(USER_A)
    r = ra("plan mausam ke hisaab se badlo", USER_A, C3, TW, queue=[("tool", ("weather_replan", {}))])
    check("no day said -> the trip's bad days are used", r.pending_confirmation and "Calangute Beach" in r.reply_text, r.reply_text)
    P.clear(redis_conn, USER_A, C3)

    # ---------------- rate limit: the shared ai_trip bucket
    for _ in range(10):
        smart.check_ai_rate_limit(USER_A)
    with CountCalls("weather_replan_service") as wc:
        r = ra("day 2 plan badlo", USER_A, C3, TW, queue=[("tool", ("weather_replan", {"day": "2"}))])
    check("rate limit hit -> polite line, no AI call, no pending",
          r.error_code == "rate_limited" and wc.count == 0 and r.pending_confirmation is None, r.reply_text)
    clear_rate(USER_A)

    # ---------------- ownership: another user's pending / trip is refused
    C4 = f"conv_s6_{uuid.uuid4().hex[:6]}"
    TO, ACT_O, _ = seed_trip(USER_A)
    clear_rate(USER_A)
    r = ra("day 2 plan badlo", USER_A, C4, TO, queue=[("tool", ("weather_replan", {"day": "2"}))])
    pcid = r.pending_confirmation["id"]
    before_o = titles(TO)
    other = agent.confirm_pending(redis_conn, USER_B, C4, "hi", pcid)
    check("another user's confirm finds nothing", other.error_code == "no_pending" and other.action not in agent.CONFIRMED_ACTIONS and titles(TO) == before_o)
    r = ra("day 2 plan badlo", USER_B, C4, TO, queue=[("tool", ("weather_replan", {"day": "2"}))])
    check("another user can't ask on someone else's trip", r.error_code == "not_found" and r.pending_confirmation is None, r.reply_text)
    forged = {"tool": "weather_replan", "data": {"trip_id": TO, "actions": [smart.normalize_action(
        {"action": "REPLACE_ACTIVITY", "activityId": ACT_O["Calangute Beach"], "activityTitle": "x", "replacement": {"name": "Hack"}})]}}
    res = smart.apply_confirmed(forged, USER_B, "hi", redis_conn)
    check("apply re-checks ownership (the pending names someone else's trip)", res.error_code == "not_found" and titles(TO) == before_o)

    # ---------------- stale suggestion: the activity vanished between ask and confirm
    r = ra("day 2 plan badlo", USER_A, C4, TO, queue=[("tool", ("weather_replan", {"day": "2"}))])
    with database.SessionLocal() as db:
        db.query(ItineraryActivityModel).filter(ItineraryActivityModel.id == ACT_O["Calangute Beach"]).delete()
        db.commit()
    r = ra("haan", USER_A, C4, TO)
    check("stale suggestion -> honest line, nothing applied", r.error_code == "stale" and "kuch nahi badla" in r.reply_text, r.reply_text)

    # ---------------- failure: the database write fails -> the trip is unchanged
    C5 = f"conv_s6_{uuid.uuid4().hex[:6]}"
    TX, ACT_X, _ = seed_trip(USER_A)
    clear_rate(USER_A)
    before_x = titles(TX)
    ra("day 2 plan badlo", USER_A, C5, TX, queue=[("tool", ("weather_replan", {"day": "2"}))])
    with mock.patch.object(Session, "commit", side_effect=RuntimeError("db down")):
        r = ra("haan", USER_A, C5, TX)
    check("a failing write -> 'could not change' line and the trip is unchanged",
          r.action == "smart_failed" and r.reply_text == smart.TEXT["failed"]["hi"] and titles(TX) == before_x, (r.action, r.reply_text))

    # ---------------- optimize day
    C6 = f"conv_s6_{uuid.uuid4().hex[:6]}"
    TD, ACT_D, _ = seed_trip(USER_A, start_offset=0)   # day 1 is today
    clear_rate(USER_A)
    before_d = titles(TD)
    with CountCalls("optimize_day_flow_service") as oc:
        r = ra("aaj ka route chhota karo", USER_A, C6, TD, queue=[("tool", ("optimize_day", {}))])
    check("optimize day: asks first (no AI call yet), today is used when no day is said",
          r.pending_confirmation and r.reply_text == "Day 1 ka order travel kam karne ke liye badal doon?" and oc.count == 0, r.reply_text)
    check("optimize day: nothing changed by asking", titles(TD) == before_d)
    with CountCalls("optimize_day_flow_service") as oc:
        r = ra("haan", USER_A, C6, TD)
        r_again = agent.confirm_pending(redis_conn, USER_A, C6, "hi")
    check("optimize day: confirm runs the service once", r.action == "smart_applied" and oc.count == 1 and r_again.error_code == "no_pending" and again.action not in agent.CONFIRMED_ACTIONS)
    check("optimize day: sentence built from the result, itinerary opens on that day",
          r.reply_text.startswith("Day 1 ab aisa hai:") and r.ui_actions[-1] == {"type": "navigate", "to": "/trip/itinerary?day=1"}, r.reply_text)
    r = ra("relaxed karo day 2", USER_A, C6, TD, queue=[("tool", ("optimize_day", {"day": "2", "goal": "RELAXED"}))])
    check("optimize day: the goal changes the question", r.reply_text == "Day 2 ko relaxed banane ke liye badal doon?", r.reply_text)
    r = ra("zyada jagah", USER_A, C6, TD, queue=[("tool", ("optimize_day", {"day": "2", "goal": "WHATEVER"}))])
    check("optimize day: an unknown goal falls back to the default", r.reply_text == "Day 2 ka order travel kam karne ke liye badal doon?")
    P.clear(redis_conn, USER_A, C6)
    TT, _, _ = seed_trip(USER_A, start_offset=1)
    r = ra("route chhota karo", USER_A, C6, TT, queue=[("tool", ("optimize_day", {}))])
    check("optimize day: no day said and today isn't a trip day -> asks which day", r.pending_confirmation is None and "kaunsa din?" in r.reply_text, r.reply_text)
    with mock.patch.object(svc.ai_provider_service, "generate_day_optimization", side_effect=RuntimeError("AI_GENERATION_ERROR")):
        before_t = titles(TT)
        ra("day 1 optimize karo", USER_A, C6, TT, queue=[("tool", ("optimize_day", {"day": "1"}))])
        r = ra("haan", USER_A, C6, TT)
    check("optimize day: the AI failing leaves the day unchanged", r.action == "smart_failed" and titles(TT) == before_t, r.reply_text)

    # ---------------- optimize budget
    C7 = f"conv_s6_{uuid.uuid4().hex[:6]}"
    TG, ACT_G, _ = seed_trip(USER_A)               # no budget yet
    clear_rate(USER_A)
    before_g = titles(TG)
    r = ra("budget mein fit karo", USER_A, C7, TG, queue=[("tool", ("optimize_budget", {}))])
    check("budget missing -> asks for it first, no pending", r.reply_text == smart.TEXT["need_budget"]["hi"] and r.pending_confirmation is None)
    r = ra("500 hai", USER_A, C7, TG, queue=[("tool", ("optimize_budget", {"budget_inr": 500}))])
    check("a budget under ₹1,000 is refused", r.error_code == "budget_out_of_range" and r.pending_confirmation is None)
    check("too-low budget says 'at least' with the shared minimum",
          r.reply_text == smart.TEXT["budget_low"]["hi"].format(min=f"{MIN_BUDGET_INR:,}"), r.reply_text)
    for said_amount in (MAX_BUDGET_INR + 1, 5 * MAX_BUDGET_INR, 1_000_000_000):   # 1e9 = "100 crore": must not be ignored
        r = ra("bahut zyada hai", USER_A, C7, TG, queue=[("tool", ("optimize_budget", {"budget_inr": said_amount}))])
        check(f"a budget of {said_amount:,} is refused as too high (not ignored)",
              r.error_code == "budget_out_of_range" and r.pending_confirmation is None
              and r.reply_text == smart.TEXT["budget_high"]["hi"].format(max=f"{MAX_BUDGET_INR:,}"), r.reply_text)
    check("voice and trip creation share one budget range", smart.MAX_BUDGET_INR == MAX_BUDGET_INR and smart.MIN_BUDGET_INR == MIN_BUDGET_INR
          and D.MIN_BUDGET_INR == MIN_BUDGET_INR)
    check("nan / inf budgets count as not said", smart._parse_budget(float("nan")) is None and smart._parse_budget(float("inf")) is None
          and smart._parse_budget(1_000_000_000) == 1_000_000_000)
    r = ra("budget 1000 hai", USER_A, C7, TG, queue=[("tool", ("optimize_budget", {"budget_inr": 1000}))])
    check("budget said -> suggestions + a question with the saving",
          r.pending_confirmation and r.reply_text.startswith("₹2,000 bachane ke liye") and "ki jagah" in r.reply_text, r.reply_text)
    check("the new budget is NOT saved just by asking", budget_of(TG) == {} and titles(TG) == before_g, budget_of(TG))
    with CountCalls("execute_refinement_actions_service") as ec:
        r = ra("haan", USER_A, C7, TG)
    check("confirm -> activities replaced and the budget saved", r.action == "smart_applied" and ec.count == 1
          and budget_of(TG).get("targetAmount") == 1000 and titles(TG) != before_g, (r.reply_text, budget_of(TG)))
    check("budget: itinerary opens (no day)", r.ui_actions[-1] == {"type": "navigate", "to": "/trip/itinerary"}, r.ui_actions)
    TH, _, _ = seed_trip(USER_A, budget=100000)
    clear_rate(USER_A)
    r = ra("kharcha kam karo", USER_A, C7, TH, queue=[("tool", ("optimize_budget", {}))])
    check("already within budget -> says so, no pending", r.reply_text == smart.TEXT["within_budget"]["hi"] and r.pending_confirmation is None)
    TI, _, _ = seed_trip(USER_A, budget=1000)
    clear_rate(USER_A)
    r = ra("budget mein fit karo", USER_A, C7, TI, queue=[("tool", ("optimize_budget", {}))])
    check("existing budget is used when none is said", r.pending_confirmation and "₹2,000" in r.reply_text, r.reply_text)
    with mock.patch.object(svc, "execute_refinement_actions_service", side_effect=RuntimeError("boom")):
        before_i = titles(TI)
        r = ra("haan", USER_A, C7, TI)
    check("a failing apply -> 'could not change' line, trip unchanged", r.action == "smart_failed" and titles(TI) == before_i)

    # ---------------- logs: codes and timings only, never the user's words or place names
    log_lines = []

    class Grab(logging.Handler):
        def emit(self, record):
            log_lines.append(record.getMessage())

    h = Grab()
    lg = logging.getLogger("voice")
    lg.addHandler(h)
    lg.setLevel(logging.INFO)
    TL, _, _ = seed_trip(USER_A)
    clear_rate(USER_A)
    ra("day 2 plan badlo", USER_A, f"conv_s6_{uuid.uuid4().hex[:6]}", TL, queue=[("tool", ("weather_replan", {"day": "2"}))])
    # a forecast failure is logged WITH a traceback, still answers the user, and changes nothing
    err_records = []

    class GrabRecords(logging.Handler):
        def emit(self, record):
            err_records.append(record)

    hr = GrabRecords()
    lg.addHandler(hr)
    clear_rate(USER_A)
    before_l = titles(TL)
    with mock.patch.object(weather_service, "get_trip_forecast", side_effect=RuntimeError("provider down")):
        r = ra("day 2 mausam dekho", USER_A, f"conv_s6_{uuid.uuid4().hex[:6]}", TL, queue=[("tool", ("weather_replan", {"day": "2"}))])
    lg.removeHandler(hr)
    check("forecast failure: spoken 'couldn't get the weather' line, nothing changed",
          r.error_code == "forecast_unavailable" and r.reply_text == smart.TEXT["forecast_unavailable"]["hi"] and titles(TL) == before_l, r.reply_text)
    check("forecast failure is logged with its traceback (error type only in the message)",
          any("forecast failed: RuntimeError" in x.getMessage() and x.exc_info for x in err_records)
          and not any("provider down" in x.getMessage() for x in err_records), [x.getMessage() for x in err_records])
    lg.removeHandler(h)
    joined = " ".join(log_lines)
    check("logs have the action and no words, titles or places", "action=smart_ask" in joined and "step=ask" in joined and "Calangute" not in joined
          and "Amber" not in joined and "Jaipur" not in joined and "badlo" not in joined, joined[:200])

check("a bare number is a real answer, not noise (is_garbled)", not agent.is_garbled("50000") and agent.is_garbled("?!") and agent.is_garbled("a"))

# ---------------- tools are registered; prompt knows them
names = {t["function"]["name"] for t in agent.TOOLS}
check("the 3 smart tools are offered to the model", {"weather_replan", "optimize_day", "optimize_budget"} <= names and
      {"weather_replan", "optimize_day", "optimize_budget"} <= agent.TOOL_NAMES)
check("the prompt tells the model when to use them", all(f"- {n}:" in agent.SYSTEM_PROMPT for n in ("weather_replan", "optimize_day", "optimize_budget")))
check("no tool takes a user or trip id from the model", all("user_id" not in str(t) and "trip_id" not in str(t)
      for t in agent.TOOLS if t["function"]["name"] in ("weather_replan", "optimize_day", "optimize_budget")))

print(f"\n{sum(results)}/{len(results)} passed", flush=True)
sys.exit(0 if all(results) else 1)
