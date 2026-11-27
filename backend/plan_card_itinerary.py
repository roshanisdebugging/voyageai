"""
Itinerary for a trip made from a checked plan (a pilgrimage card), built in the worker instead of the AI flow.

- Card days are copied exactly (days rule in pilgrimage.plan_days); one item per stop, in card order, time slot
  "Flexible" (cards have no times, and none is invented), cost unknown (shown as nothing, never "Free").
- Each stop is looked up with the shared Google search ("<name> <city>"). Several results are normal: the one
  within RESOLVE_RADIUS_KM of the destination whose name matches best is used (see resolve()). No results, none
  within the radius, no name match, quota or paused: the item stays without coordinates and is listed as
  unresolved with that reason. Never guessed.
  Only the place_id and the coordinates Google returned are kept (option (a) agreed with the owner).
- Extra days (trip longer than the card): the AI plans only those days, gets the card's places as a
  do-not-repeat list, and each place it names must be found through Google in the same way; places that are not
  found are dropped. If the AI fails or nothing is left, the day stays a free day. Never filled with guesses.
- Never uses or fills the itinerary cache.
- What came from where is saved in trips.preferences_snapshot_json["planCard"] (no migration).
Logs: trip / card ids, counts, timings and error class names only.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

import pilgrimage

FLEXIBLE = "Flexible"
FREE_DAY_TITLE = "Free day"
MAX_AI_ITEMS_PER_DAY = 4


def _day_date(start: str, day_number: int) -> str:
    return (datetime.strptime(start[:10], "%Y-%m-%d") + timedelta(days=day_number - 1)).strftime("%Y-%m-%d")


def _default_search(query: str):
    from places import search_places_detailed
    return search_places_detailed(query)


# Choosing among Google's results for a stop (never a guess):
#   1. only results within RESOLVE_RADIUS_KM of the destination's centre (25 km: Sarnath from Varanasi counts);
#   2. among those, the best name match (case and punctuation ignored, partial matches accepted, "Shri" /
#      "Temple" / "Mandir" ignored), ties broken by Google's own order;
#   3. no results, none within the radius, or no name match at all: unresolved, with that reason.
RESOLVE_RADIUS_KM = 25.0
NAME_MATCH_MIN = 0.5          # at least half of the stop name's words must match the result's name
_GENERIC_WORDS = {"shri", "sri", "shree", "sree", "the", "of", "and", "ji", "temple", "mandir", "mandiram"}


def _km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    from math import asin, cos, radians, sin, sqrt
    dlat, dlng = radians(lat2 - lat1), radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return 2 * 6371.0 * asin(sqrt(a))


def _fold(word: str) -> str:
    """Spelling variants of transliterated names: Vishwanath == Vishvanath, Dashashwamedh == Dasaswamedh."""
    w = word.replace("w", "v").replace("sh", "s").replace("aa", "a").replace("ee", "i").replace("oo", "u")
    return w


def _name_words(text: str) -> List[str]:
    words = [_fold(w) for w in pilgrimage.normalise(text).split()]
    kept = [w for w in words if w not in {_fold(g) for g in _GENERIC_WORDS}]
    return kept or words


def _alternatives(stop_name: str) -> List[str]:
    """'Sarnath (Dhamek Stupa and Archaeological Museum)' -> ['Sarnath', 'Dhamek Stupa', 'Archaeological Museum']."""
    main, _, rest = stop_name.partition("(")
    alts = [main.strip()]
    for part in re.split(r"\band\b|,|/|\)", rest):
        if part.strip():
            alts.append(part.strip())
    return [a for a in alts if a]


def _word_match(a: str, b: str) -> bool:
    return a == b or (min(len(a), len(b)) >= 5 and (a.startswith(b) or b.startswith(a)))


def name_score(stop_name: str, result_name: str) -> float:
    """0..1: the best share of a stop-name alternative's words found in the result's name."""
    got = _name_words(result_name)
    best = 0.0
    for alt in _alternatives(stop_name):
        want = _name_words(alt)
        if want:
            best = max(best, sum(1 for w in want if any(_word_match(w, g) for g in got)) / len(want))
    return best


def destination_centre(trip, city: str, search_fn: Callable = None) -> Optional[Tuple[float, float]]:
    """The trip destination's coordinates (from the wizard / Google); else one Google look-up of the city."""
    dest = (trip.destination or {}) if isinstance(trip.destination, dict) else {}
    try:
        return float(dest["latitude"]), float(dest["longitude"])
    except (KeyError, TypeError, ValueError):
        pass
    try:
        found = (search_fn or _default_search)(city)
        hit = (list(getattr(found, "results", None) or []) or [None])[0]
        return (float(hit["latitude"]), float(hit["longitude"])) if hit else None
    except Exception:
        return None


