"""
Work / event / other trips (trip_purpose.FOCUSED_PURPOSES): the generic activities the model marks with planSlot,
made real by code after the plan is generated (itinerary_service PURPOSE RULES C, D and F). These three are meant to
repeat across days, so itinerary_service.validate_and_sanitize_itinerary exempts them (and only them, and only on
these purposes) from the cross-day duplicate and coordinate-reuse checks, and place_verify never looks them up.

  planSlot "STAY":  the model never names a hotel; it writes "Hotel near <base area>". Our code finds ONE real hotel
                    with ONE Google Places text search ("hotel near <base area>, <city>", type lodging, a circle of
                    STAY_SEARCH_RADIUS_M around the base area), keeps results within STAY_RADIUS_KM that have at least
                    STAY_MIN_REVIEWS reviews, and picks the best rating (more reviews break a tie). The same hotel goes
                    on the check-in and every later stay line of the trip. No result / an error / the call cap: the
                    generic line "Hotel near <base area>" stays and no name is invented.
  planSlot "EVENT": the event itself. Our code writes it as "Your <word>, in the <base area> area", "Venue and
                    timings as per your <word>", no clock time, no coordinates, no place id (the model's wording,
                    venue and time are never kept).
  planSlot "WORK":  a preparation / work / rest session in the hotel room. The model's (day-specific) title and
                    description are kept; the location is written by code: the stay hotel's name and coordinates
                    when one was found, else "Hotel near <base area>". Never a place id or verify_status.

Storing the hotel: place_id, coordinates, its name and its address are written into the activity (the owner's
decision, 28 Nov 2026; an exception to place_verify's place_id + coordinates-only rule, for this one hotel line).
Never raises into trip creation: callers treat any failure as "no hotel found".
Logs: counts only (found / generic, google_calls), never a name, query or key.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

STAY, EVENT, WORK = "STAY", "EVENT", "WORK"
GENERIC_SLOTS = (STAY, EVENT, WORK)
STAY_RADIUS_KM = 3.0            # the hotel must be this close to the base area (not BASE_AREA_RADIUS_KM)
STAY_SEARCH_RADIUS_M = 3000     # the Google locationBias circle
STAY_MIN_REVIEWS = 20
_LODGING_TYPES = {"lodging", "hotel", "resort_hotel", "motel", "guest_house", "hostel", "bed_and_breakfast",
                  "extended_stay_hotel", "inn"}
_LABEL_MAX = 30


def slot_of(act: Any) -> Optional[str]:
    slot = str(getattr(act, "planSlot", None) or "").strip().upper()
    return slot if slot in GENERIC_SLOTS else None


def applies(trip: Any) -> bool:
    from trip_purpose import is_focused
    return is_focused(getattr(trip, "purpose_type", None))


def is_generic_block(act: Any, purpose_type: Any) -> bool:
    """True for a planSlot activity (STAY / EVENT / WORK) of a business / event / other trip: a block meant to repeat
    across days. Always False for leisure, pilgrimage and no purpose (their checks stay strict)."""
    from trip_purpose import is_focused
    return is_focused(purpose_type) and slot_of(act) is not None


def area_of(trip: Any) -> Tuple[str, Optional[Tuple[float, float]], str]:
    """(area name, (lat, lng) or None, city) for the stay search and the fixed lines: the base area, else the
    destination."""
    from trip_lifecycle import clean_place_name
    from trip_purpose import base_area_coords
    area = getattr(trip, "base_area", None) if isinstance(getattr(trip, "base_area", None), dict) else None
    dest = trip.destination if isinstance(getattr(trip, "destination", None), dict) else {}
    city = clean_place_name(str(dest.get("city") or dest.get("name") or "").split(",")[0]) or ""
    if area and base_area_coords(area):
        return clean_place_name(area.get("name")) or city or "the city", base_area_coords(area), city
    try:
        coords = (float(dest["latitude"]), float(dest["longitude"]))
    except (KeyError, TypeError, ValueError):
        coords = None
    return clean_place_name(dest.get("name")) or city or "the city", coords, city


def _google_hotels(query: str, lat: float, lng: float, radius_m: float) -> List[Dict[str, Any]]:
    """ONE Places Text Search (New) call, type lodging, biased to the circle, with rating + review count."""
    from places import _run_sync
    from services.google_maps_service import GoogleCallCounter, text_search_places
    return _run_sync(text_search_places(query, counter=GoogleCallCounter(), included_type="lodging",
                                        bias=(lat, lng, radius_m), with_rating=True))


def find_stay_hotel(trip: Any, hotel_search: Callable = None) -> Optional[Dict[str, Any]]:
    """The best-rated real hotel within STAY_RADIUS_KM of the base area, or None (no result / failure)."""
    from plan_card_itinerary import _km
    name, centre, city = area_of(trip)
    if centre is None:
        return None
    query = f"hotel near {name}, {city}" if city and city.lower() not in name.lower() else f"hotel near {name}"
    try:
        hits = (hotel_search or _google_hotels)(query, centre[0], centre[1], STAY_SEARCH_RADIUS_M) or []
    except Exception as err:       # quota / paused / network: the generic line stays
        print(f"[PURPOSE PLAN] stay=generic reason={type(err).__name__}", flush=True)
        return None
    best = None
    for h in hits:
        try:
            lat, lng = float(h["latitude"]), float(h["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        types = set(h.get("types") or [])
        rating, reviews = h.get("rating"), h.get("user_rating_count") or 0
        if not h.get("name") or not h.get("place_id") or (types and not types & _LODGING_TYPES):
            continue
        if not isinstance(rating, (int, float)) or reviews < STAY_MIN_REVIEWS or _km(centre[0], centre[1], lat, lng) > STAY_RADIUS_KM:
            continue
        if best is None or (rating, reviews) > (best[0], best[1]):
            best = (rating, reviews, {"place_id": str(h["place_id"])[:300], "name": str(h["name"])[:120],
                                      "address": str(h.get("display_name") or h.get("city") or "")[:200],
                                      "latitude": lat, "longitude": lng})
    return best[2] if best else None


def _label(trip: Any) -> str:
    """The event / work word for the event line: the user's own word when short, else the type's word."""
    text = (getattr(trip, "purpose_text", None) or "").strip()
    if text and len(text) <= _LABEL_MAX:
        return text
    return {"event": "event", "business": "work"}.get(getattr(trip, "purpose_type", None), "plans")


def slot_override(act: Any, trip: Any, check: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The activity columns our code writes for a planSlot activity of a work / event trip, or None (no change).
    check: place_verify's record for this activity ({"stay": hotel or None, ...} for a STAY / WORK line)."""
    slot = slot_of(act)
    if slot is None or not applies(trip):
        return None
    area, _, _ = area_of(trip)
    if slot == EVENT:
        word = _label(trip)
        return {"title": f"Your {word}, in the {area} area", "description": f"Venue and timings as per your {word}.",
                "location_name": f"{area} area", "time_slot": "As per your event", "latitude": None, "longitude": None,
                "estimated_cost_inr": 0, "place_id": None, "verify_status": None}
    hotel = (check or {}).get("stay")
    if slot == WORK:
        return {"location_name": f"Your room at {hotel['name']}" if hotel else f"Hotel near {area}",
                "latitude": hotel["latitude"] if hotel else None, "longitude": hotel["longitude"] if hotel else None,
                "estimated_cost_inr": 0, "place_id": None, "verify_status": None}
    prefix = "Check in" if str(getattr(act, "title", "") or "").strip().lower().startswith("check") else "Stay"
    if hotel:
        return {"title": f"{prefix}: {hotel['name']}", "description": f"A hotel within {STAY_RADIUS_KM:g} km of {area}.",
                "location_name": hotel["address"] or hotel["name"], "latitude": hotel["latitude"],
                "longitude": hotel["longitude"], "estimated_cost_inr": 0, "place_id": hotel["place_id"],
                "verify_status": (check or {}).get("status") or "verified"}
    return {"title": f"{prefix}: Hotel near {area}", "description": f"Choose a hotel near {area}.",
            "location_name": f"Hotel near {area}", "latitude": None, "longitude": None, "estimated_cost_inr": 0,
            "place_id": None, "verify_status": None}
