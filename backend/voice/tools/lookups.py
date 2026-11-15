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
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

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
    pending_actions: List[Dict[str, Any]] = field(default_factory=list)  # run only after "haan" / "yes"


# ---------------- search a place on the map

def in_india(lat: Any, lng: Any) -> bool:
    """Same box as the frontend's isInIndia()."""
    try:
        return 6.0 <= float(lat) <= 37.5 and 68.0 <= float(lng) <= 97.5
    except (TypeError, ValueError):
        return False


INDIAN_STATES = {
    "andhra pradesh", "arunachal pradesh", "assam", "bihar", "chhattisgarh", "goa", "gujarat", "haryana",
    "himachal pradesh", "jharkhand", "karnataka", "kerala", "madhya pradesh", "maharashtra", "manipur", "meghalaya",
    "mizoram", "nagaland", "odisha", "punjab", "rajasthan", "sikkim", "tamil nadu", "telangana", "tripura",
    "uttar pradesh", "uttarakhand", "west bengal", "delhi", "jammu and kashmir", "ladakh", "puducherry", "chandigarh",
    "andaman and nicobar islands", "lakshadweep", "dadra and nagar haveli and daman and diu",
}


def city_state(hit: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """City and state from the search result's address ("..., Agra, Uttar Pradesh, India")."""
    text = hit.get("city") or hit.get("region") or hit.get("displayName") or ""
    parts = [p.strip() for p in str(text).split(",") if p.strip()]
    if parts and parts[-1].lower() == "india":
        parts = parts[:-1]
    state = city = None
    if parts and parts[-1].lower() in INDIAN_STATES:
        state = parts[-1]
        parts = parts[:-1]
    if parts:
        city = re.sub(r"\s+\d{6}$", "", parts[-1]).strip() or None  # drop a PIN code
    if city and state and city.lower() == state.lower():
        city = None
    return city, state


def _where(name: str, city: Optional[str], state: Optional[str]) -> str:
    """'Agra, Uttar Pradesh' / 'Jaipur' / '' (never repeats the place's own name)."""
    bits = [b for b in (city, state) if b and b.lower() != name.lower()]
    return ", ".join(bits)


def find_place(query: str, search_fn=None) -> Optional[Dict[str, Any]]:
    """Top India result of the existing search (Google), or None."""
    if search_fn is None:
        from places import search_places as search_fn
    try:
        results = search_fn(query) or []
    except Exception:
        results = []
    hits = [r for r in results if r.get("latitude") is not None and in_india(r.get("latitude"), r.get("longitude"))]
    return hits[0] if hits else None


def search_place(query: str, lang: str, show: bool = True, search_fn=None) -> ToolResult:
    """
    show=True  ("Hawa Mahal dikhao"): open the map at once; reply names city/state.
    show=False ("Taj Mahal kahan hai"): answer with city/state and ask "Map par dikhaun?"; the map actions
               are returned as pending_actions and run only after "haan" / "yes" (voice/agent.py).
    """
    q = (query or "").strip()[:120]
    if len(q) < 2:
        return ToolResult({"hi": "Kaunsi jagah?", "en": "Which place?"}[lang], action="reply", error_code="no_query")
    top = find_place(q, search_fn)
    if not top:
        return ToolResult({"hi": "Yeh jagah nahi mili.", "en": "I couldn't find that place."}[lang],
                          action="map_focus_none", error_code="not_found")
    name = (top.get("name") or q)[:120]
    city, state = city_state(top)
    where = _where(name, city, state)
    focus = {"type": "map_focus", "lat": float(top["latitude"]), "lng": float(top["longitude"]), "name": name}
    if top.get("place_id") or top.get("id"):
        focus["place_id"] = str(top.get("place_id") or top.get("id"))[:300]
    actions = [focus, {"type": "navigate", "to": "/map"}]
    if show:
        label = f"{name}, {city}" if city and city.lower() != name.lower() else name
        reply = {"hi": f"{label}: map par dikha diya.", "en": f"Showing {label} on the map."}[lang]
        return ToolResult(reply, ui_actions=actions, action="map_focus")
    if where:
        reply = {"hi": f"{name} {where} mein hai. Map par dikhaun?", "en": f"{name} is in {where}. Shall I show it on the map?"}[lang]
    else:
        reply = {"hi": f"{name} mil gaya. Map par dikhaun?", "en": f"I found {name}. Shall I show it on the map?"}[lang]
    return ToolResult(reply, action="where", pending_actions=actions)


# ---------------- weather (Open-Meteo via weather_service)

DAY_WORDS = {"today": 0, "aaj": 0, "tomorrow": 1, "kal": 1, "day_after_tomorrow": 2, "parso": 2, "parson": 2}


def resolve_day(day: Any, today: date) -> Optional[date]:
    if day is None or day == "":
        return today
    s = str(day).strip().lower().replace(" ", "_")
    if s in DAY_WORDS:
        return today + timedelta(days=DAY_WORDS[s])
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _day_words(d: date, today: date, lang: str) -> str:
    diff = (d - today).days
    names = {"hi": {0: "Aaj", 1: "Kal", 2: "Parso"}, "en": {0: "Today", 1: "Tomorrow", 2: "The day after tomorrow"}}[lang]
    return names.get(diff) or (f"{d.day} {MONTHS_EN[d.month - 1][:3]} ko" if lang == "hi" else f"On {d.day} {MONTHS_EN[d.month - 1][:3]}")


def _trip_destination(user_id: Optional[str], trip_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """The open trip's destination, re-checked against the session user (never trusted from the model)."""
    if not (user_id and trip_id):
        return None
    try:
        from database import get_db_context
        from ownership import find_owned_trip
        with get_db_context() as db:
            trip = find_owned_trip(db, trip_id, user_id)
            if not trip:
                return None
            d = json.loads(trip.destination_json or "{}")
            if d.get("latitude") is None or d.get("longitude") is None:
                return None
            return {"name": (d.get("name") or trip.title or "").split(",")[0], "latitude": d["latitude"], "longitude": d["longitude"]}
    except Exception:
        return None


def get_weather(place: Optional[str], day: Any, lang: str, user_id: Optional[str] = None, trip_id: Optional[str] = None,
                search_fn=None, forecast_fn=None) -> ToolResult:
    """Real forecast (Open-Meteo, up to 16 days) for a named place, or the open trip's destination."""
    from trip_lifecycle import today_ist
    today = today_ist()
    the_day = resolve_day(day, today)
    if the_day is None or the_day < today:
        return ToolResult({"hi": "Kis din ka mausam?", "en": "For which day?"}[lang], action="reply", error_code="bad_day")
    if (the_day - today).days >= 16:
        return ToolResult({"hi": "Itne aage ka mausam abhi pata nahi hai.", "en": "There's no forecast that far ahead yet."}[lang],
                          action="weather", error_code="too_far")
    target = None
    if place and place.strip():
        hit = find_place(place.strip()[:120], search_fn)
        if hit:
            city, _ = city_state(hit)
            target = {"name": city or hit.get("name") or place.strip(), "latitude": hit["latitude"], "longitude": hit["longitude"]}
        else:
            return ToolResult({"hi": "Yeh jagah nahi mili.", "en": "I couldn't find that place."}[lang], action="weather", error_code="not_found")
    else:
        target = _trip_destination(user_id, trip_id)
    if not target:
        return ToolResult({"hi": "Kis jagah ka mausam batau?", "en": "Weather for which place?"}[lang], action="reply", error_code="no_place")

    if forecast_fn is None:
        from weather_service import get_trip_forecast as forecast_fn
    try:
        fc = forecast_fn(float(target["latitude"]), float(target["longitude"]), the_day.isoformat(), the_day.isoformat())
        d = next((x for x in fc.get("days", []) if x.get("date") == the_day.isoformat()), None)
    except Exception:
        d = None
    if not d:
        return ToolResult({"hi": "Abhi mausam ki jaankari nahi mil rahi.", "en": "I couldn't get the weather right now."}[lang],
                          action="weather", error_code="unavailable")
    when, name = _day_words(the_day, today, lang), target["name"]
    rain, hi_t = d.get("rainChancePercent"), d.get("tempMaxC")
    parts_hi, parts_en = [], []
    if rain is not None:
        parts_hi.append(f"baarish ka {round(rain)}% chance hai")
        parts_en.append(f"{round(rain)}% chance of rain")
    if hi_t is not None:
        parts_hi.append(f"high {round(hi_t)}°C")
        parts_en.append(f"high {round(hi_t)}°C")
    if not parts_hi:
        return ToolResult({"hi": "Abhi mausam ki jaankari nahi mil rahi.", "en": "I couldn't get the weather right now."}[lang],
                          action="weather", error_code="unavailable")
    reply = (f"{when} {name} mein " + ", ".join(parts_hi) + ".") if lang == "hi" else (f"{when} in {name}: " + ", ".join(parts_en) + ".")
    return ToolResult(reply, action="weather")


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
