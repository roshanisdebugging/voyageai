"""
Step 3 look-ups (voicefirst.md "Step 3 in detail"). Read-only: nothing here changes data.

- search_place(query)            India-only map search, top result -> ui_action map_focus
- list_my_trips(user_id, ...)    the user's own trips, upcoming first
- open_trip(user_id, ...)        match the user's own trips in code; one -> open it, several -> ask

Every function takes the user_id from the server-side session, never from the model, and every trip
comes from a query filtered by that user_id. Trip IDs the model might send are never used.
Replies are templates ("hi" = Roman Hinglish, "en" = English). No logging of user words here.
"""
from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional

MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
             "October", "November", "December"]
MONTH_ALIASES = {m.lower(): i + 1 for i, m in enumerate(MONTHS_EN)}
MONTH_ALIASES.update({m[:3].lower(): i + 1 for i, m in enumerate(MONTHS_EN)})
MONTH_ALIASES.update({"sept": 9, "janvari": 1, "farvari": 2, "march": 3, "aprail": 4, "mai": 5, "joon": 6, "julai": 7,
                      "agast": 8, "sitambar": 9, "aktubar": 10, "navambar": 11, "disambar": 12})
OPEN_STATUSES = {"PLANNING", "UPCOMING", "ACTIVE"}
MAX_SPOKEN_TRIPS = 3


@dataclass
class ToolResult:
    reply_text: str
    ui_actions: List[Dict[str, Any]] = field(default_factory=list)
    action: str = "reply"
    error_code: Optional[str] = None


# ---------------- search a place on the map

def in_india(lat: Any, lng: Any) -> bool:
    """Same box as the frontend's isInIndia()."""
    try:
        return 6.0 <= float(lat) <= 37.5 and 68.0 <= float(lng) <= 97.5
    except (TypeError, ValueError):
        return False


def search_place(query: str, lang: str, search_fn=None) -> ToolResult:
    q = (query or "").strip()[:120]
    if len(q) < 2:
        return ToolResult({"hi": "Kaunsi jagah dikhaun?", "en": "Which place should I show?"}[lang], action="reply",
                          error_code="no_query")
    if search_fn is None:
        from places import search_places as search_fn  # existing India-only search (Google)
    try:
        results = search_fn(q) or []
    except Exception:
        results = []
    hits = [r for r in results if r.get("latitude") is not None and in_india(r.get("latitude"), r.get("longitude"))]
    if not hits:
        return ToolResult({"hi": "Yeh jagah nahi mili.", "en": "I couldn't find that place."}[lang],
                          action="map_focus_none", error_code="not_found")
    top = hits[0]
    name = (top.get("name") or q)[:120]
    focus = {"type": "map_focus", "lat": float(top["latitude"]), "lng": float(top["longitude"]), "name": name}
    if top.get("place_id") or top.get("id"):
        focus["place_id"] = str(top.get("place_id") or top.get("id"))[:300]
    reply = {"hi": f"{name} map par dikha diya.", "en": f"Showing {name} on the map."}[lang]
    return ToolResult(reply, ui_actions=[focus, {"type": "navigate", "to": "/map"}], action="map_focus")


# ---------------- the user's trips

@dataclass
class TripRow:
    id: str
    title: str
    destination: str
    start: Optional[date]
    end: Optional[date]
    status: str


def _destination_name(trip) -> str:
    try:
        d = json.loads(trip.destination_json or "{}")
    except (TypeError, ValueError):
        d = {}
    return (d.get("name") or d.get("city") or trip.title or "").strip()


def _to_date(raw: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(raw)[:10])
    except (TypeError, ValueError):
        return None


def load_user_trips(user_id: str, db=None) -> List[TripRow]:
    """The user's own trips (closed automatically if they ended, as on every trip read)."""
    from models_trip import TripModel
    from trip_lifecycle import close_finished_trips

    def _load(session):
        trips = session.query(TripModel).filter(TripModel.user_id == user_id).all()
        close_finished_trips(session, trips)
        return [TripRow(id=t.id, title=(t.title or "").strip(), destination=_destination_name(t),
                        start=_to_date(t.start_date), end=_to_date(t.end_date), status=(t.status or "PLANNING").upper())
                for t in trips]

    if db is not None:
        return _load(db)
    from database import get_db_context
    with get_db_context() as session:
        return _load(session)


def _today() -> date:
    from trip_lifecycle import today_ist
    return today_ist()


def _sort_open(trips: List[TripRow]) -> List[TripRow]:
    """Ongoing first, then upcoming by start date."""
    today = _today()
    return sorted(trips, key=lambda t: (0 if t.start and t.start <= today else 1, t.start or date.max))


def _when(t: TripRow, lang: str) -> str:
    if not t.start:
        return ""
    day = f"{t.start.day} {MONTHS_EN[t.start.month - 1][:3]}"
    return {"hi": f"{day} se", "en": f"from {day}"}[lang]


def _short_name(t: TripRow) -> str:
    return (t.destination or t.title or "Trip").split(",")[0].strip()


