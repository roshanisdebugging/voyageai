"""
Shared trip creation and serialization.

REST (POST /api/trips) and the WebSocket action trips:create both call
create_trip_for_user, so validation, limits and queueing behave the same way.
The voice agent's create_trip tool must call it too.
"""
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from media_service import media_service
from models import AuthUser, UserPreferences, UserProfile
from models_place import CityModel, city_to_dict, get_or_create_city
from models_trip import TripModel
from places import validate_destination_payload
from task_queue import enqueue_itinerary_generation

MAX_TRIP_DAYS = 30
MAX_TRAVELERS = 20
MIN_BUDGET_INR = 1000
MAX_BUDGET_INR = 10_000_000

# Budget level from rupees per person per day. A child counts as half a person.
# The level is never shown to the user; it only steers the itinerary prompt and cache.
BUDGET_LEVEL_THRESHOLDS = [
    (2500, "BUDGET"),
    (6000, "MODERATE"),
    (12000, "PREMIUM"),
]


class TripValidationError(ValueError):
    """Bad trip input. The message is safe to show to the user."""


def budget_level_for(amount_inr: float, days: int, adults: int, children: int) -> str:
    people = max(1.0, adults + 0.5 * children)
    per_person_per_day = amount_inr / (people * max(1, days))
    for limit, level in BUDGET_LEVEL_THRESHOLDS:
        if per_person_per_day < limit:
            return level
    return "LUXURY"


def serialize_trip(trip: TripModel, db: Optional[Session] = None) -> Dict[str, Any]:
    origin = None
    if trip.origin_city_id and db is not None:
        origin = city_to_dict(db.query(CityModel).filter(CityModel.id == trip.origin_city_id).first())
    travelers = trip.travelers or []
    return {
        "id": trip.id,
        "userId": trip.user_id,
        "title": trip.title,
        "status": trip.status,
        "itineraryStatus": trip.itinerary_status,
        "startDate": trip.start_date,
        "endDate": trip.end_date,
        "totalDays": trip.total_days,
        "destination": trip.destination,
        "origin": origin,
        "coverMedia": trip.cover_media,
        "travelers": travelers,
        "adultsCount": sum(1 for t in travelers if t.get("type") != "CHILD"),
        "childrenCount": sum(1 for t in travelers if t.get("type") == "CHILD"),
        "preferencesSnapshot": trip.preferences_snapshot,
        "budget": trip.budget,
        "progress": trip.progress,
        "createdAt": trip.created_at,
        "updatedAt": trip.updated_at,
    }


def _parse_int(raw: Any, field: str) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise TripValidationError(f"{field} must be a whole number.")


def _parse_travelers(trip_data: Dict[str, Any]) -> tuple[int, int]:
    """Adults and children. Older clients send only travelersCount (all adults)."""
    if trip_data.get("adultsCount") is not None:
        adults = _parse_int(trip_data.get("adultsCount"), "Number of adults")
        children = _parse_int(trip_data.get("childrenCount") or 0, "Number of children")
    else:
        adults = _parse_int(trip_data.get("travelersCount") if trip_data.get("travelersCount") is not None else 2,
                            "Number of travelers")
        children = 0
    if adults < 1:
        raise TripValidationError("At least one adult must travel.")
    if children < 0:
        raise TripValidationError("Number of children cannot be negative.")
    if adults + children > MAX_TRAVELERS:
        raise TripValidationError(f"A trip can have at most {MAX_TRAVELERS} travelers.")
    return adults, children


def _parse_dates(trip_data: Dict[str, Any]) -> tuple[str, str, int]:
    today = datetime.now().date()
    start_raw = trip_data.get("startDate") or today.isoformat()
    end_raw = trip_data.get("endDate") or start_raw
    try:
        start = datetime.strptime(str(start_raw)[:10], "%Y-%m-%d").date()
        end = datetime.strptime(str(end_raw)[:10], "%Y-%m-%d").date()
    except ValueError:
        raise TripValidationError("Dates must be in YYYY-MM-DD format.")
    if start < today:
        raise TripValidationError("Trip start date cannot be in the past.")
    if end < start:
        raise TripValidationError("Trip end date cannot be earlier than start date.")
    total_days = (end - start).days + 1
    if total_days > MAX_TRIP_DAYS:
        raise TripValidationError(f"Trips can be at most {MAX_TRIP_DAYS} days long.")
    return start.isoformat(), end.isoformat(), total_days


