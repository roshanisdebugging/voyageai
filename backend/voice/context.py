"""
Trip context for the voice agent (voicefirst.md "Step 5 in detail").

When a trip is open, the prompt gets a compact view: the days with dates, the activities with short IDs
(a1, a2, ...) and names (today's day first), and the total spent vs the budget. The trip is re-checked
against the session's user before anything is read.

The model may name an activity ("Hawa Mahal wala") or give a short ID; CODE matches it against this
trip's own activities (match_activity). An ID from the model is never used as is.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional, Tuple

MAX_ACTIVITIES_IN_PROMPT = 80
MAX_TITLE = 48


@dataclass
class Act:
    short: str          # a1, a2, ... (stable for one trip state: day order, then the itinerary's order)
    id: str             # the real activity ID (from the DB, never from the model)
    title: str
    day_number: int
    date: str
    done: bool
    location: str = ""


@dataclass
class TripContext:
    trip_id: str
    title: str
    destination: str
    activities: List[Act] = field(default_factory=list)
    days: List[Tuple[int, str]] = field(default_factory=list)   # (day_number, date)
    spent: float = 0.0
    budget: Optional[float] = None
    today_day: Optional[int] = None
    itinerary_status: Optional[str] = None


def load(user_id: str, trip_id: Optional[str], today: Optional[date] = None, db=None) -> Optional[TripContext]:
    """The open trip's context, only if it is the user's own. None otherwise (or on any error)."""
    if not user_id or not trip_id:
        return None
    if db is None:
        import database
        try:
            with database.SessionLocal() as s:
                return load(user_id, trip_id, today, s)
        except Exception:
            return None
    from models_itinerary import ItineraryActivityModel, ItineraryDayModel, ItineraryModel
    from models_package import TripExpenseModel
    from ownership import find_owned_trip
    trip = find_owned_trip(db, str(trip_id)[:80], user_id)
    if not trip:
        return None
    if today is None:
        from trip_lifecycle import today_ist
        today = today_ist()
    dest = ""
    try:
        dest = (trip.destination or {}).get("name") or ""
    except Exception:
        dest = ""
    ctx = TripContext(trip_id=trip.id, title=(trip.title or "")[:80], destination=str(dest)[:80],
                      itinerary_status=getattr(trip, "itinerary_status", None))
    itin = db.query(ItineraryModel).filter(ItineraryModel.trip_id == trip.id).first()
    n = 0
    if itin:
        days = (db.query(ItineraryDayModel).filter(ItineraryDayModel.itinerary_id == itin.id)
                .order_by(ItineraryDayModel.day_number).all())
        for d in days:
            ctx.days.append((d.day_number, d.date or ""))
            if (d.date or "")[:10] == today.isoformat():
                ctx.today_day = d.day_number
            for a in db.query(ItineraryActivityModel).filter(ItineraryActivityModel.day_id == d.id).all():
                n += 1
                ctx.activities.append(Act(short=f"a{n}", id=a.id, title=(a.title or "")[:MAX_TITLE],
                                          day_number=d.day_number, date=(d.date or "")[:10], done=bool(a.is_done),
                                          location=(a.location_name or "")[:60]))
    ctx.spent = float(sum((e.amount or 0) for e in db.query(TripExpenseModel).filter(TripExpenseModel.trip_id == trip.id).all()))
    try:
        target = (trip.budget or {}).get("targetAmount")
        ctx.budget = float(target) if target else None
    except Exception:
        ctx.budget = None
    return ctx


def same_trip_id(a: str, b: str) -> bool:
    """Trip IDs arrive with or without the 'trip_' prefix."""
    from ownership import trip_id_candidates
    return bool(a and b) and bool(set(trip_id_candidates(a)) & set(trip_id_candidates(b)))


def _rupees(v: float) -> str:
    return f"Rs {int(round(v)):,}"


def prompt_text(ctx: Optional[TripContext]) -> str:
    """Compact view for the system prompt (in the prompt only; never logged)."""
    if ctx is None:
        return "none"
    lines = []
    order = sorted({d for d, _ in ctx.days}, key=lambda d: (d != ctx.today_day, d))
    dates = dict(ctx.days)
    shown = 0
    for day in order:
        acts = [a for a in ctx.activities if a.day_number == day]
        if shown >= MAX_ACTIVITIES_IN_PROMPT:
            break
        acts = acts[: MAX_ACTIVITIES_IN_PROMPT - shown]
        shown += len(acts)
        items = "; ".join(f"{a.short} {a.title}{' [done]' if a.done else ''}" for a in acts) or "no activities"
        lines.append(f"Day {day} ({dates.get(day, '')[:10]}{', today' if day == ctx.today_day else ''}): {items}")
    if not lines:
        lines.append("itinerary not ready" if ctx.itinerary_status == "GENERATING" else "no itinerary yet")
    money = f"Spent {_rupees(ctx.spent)}" + (f" of {_rupees(ctx.budget)} budget" if ctx.budget else " (no budget set)")
    return "\n  " + "\n  ".join(lines + [money])


# ---------------- matching a spoken name to one of THIS trip's activities

_FILLER = {"wala", "wali", "wale", "ka", "ki", "ke", "ko", "the", "a", "an", "visit", "mark", "done", "karo", "kar",
           "do", "ho", "gaya", "gayi", "activity", "jagah", "place", "to", "at", "par", "pe", "mein", "se", "aur"}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9ऀ-ॿ ]", " ", (s or "").lower())).strip()


def _tokens(s: str) -> List[str]:
    return [t for t in _norm(s).split() if t not in _FILLER and len(t) >= 2]


def match_activity(ctx: Optional[TripContext], query: Optional[str]) -> Tuple[Optional[Act], List[Act]]:
    """
    (the one match, []) or (None, candidates). Candidates > 1 = ambiguous; [] = unknown. Never guesses:
    a single clear match or nothing.
    """
    if ctx is None or not ctx.activities:
        return None, []
    q = (query or "").strip()[:120]
    if not q:
        return None, []
    short = re.fullmatch(r"\s*a(\d{1,3})\s*", q.lower())
    if short:
        hit = [a for a in ctx.activities if a.short == f"a{short.group(1)}"]
        return (hit[0], []) if hit else (None, [])
    exact_id = [a for a in ctx.activities if a.id == q]
    if exact_id:
        return exact_id[0], []
    nq = " ".join(_tokens(q))
    if not nq:
        return None, []
    tiers = [
        [a for a in ctx.activities if " ".join(_tokens(a.title)) == nq],
        [a for a in ctx.activities if nq in " ".join(_tokens(a.title)) or
         (len(" ".join(_tokens(a.title))) >= 4 and " ".join(_tokens(a.title)) in nq)],
    ]
    for hits in tiers:
        if len(hits) == 1:
            return hits[0], []
        if len(hits) > 1:
            return None, hits[:4]
    # token overlap, then a close spelling (typos from speech-to-text)
    qt = set(nq.split())
    scored = []
    for a in ctx.activities:
        at = set(_tokens(a.title))
        if not at:
            continue
        overlap = len(qt & at) / max(1, len(qt))
        ratio = difflib.SequenceMatcher(None, nq, " ".join(_tokens(a.title))).ratio()
        score = max(overlap, ratio if ratio >= 0.8 else 0)
        if score >= 0.6:
            scored.append((score, a))
    if not scored:
        return None, []
    best = max(s for s, _ in scored)
    top = [a for s, a in scored if s == best]
    return (top[0], []) if len(top) == 1 else (None, top[:4])