def list_my_trips(user_id: str, lang: str, include_past: bool = False, db=None) -> ToolResult:
    trips = load_user_trips(user_id, db)
    pool = [t for t in trips if t.status in OPEN_STATUSES]
    if include_past:
        past = sorted([t for t in trips if t.status == "COMPLETED"], key=lambda t: t.start or date.min, reverse=True)
        pool = past
    else:
        pool = _sort_open(pool)
    nav = [{"type": "navigate", "to": "/trips"}]
    if not pool:
        reply = ({"hi": "Aapki koi purani trip nahi hai.", "en": "You have no past trips."} if include_past else
                 {"hi": "Abhi aapki koi trip nahi hai. Nayi trip banani hai?", "en": "You don't have any trips yet. Want to plan one?"})[lang]
        return ToolResult(reply, ui_actions=nav, action="list_trips", error_code="no_trips")
    spoken = [f"{_short_name(t)} {_when(t, lang)}".strip() for t in pool[:MAX_SPOKEN_TRIPS]]
    joined = (", ".join(spoken[:-1]) + (" aur " if lang == "hi" else " and ") + spoken[-1]) if len(spoken) > 1 else spoken[0]
    n = len(pool)
    if lang == "hi":
        head = f"Aapki {n} {'purani ' if include_past else ''}trip{'s' if n > 1 else ''} {'hain' if n > 1 else 'hai'}: "
        tail = ", aur bhi hain." if n > MAX_SPOKEN_TRIPS else "."
    else:
        head = f"You have {n} {'past ' if include_past else ''}trip{'s' if n > 1 else ''}: "
        tail = ", and more." if n > MAX_SPOKEN_TRIPS else "."
    return ToolResult(head + joined + tail, ui_actions=nav, action="list_trips")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", (s or "").lower()).strip()


def _name_score(query: str, t: TripRow) -> float:
    q = _norm(query)
    if not q:
        return 0.0
    best = 0.0
    for cand in {_norm(t.destination), _norm(t.title), _norm(_short_name(t))}:
        if not cand:
            continue
        if q in cand or cand.split(" ")[0] == q.split(" ")[0]:
            return 1.0
        for word in cand.split():
            if len(word) >= 3 and sorted(word) == sorted(q):  # swapped letters from speech-to-text: "Gao" -> "Goa"
                return 0.9
            best = max(best, difflib.SequenceMatcher(None, q, word).ratio())
        best = max(best, difflib.SequenceMatcher(None, q, cand).ratio())
    return best


def parse_month(raw: Any) -> Optional[int]:
    if raw is None or raw == "":
        return None
    if isinstance(raw, int) and not isinstance(raw, bool):
        return raw if 1 <= raw <= 12 else None
    s = str(raw).strip().lower()
    if s.isdigit():
        n = int(s)
        return n if 1 <= n <= 12 else None
    return MONTH_ALIASES.get(s) or MONTH_ALIASES.get(s[:3])


def open_trip(user_id: str, lang: str, name_or_destination: Optional[str] = None, month: Any = None,
              which: Optional[str] = None, db=None) -> ToolResult:
    trips = load_user_trips(user_id, db)
    today = _today()
    if not trips:
        return ToolResult({"hi": "Abhi aapki koi trip nahi hai.", "en": "You don't have any trips yet."}[lang],
                          ui_actions=[{"type": "navigate", "to": "/trips"}], action="open_trip_none", error_code="no_trips")

    which = (which or "").strip().lower() or None
    m = parse_month(month)
    query = (name_or_destination or "").strip()

    cands = list(trips)
    if query:
        scored = [(t, _name_score(query, t)) for t in cands]
        cands = [t for t, s in scored if s >= 0.75]
    if m:
        cands = [t for t in cands if t.start and t.start.month == m]
    if which == "current":
        cands = [t for t in cands if t.start and t.end and t.start <= today <= t.end]
    elif which == "next":
        cands = [t for t in cands if t.start and t.start > today and t.status in OPEN_STATUSES]
        cands = sorted(cands, key=lambda t: t.start)[:1]
    elif which == "last":
        cands = [t for t in cands if t.status == "COMPLETED" or (t.end and t.end < today)]
        cands = sorted(cands, key=lambda t: t.start or date.min, reverse=True)[:1]
    elif len(cands) > 1:
        # By name only: prefer open trips; past ones only if nothing open matches.
        open_ones = [t for t in cands if t.status in OPEN_STATUSES]
        cands = open_ones or cands

    if not cands:
        return ToolResult({"hi": "Is naam ki koi trip nahi mili.", "en": "I couldn't find a trip like that."}[lang],
                          action="open_trip_none", error_code="not_found")
    if len(cands) == 1:
        t = cands[0]
        reply = {"hi": f"{_short_name(t)} wali trip khol di.", "en": f"Opened your {_short_name(t)} trip."}[lang]
        return ToolResult(reply, ui_actions=[{"type": "open_trip", "trip_id": t.id}, {"type": "navigate", "to": "/trip"}],
                          action="open_trip")

    # Several: ask which, by month (or by date when the months are the same).
    cands = _sort_open(cands)[:3]
    months = [MONTHS_EN[t.start.month - 1] if t.start else "?" for t in cands]
    if len(set(months)) == len(months):
        options = [f"{mo} wali" if lang == "hi" else f"the {mo} one" for mo in months]
    else:
        options = [_when(t, lang) for t in cands]
    name = _short_name(cands[0]) if len({_short_name(t) for t in cands}) == 1 else None
    sep = " ya " if lang == "hi" else " or "
    if lang == "hi":
        reply = (f"{name} ki {len(cands)} trips hain: " if name else f"{len(cands)} trips milin: ") + sep.join(options) + "?"
    else:
        reply = (f"You have {len(cands)} {name} trips: " if name else f"I found {len(cands)} trips: ") + sep.join(options) + "?"
    return ToolResult(reply, action="open_trip_ask", error_code="ambiguous")