def _parse_place(raw: Any, label: str) -> Dict[str, Any]:
    place = {"name": raw, "country": "India"} if isinstance(raw, str) else (raw or {})
    is_valid, err_msg = validate_destination_payload(place)
    if not is_valid:
        raise TripValidationError(f"{label}: {err_msg}")
    return place


def _parse_budget_amount(raw: Any) -> Optional[int]:
    if raw in (None, ""):
        return None
    amount = _parse_int(raw, "Budget amount")
    if not MIN_BUDGET_INR <= amount <= MAX_BUDGET_INR:
        raise TripValidationError(f"Budget must be between ₹{MIN_BUDGET_INR:,} and ₹{MAX_BUDGET_INR:,}.")
    return amount


def create_trip_for_user(
    db: Session,
    auth_user: AuthUser,
    user_profile: Optional[UserProfile],
    user_prefs: Optional[UserPreferences],
    trip_data: Dict[str, Any],
) -> Dict[str, Any]:
    """Validates input, saves the trip as GENERATING and queues itinerary generation."""
    prefs = user_prefs or UserPreferences(
        userId=auth_user.id,
        createdAt=datetime.now(timezone.utc).isoformat(),
        updatedAt=datetime.now(timezone.utc).isoformat(),
    )

    # Same request sent twice (retry, double tap): return the trip already created.
    client_req_id = trip_data.get("clientRequestId")
    if client_req_id:
        existing = (
            db.query(TripModel)
            .filter(TripModel.user_id == auth_user.id, TripModel.client_request_id == client_req_id)
            .first()
        )
        if existing:
            return serialize_trip(existing, db)

    destination = _parse_place(trip_data.get("destination"), "Destination")
    dest_name = destination["name"].strip()

    origin_city = None
    if trip_data.get("origin"):
        origin_city = get_or_create_city(db, _parse_place(trip_data.get("origin"), "Starting city"))

    start_date, end_date, total_days = _parse_dates(trip_data)
    adults, children = _parse_travelers(trip_data)
    budget_amount = _parse_budget_amount(trip_data.get("budgetAmount", trip_data.get("customBudgetAmount")))

    if budget_amount is not None:
        budget_level = budget_level_for(budget_amount, total_days, adults, children)
    else:
        budget_level = trip_data.get("budgetLevel") or prefs.budgetLevel or "MODERATE"

    first_name = user_profile.firstName if user_profile else "Me"
    avatar = user_profile.avatarUrl if user_profile else None
    travelers = [
        {
            "id": f"tr_{idx + 1}",
            "name": first_name if idx == 0 else f"Adult {idx + 1}",
            "type": "ADULT",
            "avatarUrl": avatar if idx == 0 else None,
        }
        for idx in range(adults)
    ] + [
        {"id": f"tr_{adults + idx + 1}", "name": f"Child {idx + 1}", "type": "CHILD", "avatarUrl": None}
        for idx in range(children)
    ]

    pref_snapshot = {
        "snapshotVersion": 1,
        "travelStyles": trip_data.get("tripStyle") or prefs.travelStyles,
        "transportPreferences": prefs.transportPreferences,
        "dietaryPreferences": prefs.dietaryPreferences,
        "foodInterests": prefs.foodInterests,
        "activityInterests": prefs.activityInterests,
        "budgetLevel": budget_level,
    }

    budget = {
        "level": budget_level,
        "targetAmount": budget_amount,  # None when the user gave no amount
        "currency": "INR",
    }

    now = datetime.now(timezone.utc).isoformat()
    trip = TripModel(
        id=f"trip_{uuid.uuid4().hex[:12]}",
        user_id=auth_user.id,
        client_request_id=client_req_id,
        origin_city_id=origin_city.id if origin_city else None,
        title=f"{dest_name} Tour Package",
        status="PLANNING",
        itinerary_status="GENERATING",
        start_date=start_date,
        end_date=end_date,
        total_days=total_days,
        destination_json=json.dumps(destination),
        cover_media_json=json.dumps(media_service.resolve_cover_media(destination)),
        travelers_json=json.dumps(travelers),
        preferences_snapshot_json=json.dumps(pref_snapshot),
        budget_json=json.dumps(budget),
        progress_json=json.dumps({
            "totalDays": total_days,
            "currentDay": 1,
            "completedActivitiesCount": 0,
            "totalActivitiesCount": total_days * 2,
        }),
        created_at=now,
        updated_at=now,
    )
    db.add(trip)
    db.commit()
    print(f"[TRIP CREATED] {trip.id} '{trip.title}' ({total_days} days) for user {auth_user.id}", flush=True)

    enqueue_itinerary_generation(trip.id)
    return serialize_trip(trip, db)
