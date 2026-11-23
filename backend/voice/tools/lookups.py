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
    google_calls: Optional[int] = None   # Google requests this tool made (logs only)
    note: Optional[str] = None           # small on-screen text, never spoken (e.g. Google's route warning)
    note_attribution: Optional[str] = None   # "Google Maps" when the note is Google Maps content
    place: Optional[Dict[str, Any]] = None  # step 5: the place found (so "yeh jagah save karo" knows it)


# ---------------- search a place on the map

MAPS_UNAVAILABLE = {"hi": "Map search abhi available nahi hai.", "en": "Map search isn't available right now."}


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


def search(query: str, search_fn=None):
    """The shared place search (places.search_places: Google, ranked, India only), as a PlaceSearch.
    A plain list (a test's search_fn) is ranked the same way."""
    import places
    fn = search_fn or places.search_places
    try:
        results = fn(query) or []
    except places.MapSearchUnavailable as err:
        return places.PlaceSearch(unavailable=True, google_calls=err.google_calls)
    except Exception:
        results = []
    if isinstance(results, places.PlaceResults):
        return places.PlaceSearch(results=list(results), ambiguous=results.ambiguous, choices=list(results.choices),
                                  google_calls=results.google_calls)
    found = places.rank_places(query, list(results)) if results else places.PlaceSearch()
    found.google_calls = None   # unknown for a plain list
    return found


def find_place(query: str, search_fn=None) -> Optional[Dict[str, Any]]:
    """Top India result of the shared search, or None."""
    found = search(query, search_fn)
    return found.results[0] if found.results else None


def _label(hit: Dict[str, Any], with_place: bool) -> str:
    name = str(hit.get("name") or "").strip()[:40]
    if not with_place:
        return name
    city, state = city_state(hit)
    where = next((w for w in (city, state) if w and w.lower() != name.lower()), None)
    return f"{name}, {where}" if where else name


def _choice_reply(choices: List[Dict[str, Any]], lang: str) -> str:
    """'Charminar ya Masjid Char Minar?' (city added only when two names are the same)."""
    names = [str(c.get("name") or "").strip().lower() for c in choices]
    labels = [_label(c, names.count(n) > 1) for c, n in zip(choices, names)]
    sep = " ya " if lang == "hi" else " or "
    joined = labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + sep + labels[-1]
    return {"hi": f"{joined}?", "en": f"Did you mean {joined}?"}[lang]


def search_place(query: str, lang: str, show: bool = True, search_fn=None) -> ToolResult:
    """
    show=True  ("Hawa Mahal dikhao"): open the map at once; reply names city/state.
    show=False ("Taj Mahal kahan hai"): answer with city/state and ask "Map par dikhaun?"; the map actions
               are returned as pending_actions and run only after "haan" / "yes" (voice/agent.py).
    """
    q = (query or "").strip()[:120]
    if len(q) < 2:
        return ToolResult({"hi": "Kaunsi jagah?", "en": "Which place?"}[lang], action="reply", error_code="no_query")
    found = search(q, search_fn)
    calls = found.google_calls
    if found.unavailable:
        return ToolResult(MAPS_UNAVAILABLE[lang], action="map_unavailable", error_code="maps_unavailable",
                          google_calls=calls)
    if not found.results:
        return ToolResult({"hi": "Yeh jagah nahi mili.", "en": "I couldn't find that place."}[lang],
                          action="map_focus_none", error_code="not_found", google_calls=calls)
    if found.ambiguous and len(found.choices) > 1:
        # Never pick a shop, or one of two equally likely landmarks, by default: ask a short choice.
        return ToolResult(_choice_reply(found.choices, lang), action="place_ask", error_code="ambiguous",
                          google_calls=calls)
    top = found.results[0]
    if found.ambiguous:
        # The only result is a shop/unknown place: say what was found and show it only after "haan".
        show = False
    name = (top.get("name") or q)[:120]
    city, state = city_state(top)
    where = _where(name, city, state)
    focus = {"type": "map_focus", "lat": float(top["latitude"]), "lng": float(top["longitude"]), "name": name}
    if top.get("place_id") or top.get("id"):
        focus["place_id"] = str(top.get("place_id") or top.get("id"))[:300]
    actions = [focus, {"type": "navigate", "to": "/map"}]
    # Step 5: the place found, so "yeh jagah save karo" knows it
    place_info = {"place_id": focus.get("place_id"), "name": name, "address": ", ".join(x for x in (city, state) if x)}
    found = {"place_id": focus.get("place_id"), "name": name, "address": ", ".join(x for x in (city, state) if x)}
    if show:
        label = f"{name}, {city}" if city and city.lower() != name.lower() else name
        reply = {"hi": f"{label}: map par dikha diya.", "en": f"Showing {label} on the map."}[lang]
        return ToolResult(reply, ui_actions=actions, action="map_focus", google_calls=calls, place=place_info)
    if where:
        reply = {"hi": f"{name} {where} mein hai. Map par dikhaun?", "en": f"{name} is in {where}. Shall I show it on the map?"}[lang]
    else:
        reply = {"hi": f"{name} mil gaya. Map par dikhaun?", "en": f"I found {name}. Shall I show it on the map?"}[lang]
    return ToolResult(reply, action="where", pending_actions=actions, google_calls=calls, place=place_info)


