"""
Step 6 smart actions by voice (voicefirst.md "Step 6 in detail", docs/voice-step6-plan.md).

  weather_replan(day?)          read the real forecast first; bad weather -> suggest indoor swaps -> ask -> apply
  optimize_day(day?, goal?)     ask first; on "haan" reorder that day (the AI call + write happen only then)
  optimize_budget(budget_inr?)  suggest cheaper swaps -> ask -> apply

Nothing here changes data until the user confirms. The ask turn only reads (and asks the AI for suggestions);
the confirm turn (apply_confirmed) is the only place that writes, through the existing services, after checking
ownership again. Suggestions are stored in the pending confirmation (voice/pending.py) and applied with
itinerary_service.execute_refinement_actions_service, which only touches activities of that trip.
Voice only REPLACES activities, it never removes them.

Every user comes from the server-side session and every trip is looked up by that user (ownership.find_owned_trip).
The model supplies only language-neutral values (an enum, a day word/number/date, a rupee amount); code resolves them.
Replies are templates ("hi" = the Hindi voice, written in Roman Hinglish like the rest of voice/; "en" = English). Logs carry codes and timings only, never user words.
"""
from __future__ import annotations

import logging
import math
import re
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Union

from trip_lifecycle import MAX_BUDGET_INR, MIN_BUDGET_INR   # the one budget range, shared with trip creation
from trip_area import PlaceOutsideTripArea
from voice import pages
from voice import pending as P

logger = logging.getLogger("voice")

SMART_TOOL_NAMES = ("weather_replan", "optimize_day", "optimize_budget", "set_trip_budget")
GOALS = ("MINIMIZE_TRAVEL_TIME", "RELAXED", "MORE_SIGHTS")
MAX_ACTIONS = 5
FORECAST_DAYS = 16               # weather_service.FORECAST_HORIZON_DAYS
AI_BUCKET = "ai_trip"            # the same bucket as /ws/app trips:weather_replan | optimize_day | optimize_budget
AI_LIMIT_PER_MINUTE = 10

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

