"""
Shared trip actions (voicefirst.md "Step 5 in detail"): the ONE place these changes are written.

Both the taps (/ws/app actions in main.py, the saved-places REST routes) and the voice tools
(voice/tools/actions.py) call these, so the rules exist once. Every function takes the session's
user_id and checks ownership itself (never another user's trip, activity or saved place), even when
the caller already checked.

Raises LookupError("Trip not found" / "Activity not found") for anything the user doesn't own.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from models_itinerary import ItineraryActivityModel, ItineraryDayModel, ItineraryModel
from models_package import TripExpenseModel
from ownership import find_owned_activity, find_owned_trip

# The categories the app shows (frontend TripExpense.category).
EXPENSE_CATEGORIES = ("Transport", "Hotel", "Food", "Activities", "Shopping", "Other")


def _owned_trip(db: Session, user_id: str, trip_id: Optional[str]):
    trip = find_owned_trip(db, trip_id, user_id)
    if not trip:
        raise LookupError("Trip not found")
    return trip


def expense_dict(e: TripExpenseModel) -> Dict[str, Any]:
    return {
        "id": e.id,
        "tripId": e.trip_id,
        "title": e.title,
        "amount": e.amount,
        "category": e.category,
        "paidBy": e.paid_by,
        "isSplit": e.is_split,
        "createdAt": e.created_at,
        "description": e.title,
        "date": e.created_at,
    }


def add_expense(db: Session, user_id: str, trip_id: str, *, title: Optional[str], amount: Any,
                category: Optional[str] = None, paid_by: Optional[str] = None, is_split: bool = False,
                created_at: Optional[str] = None) -> Dict[str, Any]:
    trip = _owned_trip(db, user_id, trip_id)
    expense = TripExpenseModel(
        id=f"exp-{uuid.uuid4().hex[:8]}",
        trip_id=trip.id,
        title=title or "Expense",
        amount=float(amount or 0.0),
        category=category or "Other",
        paid_by=paid_by or "Me",
        is_split=bool(is_split),
        created_at=created_at or datetime.now(timezone.utc).isoformat(),
    )
    db.add(expense)
    db.commit()
    return expense_dict(expense)


def set_activity_done(db: Session, user_id: str, trip_id: str, activity_id: Optional[str], done: bool) -> Dict[str, Any]:
    trip = _owned_trip(db, user_id, trip_id)
    owned = find_owned_activity(db, activity_id, user_id)
    if not owned or owned[1].id != trip.id:
        raise LookupError("Activity not found")
    activity, trip = owned
    activity.is_done = bool(done)
    db.flush()  # the session doesn't autoflush; count must see this change
    trip_activities = (
        db.query(ItineraryActivityModel.is_done)
        .join(ItineraryDayModel, ItineraryDayModel.id == ItineraryActivityModel.day_id)
        .join(ItineraryModel, ItineraryModel.id == ItineraryDayModel.itinerary_id)
        .filter(ItineraryModel.trip_id == trip.id)
        .all()
    )
    progress = dict(trip.progress or {})
    progress["completedActivitiesCount"] = sum(1 for (d,) in trip_activities if d)
    progress["totalActivitiesCount"] = len(trip_activities)
    trip.progress = progress
    db.commit()
    return {"activityId": activity.id, "isDone": activity.is_done, "progress": progress}


def set_trip_budget(db: Session, user_id: str, trip_id: str, amount: Any) -> Dict[str, Any]:
    """The trip's total budget (rupees), from the itinerary page's "Set budget". Same range as trip creation
    (trip_lifecycle MIN/MAX_BUDGET_INR); the budget level follows the amount. Voice set_trip_budget asks first, then
    saves through the same itinerary_service.set_trip_budget_amount."""
    import itinerary_service
    from trip_lifecycle import MAX_BUDGET_INR, MIN_BUDGET_INR, serialize_trip
    trip = _owned_trip(db, user_id, trip_id)
    try:
        value = float(amount)
    except (TypeError, ValueError):
        raise ValueError("Enter the budget in rupees.")
    if value != value or not MIN_BUDGET_INR <= value <= MAX_BUDGET_INR:
        raise ValueError(f"Budget must be between ₹{MIN_BUDGET_INR:,} and ₹{MAX_BUDGET_INR:,}.")
    budget = itinerary_service.set_trip_budget_amount(db, trip.id, value)
    db.refresh(trip)
    return {"budget": budget, "trip": serialize_trip(trip, db)}


def swap_activity(db: Session, user_id: str, trip_id: str, activity_id: Optional[str],
                  replacement: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not activity_id:
        raise ValueError("activity_id is required for swap_activity")
    trip = _owned_trip(db, user_id, trip_id)
    owned = find_owned_activity(db, activity_id, user_id)
    if not owned or owned[1].id != trip.id:
        raise LookupError("Activity not found")
    act = owned[0]
    replacement = replacement or {}
    if replacement:
        act.title = replacement.get("name") or replacement.get("title") or act.title
        act.description = replacement.get("description", act.description)
        act.location_name = replacement.get("locationName", act.location_name)
        if replacement.get("latitude"):
            act.latitude = replacement["latitude"]
        if replacement.get("longitude"):
            act.longitude = replacement["longitude"]
        if replacement.get("estimatedCost"):
            act.estimated_cost_inr = replacement["estimatedCost"]
        db.commit()
    return {"status": "SUCCESS", "activityId": activity_id}


def regenerate_itinerary(db: Session, user_id: str, trip_id: str) -> Dict[str, Any]:
    """Marks the itinerary GENERATING and queues the job (the worker rebuilds it). Rate limiting is the caller's."""
    from task_queue import enqueue_itinerary_generation
    trip = _owned_trip(db, user_id, trip_id)
    trip.itinerary_status = "GENERATING"
    db.commit()
    enqueue_itinerary_generation(trip.id)
    return {"status": "GENERATING", "tripId": trip.id}


