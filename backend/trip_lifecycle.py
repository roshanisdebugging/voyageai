"""
Shared trip creation and serialization.

REST (POST /api/trips) and the WebSocket action trips:create both call
create_trip_for_user, so validation, limits and queueing behave the same way.
"""
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from media_service import media_service
from models import AuthUser, UserPreferences, UserProfile
from models_trip import TripModel
from places import validate_destination_payload
from task_queue import enqueue_itinerary_generation

MAX_TRIP_DAYS = 30
MAX_TRAVELERS = 20


class TripValidationError(ValueError):
    """Bad trip input. The message is safe to show to the user."""


def serialize_trip(trip: TripModel) -> Dict[str, Any]:
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
        "coverMedia": trip.cover_media,
        "travelers": trip.travelers,
        "preferencesSnapshot": trip.preferences_snapshot,
        "budget": trip.budget,
        "progress": trip.progress,
        "createdAt": trip.created_at,
        "updatedAt": trip.updated_at,
    }


def _parse_travelers_count(raw: Any) -> int:
    try:
        count = int(raw if raw is not None else 2)
    except (TypeError, ValueError):
        raise TripValidationError("Number of travelers must be a whole number.")
    if not 1 <= count <= MAX_TRAVELERS:
        raise TripValidationError(f"Number of travelers must be between 1 and {MAX_TRAVELERS}.")
    return count


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
            return serialize_trip(existing)

    destination = trip_data.get("destination") or {}
    if isinstance(destination, str):
        destination = {"name": destination, "country": "India"}
    is_valid, err_msg = validate_destination_payload(destination)
    if not is_valid:
        raise TripValidationError(err_msg)
    dest_name = destination["name"].strip()

    start_date, end_date, total_days = _parse_dates(trip_data)
    travelers_count = _parse_travelers_count(trip_data.get("travelersCount"))

    first_name = user_profile.firstName if user_profile else "Me"
    avatar = user_profile.avatarUrl if user_profile else None
    travelers = [
        {
            "id": f"tr_{idx + 1}",
            "name": first_name if idx == 0 else f"Companion {idx + 1}",
            "type": "ADULT",
            "avatarUrl": avatar if idx == 0 else None,
        }
        for idx in range(travelers_count)
    ]

    pref_snapshot = {
        "snapshotVersion": 1,
        "travelStyles": trip_data.get("tripStyle") or prefs.travelStyles,
        "transportPreferences": prefs.transportPreferences,
        "dietaryPreferences": prefs.dietaryPreferences,
        "foodInterests": prefs.foodInterests,
        "activityInterests": prefs.activityInterests,
        "budgetLevel": prefs.budgetLevel,
    }

    budget = {
        "level": trip_data.get("budgetLevel") or prefs.budgetLevel or "MODERATE",
        "targetAmount": 30000,
        "currency": "INR",
    }

    now = datetime.now(timezone.utc).isoformat()
    trip = TripModel(
        id=f"trip_{uuid.uuid4().hex[:12]}",
        user_id=auth_user.id,
        client_request_id=client_req_id,
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
    return serialize_trip(trip)