# ---------------- category near a place ("Hawa Mahal ke paas achha restaurant dikhao")

NEARBY_SPOKEN = 3     # at most three names are spoken; the map shows up to places.CATEGORY_RESULTS


def _names(results: List[Dict[str, Any]]) -> str:
    names = [str(r.get("name") or "")[:60] for r in results[:NEARBY_SPOKEN] if r.get("name")]
    return ", ".join(names)


def _pin_category(gtype: Optional[str], types: Any) -> str:
    """The map pin's category word (the app maps it to sights / food / hotels / experiences)."""
    import places
    for t in types or []:
        if isinstance(t, str) and t not in places.GENERIC_TYPES:
            return t[:40]
    return (gtype or "sights")[:40]


def _spoken_near(near: str, results: List[Dict[str, Any]]) -> str:
    """'Hawa Mahal Jaipur' -> 'Hawa Mahal' when the results are in Jaipur (the city is said by the places anyway)."""
    words = near.split(",")[0].split()
    address = " ".join(str(r.get("city") or r.get("displayName") or "") for r in results[:3]).lower()
    while len(words) > 1 and words[-1].lower() in address:
        words.pop()
    return " ".join(words)


def rough_distance(meters: float, lang: str) -> str:
    """Straight-line distance for speech: "lagbhag 1.2 kilometer" / "lagbhag 400 meter" / "about 1.2 km"."""
    if meters < 1000:
        m = max(50, int(round(meters / 50.0) * 50))
        return {"hi": f"lagbhag {m} meter", "en": f"about {m} metres"}[lang]
    km = meters / 1000.0
    txt = f"{km:.1f}".rstrip("0").rstrip(".") if km < 10 else str(round(km))
    return {"hi": f"lagbhag {txt} kilometer", "en": f"about {txt} km"}[lang]


def rank_for_speech(results: List[Dict[str, Any]], origin: Optional[Tuple[float, float]], match_types) -> List[Dict[str, Any]]:
    """Places of the asked kind first; then by rating and distance (rating minus 0.3 per km from the origin; unrated
    places count as 0). Without an origin, rating only. Stable: Google's order breaks ties. Adds distance_m when known."""
    from places import haversine_meters
    for r in results:
        if origin:
            r["distance_m"] = haversine_meters(origin[0], origin[1], float(r["latitude"]), float(r["longitude"]))
        else:
            r.pop("distance_m", None)   # no origin: no distance (never one left over from another search)

    def key(r):
        matches = not match_types or bool(set(r.get("types") or []) & set(match_types))
        rating = float(r["rating"]) if isinstance(r.get("rating"), (int, float)) else 0.0
        km = (r.get("distance_m") or 0) / 1000.0 if origin else 0.0
        return (0 if matches else 1, -(rating - 0.3 * km))
    return sorted(results, key=key)