# ---------------- saved places (keyed by the user; another user's saved place is never touched)

SAVED_PLACE_FIELDS = ("title", "category", "rating", "location_name", "distance_text", "duration_text",
                      "cost_text", "description")


def _invalidate_saved_cache(user_id: str) -> None:
    try:
        from redis_client import redis_conn
        redis_conn.delete(f"saved_places:{user_id}")
    except Exception as e:
        print(f"[SAVED PLACES CACHE WARN]: {e}", flush=True)


def save_place(db: Session, user_id: str, *, place_id: str, title: str, category: Optional[str] = None,
               rating: Optional[float] = None, location_name: Optional[str] = None,
               distance_text: Optional[str] = None, duration_text: Optional[str] = None,
               cost_text: Optional[str] = None, description: Optional[str] = None) -> Dict[str, Any]:
    from models_db import SavedPlaceModel
    if not user_id or not place_id:
        raise ValueError("place_id is required")
    values = {"title": title, "category": category, "rating": rating, "location_name": location_name or "",
              "distance_text": distance_text, "duration_text": duration_text, "cost_text": cost_text,
              "description": description}
    existing = db.query(SavedPlaceModel).filter(SavedPlaceModel.user_id == user_id,
                                                SavedPlaceModel.place_id == place_id).first()
    if existing:
        for k, v in values.items():
            setattr(existing, k, v)
    else:
        db.add(SavedPlaceModel(id=f"sp_{uuid.uuid4().hex[:12]}", user_id=user_id, place_id=place_id, **values))
    db.commit()
    _invalidate_saved_cache(user_id)
    return {"status": "saved", "place_id": place_id}


def find_saved_place(db: Session, user_id: str, place_id: str):
    from models_db import SavedPlaceModel
    if not user_id or not place_id:
        return None
    return db.query(SavedPlaceModel).filter(SavedPlaceModel.user_id == user_id,
                                            SavedPlaceModel.place_id == place_id).first()


def unsave_place(db: Session, user_id: str, place_id: str) -> Dict[str, Any]:
    """Removes the user's own saved place. `removed` carries its fields (for an Undo), or None if it wasn't saved."""
    from models_db import SavedPlaceModel
    row = find_saved_place(db, user_id, place_id)
    removed = None
    if row is not None:
        removed = {"place_id": row.place_id, **{k: getattr(row, k) for k in SAVED_PLACE_FIELDS}}
        if removed.get("rating") is not None:
            removed["rating"] = float(removed["rating"])
    db.query(SavedPlaceModel).filter(SavedPlaceModel.user_id == user_id, SavedPlaceModel.place_id == place_id).delete()
    db.commit()
    _invalidate_saved_cache(user_id)
    return {"status": "removed", "place_id": place_id, "removed": removed}