def resolve(name: str, city: str, search_fn: Callable = None,
            centre: Optional[Tuple[float, float]] = None,
            radius_km: float = RESOLVE_RADIUS_KM) -> Tuple[Optional[Dict[str, Any]], str]:
    """(place, why). place = {place_id, latitude, longitude, ambiguous} or None.
    why = ok | no_results | outside_radius | no_name_match | unavailable | error:<Class>.
    One Google search per call ("<name> <city>", the shared, ranked, India-only search).
    radius_km: card stops use RESOLVE_RADIUS_KM; place_verify passes a wider trip radius (its own distance check
    then flags a stop far from the rest of its day)."""
    search_fn = search_fn or _default_search
    try:
        found = search_fn(f"{name} {city}")
    except Exception as err:
        return None, f"error:{type(err).__name__}"
    if getattr(found, "unavailable", False):
        return None, "unavailable"
    ranked = []
    for rank, hit in enumerate(getattr(found, "results", None) or []):
        try:
            ranked.append((rank, hit, float(hit["latitude"]), float(hit["longitude"])))
        except (KeyError, TypeError, ValueError):
            continue
    if not ranked:
        return None, "no_results"
    if centre is not None:
        ranked = [r for r in ranked if _km(centre[0], centre[1], r[2], r[3]) <= radius_km]
        if not ranked:
            return None, "outside_radius"
    scored = [(name_score(name, str(r[1].get("name") or "")), r) for r in ranked]
    scored = [s for s in scored if s[0] >= NAME_MATCH_MIN]
    if not scored:
        return None, "no_name_match"
    score, (rank, hit, lat, lng) = max(scored, key=lambda s: (s[0], -s[1][0]))   # best name, then Google's order
    return {"place_id": hit.get("place_id") or hit.get("id"), "latitude": lat, "longitude": lng,
            "ambiguous": bool(getattr(found, "ambiguous", False)) or len(ranked) > 1}, "ok"


def _extra_days_prompt(dest: str, region: str, first_day: int, count: int, avoid: List[str]) -> str:
    return (
        f"Plan {count} more day(s) of a trip to {dest}, {region}, India: trip days {first_day} to {first_day + count - 1}.\n"
        "Rules:\n"
        "- Only real places that exist in or near the destination. If you are not sure a place exists, leave it out.\n"
        f"- At most {MAX_AI_ITEMS_PER_DAY} places per day. Fewer is fine. An empty day is fine.\n"
        "- Do NOT include any of these places (already in the plan): " + "; ".join(avoid) + "\n"
        "- No opening hours, prices, ticket rules or times: they are checked elsewhere.\n"
        "- description: one short sentence about what the place is, nothing else.\n"
        'Return JSON only: {"days": [{"dayNumber": <int>, "title": "<short title>", '
        '"places": [{"name": "<place name>", "description": "<one sentence>"}]}]}'
    )