def search_nearby(category: Optional[str], near: Optional[str], lang: str, *, near_me: bool = False,
                  user_id: Optional[str] = None, trip_id: Optional[str] = None,
                  origin: Optional[Tuple[float, float]] = None, search_fn=None) -> ToolResult:
    """
    "Howrah ke paas achha restaurant", "Hawa Mahal ke paas cafe", "mere aaspas khane ki achhi jagah", "achha restaurant
    dikhao". Where:
      1. a place the user said (near = X): "restaurants near X" - X wins over the device location. An open trip's
         destination is only a soft hint for an ambiguous X (a 50 km locationBias), never added to the query.
      2. "mere aaspas" / "near me" (near_me) or no place at all: the device location sent with this turn (3 km bias).
         No location -> ONE short question ("Kahan ke paas dekhun?"). The trip destination is never the default.
    ONE Google Text Search call (places.search_category), no Place Details. Map: up to 6 markers. Speech: at most three
    names, ranked by rating and distance, with a rough straight-line distance when the origin is the device.
    """
    import places
    cat = (category or "").strip()[:60]
    if len(cat) < 2:
        return ToolResult({"hi": "Kya dhoondhun? Jaise restaurant, cafe ya hotel.",
                           "en": "What should I look for? A restaurant, cafe or hotel?"}[lang],
                          action="reply", error_code="no_category")
    near_q = (near or "").strip()[:100] or None
    if near_q and _norm_words(near_q) in NEAR_ME_WORDS:
        near_q, near_me = None, True          # the model wrote "me" / "here" as the place
    device = (float(origin[0]), float(origin[1])) if origin else None
    if near_q:
        trip_dest = _trip_destination(user_id, trip_id)
        hint = (float(trip_dest["latitude"]), float(trip_dest["longitude"])) if trip_dest else None
        found = (search_fn or places.search_category)(cat, near=near_q, area=None, bias=hint,
                                                      bias_radius_m=places.TRIP_HINT_RADIUS_M)
        speech_origin = None                   # X's own position isn't known without a second call
    else:
        if not device:
            return ToolResult({"hi": "Kahan ke paas dekhun?", "en": "Near which place should I look?"}[lang],
                              action="reply", error_code="no_area")
        found = (search_fn or places.search_category)(cat, near=None, area=None, bias=device,
                                                      bias_radius_m=places.NEAR_BIAS_RADIUS_M)
        speech_origin = device
    calls = found.google_calls
    gtype, match, plural = places.category_info(cat)
    if near_q:
        spoken = _spoken_near(near_q, found.results)
        where_hi, where_en = f"{spoken} ke paas", f"near {spoken}"
    else:
        where_hi, where_en = "aapke aaspas", "around you"
    if found.unavailable:
        return ToolResult(MAPS_UNAVAILABLE[lang], action="map_unavailable", error_code="maps_unavailable",
                          google_calls=calls)
    if not found.results:
        return ToolResult({"hi": f"{where_hi[:1].upper()}{where_hi[1:]} koi {plural} nahi mile.",
                           "en": f"I couldn't find {plural} {where_en}."}[lang],
                          action="nearby_none", error_code="not_found", google_calls=calls)
    ranked = rank_for_speech(list(found.results), speech_origin, match)
    shown = []
    for r in ranked:
        item = {"name": str(r.get("name") or "")[:120], "lat": float(r["latitude"]), "lng": float(r["longitude"]),
                "category": _pin_category(gtype, r.get("types"))}
        pid = str(r.get("place_id") or r.get("id") or "")
        if pid:
            item["place_id"] = pid[:300]
        if isinstance(r.get("rating"), (int, float)):
            item["rating"] = round(float(r["rating"]), 1)
        address = r.get("city") or r.get("displayName")
        if address:
            item["address"] = str(address)[:200]
        shown.append(item)
    title = {"hi": f"{where_hi[:1].upper()}{where_hi[1:]} {plural}", "en": f"{plural[:1].upper()}{plural[1:]} {where_en}"}[lang][:80]
    actions = [{"type": "map_results", "title": title, "places": shown}, {"type": "navigate", "to": "/map"}]
    spoken_items = []
    for r in ranked[:NEARBY_SPOKEN]:
        name = str(r.get("name") or "")[:60]
        if r.get("distance_m") is not None:
            name = f"{name}, {rough_distance(r['distance_m'], lang)}"
        spoken_items.append(name)
    sep = "; " if speech_origin else ", "
    names = sep.join(spoken_items)
    reply = {"hi": f"{where_hi[:1].upper()}{where_hi[1:]} ye {plural} mile: {names}. Map par dikha diye.",
             "en": f"{plural[:1].upper()}{plural[1:]} {where_en}: {names}. Showing them on the map."}[lang]
    return ToolResult(reply, ui_actions=actions, action="map_results", google_calls=calls)