TEXT: Dict[str, Dict[str, str]] = {
    "no_trip": {"hi": "Pehle koi trip kholiye.", "en": "Open a trip first."},
    "no_itinerary": {"hi": "Itinerary abhi ban rahi hai.", "en": "Your itinerary isn't ready yet."},
    "not_found": {"hi": "Yeh trip nahi mili.", "en": "I couldn't find that trip."},
    "need_day": {"hi": "Kaunsa din? Din ka number, ya aaj ya kal boliye.",
                 "en": "Which day? Say the day number, or today or tomorrow."},
    "outside_trip": {"hi": "Trip {start} se {end} tak hai, kaunsa din?",
                     "en": "The trip runs from {start} to {end}. Which day?"},
    "past_day": {"hi": "Yeh din nikal chuka hai.", "en": "That day has already passed."},
    "too_far": {"hi": "Itne aage ka mausam abhi pata nahi hai.", "en": "There's no forecast that far ahead yet."},
    "forecast_unavailable": {"hi": "Abhi mausam ki jaankari nahi mil rahi.", "en": "I couldn't get the weather right now."},
    "no_bad_weather_day": {"hi": "{when} mausam theek hai, plan badalne ki zaroorat nahi.",
                           "en": "{when}, the weather looks fine, so there's no need to change the plan."},
    "no_bad_weather_trip": {"hi": "Trip ke dauran mausam theek hai, plan badalne ki zaroorat nahi.",
                            "en": "The weather looks fine for your trip, so there's no need to change the plan."},
    "no_indoor_needed": {"hi": "Mausam kharab hai, par koi jagah badalni nahi padegi.",
                         "en": "The weather is bad, but none of your plans need changing."},
    "rate_limited": {"hi": "Thodi der baad try karein.", "en": "Please try again in a little while."},
    "failed": {"hi": "Abhi plan badal nahi paaya, thodi der mein try karein.",
               "en": "I couldn't change the plan right now, please try again in a bit."},
    "need_budget": {"hi": "Pehle budget batayein, kitna hai?", "en": "First tell me your budget. How much is it?"},
    "budget_low": {"hi": "Budget kam se kam {min} rupaye hona chahiye, kitna hai?",
                   "en": "The budget must be at least {min} rupees. How much is it?"},
    "budget_high": {"hi": "Budget zyada se zyada {max} rupaye ho sakta hai, kitna hai?",
                    "en": "The budget can be at most {max} rupees. How much is it?"},
    "within_budget": {"hi": "Plan pehle se budget ke andar hai.", "en": "Your plan is already within budget."},
    "no_savings": {"hi": "Budget ke liye koi sasta vikalp nahi mila.", "en": "I couldn't find cheaper options."},
    "no_activities": {"hi": "Is din mein koi activity nahi hai.", "en": "There are no activities on that day."},
    "stale": {"hi": "Plan pehle hi badal gaya tha, kuch nahi badla.", "en": "The plan had already changed, so nothing was changed."},
    "weather_q": {"hi": "{when} {cond} ka forecast hai. {what}?", "en": "{when} the forecast is {cond}. Shall I {what}?"},
    "budget_q": {"hi": "{saving} bachane ke liye {what}?", "en": "To save {saving}, shall I {what}?"},
    "day_q_MINIMIZE_TRAVEL_TIME": {"hi": "Day {n} ka order travel kam karne ke liye badal doon?",
                                   "en": "Shall I reorder day {n} to cut travel time?"},
    "day_q_RELAXED": {"hi": "Day {n} ko relaxed banane ke liye badal doon?", "en": "Shall I make day {n} more relaxed?"},
    "day_q_MORE_SIGHTS": {"hi": "Day {n} mein zyada jagahein dekhne ke liye badal doon?",
                          "en": "Shall I reorder day {n} to fit in more sights?"},
    "applied": {"hi": "Ho gaya. {what}", "en": "Done. {what}"},
    "day_applied": {"hi": "Day {n} ab aisa hai: {titles}.", "en": "Day {n} is now: {titles}."},
    "cancelled": {"hi": "Theek hai, kuch nahi badla.", "en": "Okay, nothing was changed."},
    # set_trip_budget: set or change the open trip's budget amount (asks first)
    "budget_ask_amount": {"hi": "Kitna budget rakhun?", "en": "What should the budget be?"},
    "budget_same": {"hi": "Budget pehle se {amount} hai.", "en": "The budget is already {amount}."},
    "budget_change_q": {"hi": "Trip ka budget {old} se {new} kar doon?", "en": "Change the trip budget from {old} to {new}?"},
    "budget_set_q": {"hi": "Trip ka budget {new} rakh doon?", "en": "Set the trip budget to {new}?"},
    "budget_set_done": {"hi": "Ho gaya, budget ab {new} hai.", "en": "Done. The budget is now {new}."},
}


def _t(key: str, lang: str, **kw: Any) -> str:
    return TEXT[key][lang if lang in ("hi", "en") else "hi"].format(**kw)


# ---------------- days of a trip

@dataclass
class DayRef:
    day_id: str
    day_number: int
    date: str          # YYYY-MM-DD


def _fmt_date(iso: str) -> str:
    try:
        d = date.fromisoformat(iso[:10])
        return f"{d.day} {MONTHS[d.month - 1]}"
    except (TypeError, ValueError):
        return str(iso)[:10]


@contextmanager
def _session(db=None):
    if db is not None:
        yield db
        return
    import database
    with database.SessionLocal() as s:
        yield s


def load_days(db, trip_id: str) -> List[DayRef]:
    """The trip's itinerary days in order ([] when there is no itinerary yet)."""
    from models_itinerary import ItineraryDayModel, ItineraryModel
    itin = (db.query(ItineraryModel).filter(ItineraryModel.trip_id == trip_id)
            .order_by(ItineraryModel.version.desc()).first())
    if not itin:
        return []
    rows = (db.query(ItineraryDayModel).filter(ItineraryDayModel.itinerary_id == itin.id)
            .order_by(ItineraryDayModel.day_number).all())
    return [DayRef(r.id, int(r.day_number), str(r.date)[:10]) for r in rows]


def resolve_in_days(days: List[DayRef], day: Any, today: date) -> Union[DayRef, str]:
    """
    Pure: one of the trip's days, or an error code. `day` is language-neutral: today | tomorrow |
    day_after_tomorrow | YYYY-MM-DD | a day number (2, "2"). None -> "need_day".
    Codes: no_itinerary | need_day | outside_trip
    """
    if not days:
        return "no_itinerary"
    if day is None or (isinstance(day, str) and not day.strip()) or isinstance(day, bool):
        return "need_day"
    if isinstance(day, float) and day == int(day):
        day = int(day)
    raw = str(day).strip()
    if isinstance(day, int) or re.fullmatch(r"\d{1,2}", raw):
        n = int(raw)
        return next((d for d in days if d.day_number == n), "outside_trip")
    from voice.tools.lookups import resolve_day
    the_date = resolve_day(raw, today)
    if the_date is None:
        return "need_day"
    return next((d for d in days if d.date == the_date.isoformat()), "outside_trip")


