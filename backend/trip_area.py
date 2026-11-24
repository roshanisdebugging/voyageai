"""
Is a place inside a trip's destination area? The ONE backend rule for putting a place into an itinerary.

Adding (POST /api/trips/itinerary/add) calls require_place_in_trip_area; every swap / edit / AI replacement calls
require_replacement_in_trip_area. Any new way (a voice add tool doesn't exist yet) must do the same, and can speak
PlaceOutsideTripArea.message as it is. Over REST the error is 422 + error_code (exception handler in main.py).
The app hides the Add button with the same radius (frontend/src/features/trip/tripArea.ts).
"""
import logging
import math
import os
from typing import Any, Optional, Tuple

from places import haversine_meters

log = logging.getLogger("trip_area")

PLACE_OUTSIDE_TRIP_AREA = "place_outside_trip_area"
# Goa is about 100 km long: 60 km covers a destination region but not another state.
DEFAULT_TRIP_AREA_RADIUS_KM = 60.0


class PlaceOutsideTripArea(ValueError):
    """The message is safe to show or speak to the user."""
    code = PLACE_OUTSIDE_TRIP_AREA

    def __init__(self, destination_name: str):
        self.message = f"Yeh jagah aapke {destination_name} trip ke area ke bahar hai." if destination_name \
            else "Yeh jagah aapke trip ke area ke bahar hai."
        super().__init__(self.message)


def trip_area_radius_km() -> float:
    """TRIP_AREA_RADIUS_KM from the environment; anything that isn't a positive number means the default."""
    try:
        value = float(os.getenv("TRIP_AREA_RADIUS_KM", "") or DEFAULT_TRIP_AREA_RADIUS_KM)
    except ValueError:
        return DEFAULT_TRIP_AREA_RADIUS_KM
    return value if math.isfinite(value) and value > 0 else DEFAULT_TRIP_AREA_RADIUS_KM


def _coords(lat: Any, lng: Any) -> Optional[Tuple[float, float]]:
    """Real coordinates, or None. 0,0 is this app's old "unknown", never a place in India."""
    try:
        a, b = float(lat), float(lng)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(a) and math.isfinite(b)) or abs(a) > 90 or abs(b) > 180 or (a == 0 and b == 0):
        return None
    return a, b


def require_place_in_trip_area(trip: Any, latitude: Any, longitude: Any) -> None:
    """Raises PlaceOutsideTripArea when the place is farther than the radius from the trip's destination.
    Coordinates missing on either side: nothing to compare, so it's allowed and a warning is logged."""
    dest = trip.destination or {}
    centre = _coords(dest.get("latitude"), dest.get("longitude"))
    if centre is None:
        log.warning("trip area check skipped: trip %s has no destination coordinates", trip.id)
        return
    place = _coords(latitude, longitude)
    if place is None:
        log.warning("trip area check skipped: no place coordinates sent (trip %s)", trip.id)
        return
    if haversine_meters(*centre, *place) > trip_area_radius_km() * 1000:
        raise PlaceOutsideTripArea(str(dest.get("name") or "").split(",")[0].strip())


def require_replacement_in_trip_area(trip: Any, activity: Any, latitude: Any, longitude: Any) -> None:
    """The same rule for changing an activity already in the trip. An edit that doesn't move it is never refused, so
    an activity added before this rule can still be marked done, renamed, ..."""
    if latitude is None and longitude is None:
        return
    lat = activity.latitude if latitude is None else latitude
    lng = activity.longitude if longitude is None else longitude
    if (lat, lng) == (activity.latitude, activity.longitude):
        return
    require_place_in_trip_area(trip, lat, lng)