# The place words that mean "here" (the model sometimes puts them in `near`).
NEAR_ME_WORDS = {"me", "here", "near me", "nearby", "my location", "current location", "mere aaspas", "mere paas",
                 "yahan", "yahan ke paas", "yahin", "aaspas", "paas mein", "around me", "mere aas paas", "aas paas"}


def _norm_words(s: str) -> str:
    return " ".join(re.sub(r"[^a-z ]", " ", (s or "").lower()).split())


# ---------------- travel time (Google Routes API via routes_service)

TRAVEL_MODES = {"drive": "drive", "car": "drive", "cab": "drive", "taxi": "drive",
                "two_wheeler": "two_wheeler", "bike": "two_wheeler", "scooty": "two_wheeler", "scooter": "two_wheeler",
                "walk": "walk", "walking": "walk", "paidal": "walk"}
MODE_WORDS = {"hi": {"drive": "car se", "two_wheeler": "bike se", "walk": "paidal"},
              "en": {"drive": "by car", "two_wheeler": "by bike", "walk": "on foot"}}
ROUTE_UNAVAILABLE = {"hi": "Route abhi available nahi hai.", "en": "Routes aren't available right now."}


def travel_mode(raw: Any) -> str:
    return TRAVEL_MODES.get(str(raw or "").strip().lower().replace(" ", "_"), "drive")


def spoken_distance(meters: float) -> str:
    """"850 m" / "6.8 km" / "240 km" (same in Hinglish and English)."""
    if meters < 1000:
        return f"{int(round(meters / 10.0) * 10)} m"
    km = meters / 1000.0
    return f"{km:.1f} km" if km < 10 else f"{round(km)} km"


def spoken_duration(seconds: float, lang: str) -> str:
    """"22 minute" / "1 ghanta 5 minute" (hi), "22 minutes" / "1 hour 5 minutes" (en)."""
    mins = max(1, int(round(seconds / 60.0)))
    h, m = divmod(mins, 60)
    if lang == "hi":
        hours = f"{h} ghanta" if h == 1 else f"{h} ghante"
        return f"{mins} minute" if not h else (hours + (f" {m} minute" if m else ""))
    if not h:
        return f"{mins} minute" + ("s" if mins != 1 else "")
    return f"{h} hour" + ("s" if h != 1 else "") + (f" {m} minute" + ("s" if m != 1 else "") if m else "")


# Travel time origin rules (same numbers as the app's deviceLocationLogic.ts)
LOCATION_MAX_ACCURACY_M = 1000   # worse than this: not a usable origin
HERE_M = 150                     # closer than this: "you're here", no route call
FAR_AWAY_M = 300_000             # farther than this: straight-line only, no route call
NO_LOCATION = {"hi": "Aapki location nahi mili, location on kijiye.",
               "en": "I couldn't get your location. Please turn location on."}