def resolve_trip_day(db, trip_id: str, day: Any, today: date) -> Union[DayRef, str]:
    return resolve_in_days(load_days(db, trip_id), day, today)


def _day_error(code: str, days: List[DayRef], lang: str) -> str:
    if code == "outside_trip" and days:
        return _t("outside_trip", lang, start=_fmt_date(days[0].date), end=_fmt_date(days[-1].date))
    return _t(code if code in TEXT else "need_day", lang)


# ---------------- AI rate limit (shared with /ws/app)

def check_ai_rate_limit(user_id: str, redis_conn=None) -> bool:
    """One hit on the same sliding window as /ws/app's `ai_trip` bucket (rl:ws:ai_trip:{user}, 10 per minute)."""
    try:
        from rate_limiter import SLIDING_WINDOW_LUA
        if redis_conn is None:
            from redis_client import redis_conn as _r
            redis_conn = _r
        now = time.time()
        script = redis_conn.register_script(SLIDING_WINDOW_LUA)
        res = script(keys=[f"rl:ws:{AI_BUCKET}:{user_id}"], args=[now, 60, AI_LIMIT_PER_MINUTE, f"{now}:{uuid.uuid4().hex[:8]}"])
        return int(res[0]) == 1
    except Exception as err:
        logger.warning("[VOICE SMART] rate limit check failed (rejecting): %s", type(err).__name__)
        return False   # fail closed, like /ws/app for paid AI calls


# ---------------- AI suggestions -> safe actions

def _num(v: Any) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def normalize_action(rec: Any) -> Optional[Dict[str, Any]]:
    """One AI suggestion -> a REPLACE_ACTIVITY action with only the fields execute_refinement_actions_service uses."""
    if not isinstance(rec, dict):
        return None
    kind = str(rec.get("type") or rec.get("action") or "").upper()
    if kind != "REPLACE_ACTIVITY" or not rec.get("activityId"):   # voice never removes an activity
        return None
    rep = rec.get("replacement")
    if not isinstance(rep, dict) or not str(rep.get("name") or "").strip():
        return None
    out: Dict[str, Any] = {"name": str(rep["name"]).strip()[:200]}
    for key, cap in (("description", 500), ("timeSlot", 30), ("locationName", 200)):
        if isinstance(rep.get(key), str) and rep[key].strip():
            out[key] = rep[key].strip()[:cap]
    lat, lng = _num(rep.get("latitude")), _num(rep.get("longitude"))
    if lat is not None and lng is not None and -90 <= lat <= 90 and -180 <= lng <= 180:
        out["latitude"], out["longitude"] = lat, lng
    cost = _num(rep.get("estimatedCost"))
    if cost is not None and 0 <= cost <= 10_000_000:
        out["estimatedCost"] = int(cost)
    return {"type": "REPLACE_ACTIVITY", "activityId": str(rec["activityId"]),
            "activityTitle": str(rec.get("activityTitle") or "").strip()[:120], "replacement": out}


def summarize_replacements(actions: List[Dict[str, Any]], lang: str, past: bool = False) -> str:
    """'Amber Fort ki jagah City Palace rakh doon' / 'replace Amber Fort with City Palace' (past: 'rakh diya' / 'Replaced')."""
    parts = []
    for a in actions[:2]:
        old = a.get("activityTitle") or ("ek jagah" if lang != "en" else "one stop")
        new = (a.get("replacement") or {}).get("name") or ""
        parts.append((old, new))
    if not parts:
        return ""
    more = len(actions) - len(parts)
    if lang == "en":
        body = " and ".join(f"{o} with {n}" for o, n in parts) + (f", and {more} more" if more > 0 else "")
        return f"Replaced {body}" if past else f"replace {body}"
    body = " aur ".join(f"{o} ki jagah {n}" for o, n in parts) + (f", aur {more} aur" if more > 0 else "")
    return f"{body} rakh diya" if past else f"{body} rakh doon"