def _ask_ai(prompt: str, complete_fn: Callable = None) -> Optional[Dict[str, Any]]:
    """The AI's extra days, or None on any failure (mock mode, provider error, bad JSON)."""
    if complete_fn is None:
        from ai_provider import complete_json as complete_fn
    try:
        raw = complete_fn(prompt)
        data = json.loads(raw) if isinstance(raw, str) else raw
        return data if isinstance(data, dict) and isinstance(data.get("days"), list) else None
    except Exception as err:
        print(f"[PILGRIMAGE] ai extra days failed error={type(err).__name__}", flush=True)
        return None


def build_days(trip, card: pilgrimage.Card, search_fn: Callable = None, complete_fn: Callable = None) -> Dict[str, Any]:
    """Pure-ish: the days to save plus the per-day / per-stop info. No database writes here."""
    plan = pilgrimage.plan_days(card, trip.total_days)
    dest = (trip.destination or {}) if isinstance(trip.destination, dict) else {}
    dest_city = dest.get("city") or dest.get("name") or card.match_names[0]
    days: List[Dict[str, Any]] = []
    stats = {"google_lookups": 0, "unresolved": 0, "ai_called": False, "ai_items": 0,
             "resolved": 0, "resolved_from_ambiguous": 0, "reasons": {}}
    centre = destination_centre(trip, dest_city, search_fn)

    for i, pd in enumerate(plan.card_days, start=1):
        items = []
        for stop in pd.stops:
            place, why = resolve(stop.name, stop.city, search_fn, centre)
            stats["google_lookups"] += 1
            stats["unresolved"] += 0 if place else 1
            if place:
                stats["resolved"] += 1
                stats["resolved_from_ambiguous"] += 1 if place.get("ambiguous") else 0
            else:
                stats["reasons"][why] = stats["reasons"].get(why, 0) + 1
            items.append({"title": stop.name, "description": stop.note, "location_name": stop.city, "place": place,
                          "why": why, "priority": stop.priority, "visit_minutes": stop.visit_minutes, "source": "card"})
        days.append({"day_number": i, "title": pd.title, "source": "card", "card_day": pd.card_day, "items": items})

    if plan.extra_days:
        first = len(plan.card_days) + 1
        avoid = [s.name for d in card.days for s in d.stops]
        stats["ai_called"] = True
        ai = _ask_ai(_extra_days_prompt(dest.get("name") or card.short_name, card.region, first, plan.extra_days, avoid),
                     complete_fn)
        ai_days = {}
        for d in (ai or {}).get("days", []):
            try:
                ai_days[int(d.get("dayNumber"))] = d
            except (TypeError, ValueError):
                continue
        seen = {pilgrimage.normalise(n) for n in avoid}
        seen_ids = {it["place"]["place_id"] for d in days for it in d["items"] if it["place"]}
        for n in range(first, first + plan.extra_days):
            d = ai_days.get(n) or {}
            items = []
            for p in (d.get("places") or [])[:MAX_AI_ITEMS_PER_DAY]:
                name = str((p or {}).get("name") or "").strip()[:120]
                if len(name) < 2 or pilgrimage.normalise(name) in seen:
                    continue
                place, why = resolve(name, dest_city, search_fn, centre)
                stats["google_lookups"] += 1
                if not place or place["place_id"] in seen_ids:
                    continue   # not found through Google (or a repeat): left out, never guessed
                seen.add(pilgrimage.normalise(name))
                seen_ids.add(place["place_id"])
                desc = str((p or {}).get("description") or "").strip()[:300] or None
                items.append({"title": name, "description": desc, "location_name": dest_city, "place": place, "why": why,
                              "priority": None, "visit_minutes": None, "source": "ai"})
            stats["ai_items"] += len(items)
            if items:
                title = str(d.get("title") or "").strip()[:120] or f"Day {n}"
                days.append({"day_number": n, "title": title, "source": "ai", "card_day": None, "items": items})
            else:
                days.append({"day_number": n, "title": FREE_DAY_TITLE, "source": "free", "card_day": None, "items": []})
    return {"days": days, "stats": stats, "plan_days": len(plan.card_days), "extra_days": plan.extra_days}