def get_travel_time(place: Optional[str], mode: Any, lang: str, user_id: Optional[str] = None,
                    trip_id: Optional[str] = None, origin: Optional[Tuple[float, float]] = None,
                    search_fn=None, route_fn=None) -> ToolResult:
    """
    "Hawa Mahal kitni door hai" -> "Hawa Mahal yahan se 6.8 km hai, car se 22 minute."
    Destination: the shared place search (landmark-first). Origin: ONLY the device's current location sent by the app
    with this turn (accuracy 1 km or better). Never the trip destination, a hotel or a previous activity: without a
    usable location it asks to turn location on and makes no route call. Over 300 km: straight-line only, no route
    call; under 150 m: "you're here". Read-only; logs nothing about places.
    """
    from places import haversine_meters
    from services.routes_service import RouteNotFound, RouteUnavailable
    q = (place or "").strip()[:120]
    if len(q) < 2:
        return ToolResult({"hi": "Kahan tak ki doori?", "en": "Distance to which place?"}[lang], action="reply", error_code="no_query")
    if not origin:
        return ToolResult(NO_LOCATION[lang], action="travel_time", error_code="no_origin")
    o_lat, o_lng = float(origin[0]), float(origin[1])
    mode = travel_mode(mode)
    found = search(q, search_fn)
    calls = found.google_calls
    if found.unavailable:
        return ToolResult(MAPS_UNAVAILABLE[lang], action="travel_time", error_code="maps_unavailable", google_calls=calls)
    if not found.results:
        return ToolResult({"hi": "Yeh jagah nahi mili.", "en": "I couldn't find that place."}[lang],
                          action="travel_time", error_code="not_found", google_calls=calls)
    if found.ambiguous and len(found.choices) > 1:
        return ToolResult(_choice_reply(found.choices, lang), action="place_ask", error_code="ambiguous", google_calls=calls)
    dest = found.results[0]
    name = str(dest.get("name") or q)[:60]

    d_lat, d_lng = float(dest["latitude"]), float(dest["longitude"])
    straight_m = haversine_meters(o_lat, o_lng, d_lat, d_lng)
    straight = spoken_distance(straight_m)
    if straight_m < HERE_M:
        return ToolResult({"hi": f"Aap {name} par hi hain.", "en": f"You're at {name}."}[lang],
                          action="travel_time", google_calls=calls)
    if straight_m > FAR_AWAY_M:
        km = round(straight_m / 1000)
        return ToolResult({"hi": f"Aap {name} se door hain, seedhi doori {km} km hai.",
                           "en": f"You're far from {name}: {km} km in a straight line."}[lang],
                          action="travel_time", error_code="far_away", google_calls=calls)

    if route_fn is None:
        from places import _run_sync
        from services.routes_service import compute_route

        def route_fn(*a, **k):
            return _run_sync(compute_route(*a, **k))
    try:
        route = route_fn(o_lat, o_lng, d_lat, d_lng, mode, user_id=user_id)
    except RouteUnavailable:
        reply = {"hi": f"{ROUTE_UNAVAILABLE['hi']} Seedhi doori {straight} hai.",
                 "en": f"{ROUTE_UNAVAILABLE['en']} In a straight line it's {straight}."}[lang]
        return ToolResult(reply, action="travel_time", error_code="routes_unavailable", google_calls=calls)
    except (RouteNotFound, ValueError):
        reply = {"hi": f"Wahan tak ka route nahi mila. Seedhi doori {straight} hai.",
                 "en": f"I couldn't find a route there. In a straight line it's {straight}."}[lang]
        return ToolResult(reply, action="travel_time", error_code="no_route", google_calls=calls)
    if calls is not None and not route.get("cached"):
        calls += 1
    dist, dur = spoken_distance(route["distance_m"]), spoken_duration(route["duration_s"], lang)
    words = MODE_WORDS[lang][mode]
    if lang == "hi":
        reply = f"{name} aapki location se {dist} hai, {words} {dur}."
    else:
        reply = f"{name} is {dist} from your location, {dur} {words}."
    # Google's route warning (walk / bike) goes on screen, not in the spoken reply.
    note = route.get("warning") if mode != "drive" else None
    return ToolResult(reply, action="travel_time", google_calls=calls, note=note,
                      note_attribution="Google Maps" if note else None)


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
    calls = None
    if place and place.strip():
        found = search(place.strip()[:120], search_fn)
        calls = found.google_calls
        if found.unavailable:
            return ToolResult(MAPS_UNAVAILABLE[lang], action="weather", error_code="maps_unavailable", google_calls=calls)
        hit = found.results[0] if found.results else None
        if hit:
            city, _ = city_state(hit)
            target = {"name": city or hit.get("name") or place.strip(), "latitude": hit["latitude"], "longitude": hit["longitude"]}
        else:
            return ToolResult({"hi": "Yeh jagah nahi mili.", "en": "I couldn't find that place."}[lang], action="weather",
                              error_code="not_found", google_calls=calls)
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
                          action="weather", error_code="unavailable", google_calls=calls)
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
                          action="weather", error_code="unavailable", google_calls=calls)
    reply = (f"{when} {name} mein " + ", ".join(parts_hi) + ".") if lang == "hi" else (f"{when} in {name}: " + ", ".join(parts_en) + ".")
    return ToolResult(reply, action="weather", google_calls=calls)


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