def _time_key(slot: Any, idx: int):
    for fmt in ("%I:%M %p", "%H:%M", "%I %p"):
        try:
            t = datetime.strptime(str(slot).strip().upper(), fmt)
            return (0, t.hour * 60 + t.minute, idx)
        except ValueError:
            continue
    return (1, 0, idx)


def summarize_day_order(activities: List[Dict[str, Any]], day_number: int, lang: str) -> str:
    """One sentence from the service's result: the first three stops in time order."""
    ordered = sorted(enumerate(activities), key=lambda p: _time_key(p[1].get("timeSlot"), p[0]))
    titles = [str(a.get("title") or "").strip() for _, a in ordered if str(a.get("title") or "").strip()][:3]
    return _t("day_applied", lang, n=day_number, titles=", ".join(titles) if lang != "en" else ", then ".join(titles))


# ---------------- the ask turn

def _result(text: str, *, action: str = "smart_ask", step: Optional[str] = None, code: Optional[str] = None,
            detail: Optional[str] = None, pending=None, ui_actions=None):
    from voice.agent import AgentResult
    return AgentResult(text, ui_actions=list(ui_actions or []), action=action, step=step, error_code=code,
                       error_detail=detail,
                       pending_confirmation={"id": pending["id"], "summary": pending["summary"]} if pending else None)


def _owned_trip(db, trip, user_id: str):
    from ownership import find_owned_trip
    return find_owned_trip(db, getattr(trip, "id", None), user_id)


def _today() -> date:
    from trip_lifecycle import today_ist
    return today_ist()


def propose(name: str, args: Dict[str, Any], user_id: str, trip, lang: str, redis_conn, conversation_id: str, db=None):
    """Dispatch for the agent. Never raises: any failure is a spoken line plus an error code for the logs."""
    try:
        if name == "weather_replan":
            return propose_weather_replan(user_id, trip, args.get("day"), lang, redis_conn, conversation_id, db)
        if name == "optimize_day":
            return propose_optimize_day(user_id, trip, args.get("day"), args.get("goal"), lang, redis_conn,
                                        conversation_id, db)
        if name == "set_trip_budget":
            return propose_set_budget(user_id, trip, args.get("amount"), lang, redis_conn, conversation_id, db)
        return propose_optimize_budget(user_id, trip, args.get("budget_inr"), lang, redis_conn, conversation_id, db)
    except Exception as err:
        logger.exception("[VOICE SMART] %s failed while asking", name)
        return _result(_t("failed", lang), action="smart_failed", step="failed", code=type(err).__name__,
                       detail=f"{type(err).__name__}: {str(err)[:200]}")


def _bad_weather_text(when_day: Optional[date], today: date, lang: str) -> str:
    if when_day is None:
        return _t("no_bad_weather_trip", lang)
    from voice.tools.lookups import _day_words
    return _t("no_bad_weather_day", lang, when=_day_words(when_day, today, lang))


