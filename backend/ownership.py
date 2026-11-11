"""
Single place for "does this user own this trip / activity?" checks.

Every route and WebSocket action that reads or changes a trip must go through
these helpers. They never fall back to another user's data.
"""
from typing import List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy.orm import Session

from models_trip import TripModel
from models_itinerary import ItineraryModel, ItineraryDayModel, ItineraryActivityModel


def trip_id_candidates(trip_id: Optional[str]) -> List[str]:
    """The frontend sends trip IDs with or without the 'trip_' prefix."""
    clean = (trip_id or "").strip()
    if not clean:
        return []
    bare = clean[len("trip_"):] if clean.startswith("trip_") else clean
    return list(dict.fromkeys([clean, f"trip_{bare}", bare]))


def find_owned_trip(db: Session, trip_id: Optional[str], user_id: Optional[str]) -> Optional[TripModel]:
    candidates = trip_id_candidates(trip_id)
    if not candidates or not user_id:
        return None
    return (
        db.query(TripModel)
        .filter(TripModel.id.in_(candidates), TripModel.user_id == user_id)
        .first()
    )


def require_owned_trip(db: Session, trip_id: Optional[str], user_id: Optional[str]) -> TripModel:
    trip = find_owned_trip(db, trip_id, user_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    return trip


def latest_owned_trip(db: Session, user_id: Optional[str]) -> Optional[TripModel]:
    if not user_id:
        return None
    return (
        db.query(TripModel)
        .filter(TripModel.user_id == user_id)
        .order_by(TripModel.created_at.desc())
        .first()
    )


def find_owned_activity(
    db: Session, activity_id: Optional[str], user_id: Optional[str]
) -> Optional[Tuple[ItineraryActivityModel, TripModel]]:
    """Returns (activity, trip) only when the activity belongs to one of the user's trips."""
    if not activity_id or not user_id:
        return None
    row = (
        db.query(ItineraryActivityModel, TripModel)
        .join(ItineraryDayModel, ItineraryDayModel.id == ItineraryActivityModel.day_id)
        .join(ItineraryModel, ItineraryModel.id == ItineraryDayModel.itinerary_id)
        .join(TripModel, TripModel.id == ItineraryModel.trip_id)
        .filter(ItineraryActivityModel.id == activity_id, TripModel.user_id == user_id)
        .first()
    )
    return (row[0], row[1]) if row else None


def require_owned_activity(
    db: Session, activity_id: Optional[str], user_id: Optional[str]
) -> Tuple[ItineraryActivityModel, TripModel]:
    found = find_owned_activity(db, activity_id, user_id)
    if not found:
        raise HTTPException(status_code=404, detail="Activity not found")
    return found