def match_trips(user_id: str, name_or_destination: Optional[str] = None, month: Any = None,
                which: Optional[str] = None, db=None) -> Tuple[List[TripRow], List[TripRow]]:
    """(all of the user's trips, the ones matching name / month / next|current|last). Code only, user's own trips."""
    trips = load_user_trips(user_id, db)
    today = _today()
    which = (which or "").strip().lower() or None
    m = parse_month(month)
    query = (name_or_destination or "").strip()

    cands = list(trips)
    if query:
        scored = [(t, _name_score(query, t)) for t in cands]
        exact = [t for t, s in scored if s >= 1.0]
        # An exact name wins over look-alikes ("Udaipur" must not also pick a Jaipur trip, ratio 0.92).
        cands = exact or [t for t, s in scored if s >= 0.75]
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
    return trips, cands


NO_SUCH_TRIP = {"hi": "Is naam ki koi trip nahi mili.", "en": "I couldn't find a trip like that."}


def which_trip_question(cands: List[TripRow], lang: str) -> str:
    """Several trips match: ask which, by month (or by date when the months are the same)."""
    cands = _sort_open(cands)[:3]
    months = [MONTHS_EN[t.start.month - 1] if t.start else "?" for t in cands]
    if len(set(months)) == len(months):
        options = [f"{mo} wali" if lang == "hi" else f"the {mo} one" for mo in months]
    else:
        options = [_when(t, lang) for t in cands]
    name = _short_name(cands[0]) if len({_short_name(t) for t in cands}) == 1 else None
    sep = " ya " if lang == "hi" else " or "
    if lang == "hi":
        return (f"{name} ki {len(cands)} trips hain: " if name else f"{len(cands)} trips milin: ") + sep.join(options) + "?"
    return (f"You have {len(cands)} {name} trips: " if name else f"I found {len(cands)} trips: ") + sep.join(options) + "?"


def open_trip(user_id: str, lang: str, name_or_destination: Optional[str] = None, month: Any = None,
              which: Optional[str] = None, db=None) -> ToolResult:
    trips, cands = match_trips(user_id, name_or_destination, month, which, db)
    if not trips:
        return ToolResult({"hi": "Abhi aapki koi trip nahi hai.", "en": "You don't have any trips yet."}[lang],
                          ui_actions=[{"type": "navigate", "to": "/trips"}], action="open_trip_none", error_code="no_trips")
    if not cands:
        return ToolResult(NO_SUCH_TRIP[lang], action="open_trip_none", error_code="not_found")
    if len(cands) == 1:
        t = cands[0]
        reply = {"hi": f"{_short_name(t)} wali trip khol di.", "en": f"Opened your {_short_name(t)} trip."}[lang]
        return ToolResult(reply, ui_actions=[{"type": "open_trip", "trip_id": t.id}, {"type": "navigate", "to": "/trip"}],
                          action="open_trip")
    return ToolResult(which_trip_question(cands, lang), action="open_trip_ask", error_code="ambiguous")