def propose_weather_replan(user_id: str, trip, day: Any, lang: str, redis_conn, conversation_id: str, db=None,
                           today: Optional[date] = None):
    import itinerary_service as svc
    import weather_service
    from models_itinerary import ItineraryActivityModel
    from voice.tools.lookups import _day_words

    today = today or _today()
    with _session(db) as s:
        row = _owned_trip(s, trip, user_id)
        if row is None:
            return _result(_t("not_found", lang), action="smart_failed", step="failed", code="not_found")
        days = load_days(s, row.id)
        if not days:
            return _result(_t("no_itinerary", lang), step="failed", code="no_itinerary")

        if day is not None and str(day).strip():
            ref = resolve_in_days(days, day, today)
            if isinstance(ref, str):
                return _result(_day_error(ref, days, lang), step="failed", code=ref)
            targets = [ref]
            if date.fromisoformat(ref.date) < today:
                return _result(_t("past_day", lang), step="failed", code="past_day")
        else:
            targets = [d for d in days if date.fromisoformat(d.date) >= today]
            if not targets:
                return _result(_t("past_day", lang), step="failed", code="past_day")
        horizon = today + timedelta(days=FORECAST_DAYS - 1)
        in_range = [t for t in targets if date.fromisoformat(t.date) <= horizon]
        if not in_range:
            return _result(_t("too_far", lang), action="weather", step="failed", code="too_far")

        dest = row.destination if isinstance(row.destination, dict) else {}
        if dest.get("latitude") is None or dest.get("longitude") is None:
            return _result(_t("forecast_unavailable", lang), action="weather", step="failed", code="no_location")
        try:
            forecast = weather_service.get_trip_forecast(float(dest["latitude"]), float(dest["longitude"]),
                                                         in_range[0].date, in_range[-1].date)
        except Exception as err:   # ForecastUnavailable or anything else: say so, change nothing
            logger.warning("[VOICE SMART] forecast failed: %s", type(err).__name__, exc_info=True)
            return _result(_t("forecast_unavailable", lang), action="weather", step="failed",
                           code="forecast_unavailable", detail=type(err).__name__)

        wanted = {t.date for t in in_range}
        bad = [d for d in forecast.get("days", []) if d.get("badWeather") and d.get("date") in wanted]
        if not bad:
            when_day = date.fromisoformat(in_range[0].date) if len(targets) == 1 else None
            return _result(_bad_weather_text(when_day, today, lang), action="weather", step="no_change", code=None)

        if not check_ai_rate_limit(user_id, redis_conn):
            return _result(_t("rate_limited", lang), step="failed", code="rate_limited")

        bad_dates = [d["date"] for d in bad]
        filtered = {"source": forecast.get("source"), "days": bad, "badWeatherDates": bad_dates,
                    "condition": bad[0].get("condition"),
                    "summary": "Bad weather expected on " + ", ".join(f"{d['date']} ({d.get('condition')})" for d in bad)}
        trip_id = row.id
        try:
            res = svc.weather_replan_service(s, trip_id, forecast_override=filtered)
        except Exception as err:
            s.rollback()
            logger.warning("[VOICE SMART] weather_replan_service failed: %s", type(err).__name__, exc_info=True)
            return _result(_t("failed", lang), action="smart_failed", step="failed", code="service_failed",
                           detail=f"{type(err).__name__}: {str(err)[:200]}")

        bad_day_ids = [d.day_id for d in days if d.date in bad_dates]
        ids_on_bad_days = {r[0] for r in s.query(ItineraryActivityModel.id)
                           .filter(ItineraryActivityModel.day_id.in_(bad_day_ids)).all()}
        actions = []
        for rec in (res or {}).get("recommendations") or []:
            act = normalize_action(rec)
            if act and act["activityId"] in ids_on_bad_days:
                actions.append(act)
            if len(actions) >= MAX_ACTIONS:
                break
        if not actions:
            return _result(_t("no_indoor_needed", lang), action="weather", step="no_change", code="no_suggestions")

        first_day = next(d for d in days if d.date == bad_dates[0])
        when = _day_words(date.fromisoformat(first_day.date), today, lang)
        cond = str(bad[0].get("condition") or "bad weather")
        what = summarize_replacements(actions, lang)
        summary = _t("weather_q", lang, when=when, cond=cond.lower(), what=what)
        pc = P.save(redis_conn, user_id, conversation_id, "weather_replan", summary,
                    {"trip_id": trip_id, "actions": actions, "day_number": first_day.day_number})
        return _result(summary, step="ask", pending=pc)


def propose_optimize_day(user_id: str, trip, day: Any, goal: Any, lang: str, redis_conn, conversation_id: str,
                         db=None, today: Optional[date] = None):
    from models_itinerary import ItineraryActivityModel
    today = today or _today()
    goal = goal if goal in GOALS else "MINIMIZE_TRAVEL_TIME"
    with _session(db) as s:
        row = _owned_trip(s, trip, user_id)
        if row is None:
            return _result(_t("not_found", lang), action="smart_failed", step="failed", code="not_found")
        days = load_days(s, row.id)
        # No day said ("route chhota karo"): today if it's a trip day, else ask.
        ref = resolve_in_days(days, day if (day is not None and str(day).strip()) else "today", today)
        if isinstance(ref, str):
            return _result(_day_error(ref, days, lang), step="failed", code=ref)
        count = s.query(ItineraryActivityModel).filter(ItineraryActivityModel.day_id == ref.day_id).count()
        if count == 0:
            return _result(_t("no_activities", lang), step="failed", code="no_activities")
        summary = _t(f"day_q_{goal}", lang, n=ref.day_number)
        pc = P.save(redis_conn, user_id, conversation_id, "optimize_day", summary,
                    {"trip_id": row.id, "day_id": ref.day_id, "day_number": ref.day_number, "goal": goal})
        return _result(summary, step="ask", pending=pc)