def generate(trip, db, card: pilgrimage.Card, search_fn: Callable = None, complete_fn: Callable = None) -> str:
    """Builds and saves the itinerary for a card trip. Returns "READY". Raises on a database error (the caller
    marks the trip FAILED, as for the AI flow)."""
    from models_itinerary import ItineraryActivityModel, ItineraryDayModel, ItineraryModel
    from sqlalchemy import null

    started = time.perf_counter()
    built = build_days(trip, card, search_fn, complete_fn)
    now = datetime.utcnow().isoformat() + "Z"

    existing = db.query(ItineraryModel).filter(ItineraryModel.trip_id == trip.id).first()
    version = (existing.version + 1) if existing else 1
    if existing:
        db.delete(existing)
        db.flush()
    itin_id = f"itin_{uuid.uuid4().hex[:12]}"
    db.add(ItineraryModel(id=itin_id, trip_id=trip.id, version=version, status="READY",
                          provider_name="PLAN_CARD" + ("+AI" if built["stats"]["ai_items"] else ""),
                          created_at=now, updated_at=now))
    db.flush()

    day_info, stop_info, total = [], {}, 0
    for d in built["days"]:
        day_id = f"day_{uuid.uuid4().hex[:10]}"
        db.add(ItineraryDayModel(id=day_id, itinerary_id=itin_id, day_number=d["day_number"],
                                 date=_day_date(trip.start_date, d["day_number"]), title=d["title"], summary=None))
        db.flush()
        day_info.append({"dayNumber": d["day_number"], "source": d["source"], "cardDay": d["card_day"]})
        for it in d["items"]:
            act_id = f"act_{uuid.uuid4().hex[:10]}"
            place = it["place"]
            db.add(ItineraryActivityModel(
                id=act_id, day_id=day_id, time_slot=FLEXIBLE, title=it["title"], description=it["description"],
                activity_type="SIGHTSEEING", location_name=it["location_name"],
                latitude=place["latitude"] if place else None, longitude=place["longitude"] if place else None,
                estimated_cost_inr=null(),   # unknown: NULL (a plain None would become the column default 0)
                booking_required=False, is_confirmed=False))
            stop_info[act_id] = {"placeId": place["place_id"] if place else None, "unresolved": place is None,
                                 "reason": None if place else it["why"],
                                 "source": it["source"], "priority": it["priority"], "visitMinutes": it["visit_minutes"]}
            total += 1

    snap = dict(trip.preferences_snapshot or {})
    meta = dict(snap.get("planCard") or {})
    meta.update({"days": day_info, "stops": stop_info, "builtVersion": card.version})
    snap["planCard"] = meta
    trip.preferences_snapshot = snap
    progress = dict(trip.progress or {})
    progress["totalActivitiesCount"] = total
    trip.progress = progress
    trip.itinerary_status = "READY"
    trip.updated_at = now
    db.commit()
    s = built["stats"]
    ai_days = sum(1 for d in day_info if d["source"] == "ai")
    free_days = sum(1 for d in day_info if d["source"] == "free")
    reasons = ",".join(f"{k}:{v}" for k, v in sorted(s["reasons"].items())) or "none"
    print(f"[PILGRIMAGE] built trip={trip.id} card={card.id} user_days={trip.total_days} card_days={built['plan_days']} "
          f"ai_days={ai_days} unresolved_stops={s['unresolved']} resolved={s['resolved']} "
          f"resolved_from_ambiguous={s['resolved_from_ambiguous']} unresolved={s['unresolved']} reasons={reasons} "
          f"free_days={free_days} items={total} google_lookups={s['google_lookups']} "
          f"ms={int((time.perf_counter() - started) * 1000)}", flush=True)
    return "READY"