def _parse_budget(raw: Any) -> Optional[float]:
    """Any finite number counts as 'said'; the range check is the caller's, so a huge amount is refused, not ignored."""
    v = _num(raw)
    return v if v is not None and math.isfinite(v) else None


def propose_optimize_budget(user_id: str, trip, budget_inr: Any, lang: str, redis_conn, conversation_id: str, db=None):
    import itinerary_service as svc
    with _session(db) as s:
        row = _owned_trip(s, trip, user_id)
        if row is None:
            return _result(_t("not_found", lang), action="smart_failed", step="failed", code="not_found")
        days = load_days(s, row.id)
        if not days:
            return _result(_t("no_itinerary", lang), step="failed", code="no_itinerary")

        said = _parse_budget(budget_inr)
        if said is not None and not (MIN_BUDGET_INR <= said <= MAX_BUDGET_INR):
            key = "budget_low" if said < MIN_BUDGET_INR else "budget_high"
            return _result(_t(key, lang, min=f"{MIN_BUDGET_INR:,}", max=f"{MAX_BUDGET_INR:,}"),
                           step="failed", code="budget_out_of_range")
        existing = _num((row.budget or {}).get("targetAmount")) or 0
        if said is None and existing <= 0:
            return _result(_t("need_budget", lang), step="failed", code="need_budget")

        if not check_ai_rate_limit(user_id, redis_conn):
            return _result(_t("rate_limited", lang), step="failed", code="rate_limited")

        trip_id = row.id
        original_budget = dict(row.budget or {})
        try:
            if said is not None:
                # The amount is only saved if the user confirms: it is applied for this check, then rolled back.
                row.budget = {**original_budget, "targetAmount": int(said) if said == int(said) else said}
                s.flush()
            try:
                res = svc.optimize_budget_service(s, trip_id)
            finally:
                if said is not None:
                    s.rollback()
        except Exception as err:
            s.rollback()
            if isinstance(err, ValueError) and "no budget" in str(err).lower():
                return _result(_t("need_budget", lang), step="failed", code="need_budget")
            logger.warning("[VOICE SMART] optimize_budget_service failed: %s", type(err).__name__, exc_info=True)
            return _result(_t("failed", lang), action="smart_failed", step="failed", code="service_failed",
                           detail=f"{type(err).__name__}: {str(err)[:200]}")

        res = res or {}
        saving = _num(res.get("savingsRequired"))
        if saving is None or saving <= 0:
            return _result(_t("within_budget", lang), step="no_change", code=None)
        from models_itinerary import ItineraryActivityModel
        own_ids = {r[0] for r in s.query(ItineraryActivityModel.id)
                   .filter(ItineraryActivityModel.day_id.in_([d.day_id for d in days])).all()}
        actions = []
        for rec in res.get("recommendations") or []:
            act = normalize_action(rec)
            if act and act["activityId"] in own_ids:
                actions.append(act)
            if len(actions) >= MAX_ACTIONS:
                break
        if not actions:
            return _result(_t("no_savings", lang), step="no_change", code="no_suggestions")

        saving_txt = f"₹{int(saving):,}"
        summary = _t("budget_q", lang, saving=saving_txt, what=summarize_replacements(actions, lang))
        data: Dict[str, Any] = {"trip_id": trip_id, "actions": actions}
        if said is not None:
            data["set_budget"] = said
        pc = P.save(redis_conn, user_id, conversation_id, "optimize_budget", summary, data)
        return _result(summary, step="ask", pending=pc)


def _inr(amount: float) -> str:
    return f"₹{int(amount):,}" if amount == int(amount) else f"₹{amount:,.2f}"


def propose_set_budget(user_id: str, trip, amount: Any, lang: str, redis_conn, conversation_id: str, db=None):
    """
    "budget 25000 kar do", "budget badal ke 40 hazaar rakho", "set budget to 30000": asks first, then the confirm
    turn saves it with itinerary_service.set_trip_budget_amount. Same range as trip creation (budget_out_of_range).
    No AI call, no itinerary needed.
    """
    with _session(db) as s:
        row = _owned_trip(s, trip, user_id)
        if row is None:
            return _result(_t("not_found", lang), action="smart_failed", step="failed", code="not_found")
        said = _parse_budget(amount)
        if said is None:
            return _result(_t("budget_ask_amount", lang), step="failed", code="need_budget")
        if not (MIN_BUDGET_INR <= said <= MAX_BUDGET_INR):
            key = "budget_low" if said < MIN_BUDGET_INR else "budget_high"
            return _result(_t(key, lang, min=f"{MIN_BUDGET_INR:,}", max=f"{MAX_BUDGET_INR:,}"),
                           step="failed", code="budget_out_of_range")
        existing = _num((row.budget or {}).get("targetAmount")) or 0
        if existing > 0 and abs(existing - said) < 0.5:
            return _result(_t("budget_same", lang, amount=_inr(existing)), step="no_change", code=None)
        summary = (_t("budget_change_q", lang, old=_inr(existing), new=_inr(said)) if existing > 0
                   else _t("budget_set_q", lang, new=_inr(said)))
        pc = P.save(redis_conn, user_id, conversation_id, "set_trip_budget", summary,
                    {"trip_id": row.id, "amount": int(said) if said == int(said) else said})
        return _result(summary, step="ask", pending=pc)


# ---------------- the confirm turn

def apply_confirmed(pending: Dict[str, Any], user_id: str, lang: str, redis_conn=None, db=None):
    """
    Runs a confirmed smart action. The pending item was already taken (once). Ownership is checked again; the
    work runs in the services' own transactions, so a failure leaves the trip as it was.
    Returns action "smart_applied" or "smart_failed".
    """
    import itinerary_service as svc
    tool, data = pending.get("tool"), pending.get("data") or {}
    try:
        with _session(db) as s:
            from ownership import find_owned_trip
            row = find_owned_trip(s, data.get("trip_id"), user_id)
            if row is None:
                return _result(_t("not_found", lang), action="smart_failed", step="failed", code="not_found")
            trip_id = row.id

            if tool == "set_trip_budget":
                amount = float(data.get("amount"))
                svc.set_trip_budget_amount(s, trip_id, amount)   # checks the range again
                text = _t("budget_set_done", lang, new=_inr(amount))
                route, _ = pages.resolve("itinerary", None, True)
            elif tool == "optimize_day":
                if not check_ai_rate_limit(user_id, redis_conn):
                    return _result(_t("rate_limited", lang), action="smart_failed", step="failed", code="rate_limited")
                res = svc.optimize_day_flow_service(s, trip_id, str(data.get("day_id") or ""), data.get("goal") or GOALS[0])
                acts = (res or {}).get("activities") or []
                if not acts:
                    return _result(_t("no_activities", lang), action="smart_failed", step="failed", code="no_activities")
                n = int(data.get("day_number") or 0)
                text = summarize_day_order(acts, n, lang)
                route, _ = pages.resolve("itinerary", n if 1 <= n <= pages.MAX_DAY else None, True)
            elif tool in ("weather_replan", "optimize_budget"):
                actions = [a for a in (data.get("actions") or []) if normalize_action(a)][:MAX_ACTIONS]
                res = svc.execute_refinement_actions_service(s, trip_id, actions)
                done = int((res or {}).get("executedCount") or 0)
                if done == 0:
                    return _result(_t("stale", lang), action="smart_failed", step="failed", code="stale")
                if data.get("set_budget") is not None:
                    svc.set_trip_budget_amount(s, trip_id, float(data["set_budget"]))
                text = _t("applied", lang, what=summarize_replacements(actions, lang, past=True) + ".")
                n = int(data.get("day_number") or 0)
                route, _ = pages.resolve("itinerary", n if 1 <= n <= pages.MAX_DAY else None, True)
            else:
                return _result(_t("failed", lang), action="smart_failed", step="failed", code="unknown_pending_tool")
    except PlaceOutsideTripArea as err:
        return _result(err.message, action="smart_failed", step="failed", code=err.code)
    except Exception as err:
        logger.warning("[VOICE SMART] apply failed: %s", type(err).__name__, exc_info=True)
        return _result(_t("failed", lang), action="smart_failed", step="failed", code="service_failed",
                       detail=f"{type(err).__name__}: {str(err)[:200]}")
    ui = [{"type": "refresh", "what": "itinerary"}]
    if route:
        ui.append({"type": "navigate", "to": route})
    return _result(text, action="smart_applied", step="applied", ui_actions=ui)
