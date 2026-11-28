"""
Shared trip creation and serialization.

REST (POST /api/trips) and the WebSocket action trips:create both call
create_trip_for_user, so validation, limits and queueing behave the same way.
The voice agent's create_trip tool must call it too.
"""
import json
import unicodedata
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Optional

from sqlalchemy.orm import Session

from media_service import media_service
from models import AuthUser, UserPreferences, UserProfile
from models_place import CityModel, city_to_dict, get_or_create_city
from models_trip import TripModel
from places import validate_destination_payload
from task_queue import enqueue_itinerary_generation, publish_trip_event

MAX_TRIP_DAYS = 30
MAX_TRAVELERS = 20
MIN_BUDGET_INR = 1000
MAX_BUDGET_INR = 10_000_000
ORIGIN_MAX_CHARS = 60      # a starting city's name: letters, spaces and common punctuation only
_PLACE_NAME_PUNCT = set(" .,'-()&/")

# Budget level from rupees per person per day. A child counts as half a person.
# The level is never shown to the user; it only steers the itinerary prompt and cache.
BUDGET_LEVEL_THRESHOLDS = [
    (2500, "BUDGET"),
    (6000, "MODERATE"),
    (12000, "PREMIUM"),
]


# "Today" for trip dates is the India date (IST has no daylight saving, so a fixed offset is exact).
IST = timezone(timedelta(hours=5, minutes=30))
# Trips in these states are closed (set to COMPLETED) once their end date has passed.
OPEN_TRIP_STATUSES = {"PLANNING", "UPCOMING", "ACTIVE", "CONFIRMED"}


def today_ist() -> date:
    return datetime.now(IST).date()


def close_finished_trips(db: Session, trips: Iterable[TripModel]) -> int:
    """
    Marks open trips whose end date is before today (IST) as COMPLETED and saves it.
    Called whenever trips are read, so no scheduled job is needed.
    Cancelled and archived trips are left alone. Returns how many were closed.
    """
    today = today_ist()
    closed = 0
    for trip in trips:
        if (trip.status or "PLANNING").upper() not in OPEN_TRIP_STATUSES:
            continue
        try:
            end = date.fromisoformat(str(trip.end_date)[:10])
        except ValueError:
            continue
        if end < today:
            trip.status = "COMPLETED"
            closed += 1
    if closed:
        db.commit()
    return closed


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
        "purposeType": getattr(trip, "purpose_type", None),
        "purposeText": getattr(trip, "purpose_text", None),
        "baseArea": getattr(trip, "base_area", None),
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
    today = today_ist()
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


def clean_place_name(raw: Any, max_chars: int = ORIGIN_MAX_CHARS) -> Optional[str]:
    """A city name as said or typed -> trimmed name, or None when it isn't a place name: 2..max_chars characters,
    only letters (any script, with their vowel signs), spaces and . , ' - ( ) & /, at least one letter, no digits."""
    if raw is None or isinstance(raw, (bool, int, float)):
        return None
    name = " ".join(str(raw).split())
    if not 2 <= len(name) <= max_chars:
        return None
    has_letter = False
    for ch in name:
        kind = unicodedata.category(ch)[0]
        if kind == "L":
            has_letter = True
        elif kind != "M" and ch not in _PLACE_NAME_PUNCT:
            return None
    return name if has_letter else None


def _parse_origin(raw: Any) -> Optional[Dict[str, Any]]:
    """The optional starting city: a checked place whose name passes clean_place_name."""
    if not raw:
        return None
    place = _parse_place(raw, "Starting city")
    name = clean_place_name(place.get("name"))
    if name is None:
        raise TripValidationError(f"Starting city: use a city name of at most {ORIGIN_MAX_CHARS} letters.")
    return {**place, "name": name}


def _parse_purpose(trip_data: Dict[str, Any], destination: Dict[str, Any]) -> tuple:
    """The optional purpose (purposeType, purposeText) and base area (baseArea): checked like the origin. Text and
    area are kept only for business / event / other; leisure, pilgrimage and no purpose store none (planned as today).
    Older clients send none of these: (None, None, None)."""
    from trip_purpose import PURPOSE_TEXT_MAX, PURPOSE_TYPES, base_area_ok, clean_purpose_text, is_focused
    ptype = trip_data.get("purposeType")
    if ptype in (None, ""):
        return None, None, None
    if ptype not in PURPOSE_TYPES:
        raise TripValidationError("Purpose: choose one of the listed options.")
    if not is_focused(ptype):
        return ptype, None, None
    raw_text = trip_data.get("purposeText")
    text = None
    if raw_text not in (None, ""):
        text = clean_purpose_text(raw_text)
        if text is None:
            raise TripValidationError(f"Purpose: one line of at most {PURPOSE_TEXT_MAX} letters, digits and common punctuation.")
    area = None
    raw_area = trip_data.get("baseArea")
    if raw_area:
        place = _parse_place(raw_area, "Base area")
        name = clean_place_name(place.get("name"))
        if name is None or not base_area_ok(place, destination):
            raise TripValidationError(f"Base area: choose a place near {destination.get('name') or 'the destination'}.")
        area = {"id": place.get("id"), "name": name, "city": place.get("city"), "region": place.get("region"),
                "latitude": float(place["latitude"]), "longitude": float(place["longitude"])}
    return ptype, text, area


def _parse_budget_amount(raw: Any) -> Optional[int]:
    if raw in (None, ""):
        return None
    amount = _parse_int(raw, "Budget amount")
    if not MIN_BUDGET_INR <= amount <= MAX_BUDGET_INR:
        raise TripValidationError(f"Budget must be between ₹{MIN_BUDGET_INR:,} and ₹{MAX_BUDGET_INR:,}.")
    return amount


def _plan_card_meta(card_id, destination) -> Optional[Dict[str, Any]]:
    """What the trip keeps of a checked plan (no migration: stored in preferences_snapshot_json).
    None when no card was asked for, it no longer exists, or it does not fit the destination."""
    if not card_id or not isinstance(card_id, str):
        return None
    import pilgrimage
    card = pilgrimage.get_card(card_id)
    if card is None or not pilgrimage.card_fits_destination(card, destination):
        reason = "card_missing" if card is None else "destination_changed"
        print(f"[PILGRIMAGE] card not used card={str(card_id)[:80]} reason={reason}", flush=True)
        return None
    return {
        "id": card.id,
        "version": card.version,
        "status": card.status,
        "lastVerified": card.last_verified.isoformat() if card.last_verified else None,
        "nameEn": card.name_en,
        "nameHi": card.name_hi,
        "bookingNotes": [{"text": n.text, "officialUrl": n.official_url} for n in card.booking_notes],
    }


def _build_from_card_now(db: Session, trip: TripModel, card_id: str, total_days: int) -> bool:
    """A checked-plan trip that needs no AI day (same or fewer days than the card): build the itinerary from the
    card right here (Google look-ups only) and queue no job. False: the worker builds it (card days + AI days),
    or, if this build fails, the worker retries from the card."""
    import pilgrimage
    card = pilgrimage.get_card(card_id)
    if card is None or pilgrimage.plan_days(card, total_days).extra_days:
        return False
    try:
        from plan_card_itinerary import generate
        generate(trip, db, card)
    except Exception as err:
        db.rollback()
        print(f"[PILGRIMAGE] build at creation failed trip={trip.id} card={card.id} error={type(err).__name__}; queued", flush=True)
        return False
    publish_trip_event(trip.id, "READY")
    return True


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

    origin = _parse_origin(trip_data.get("origin"))
    purpose_type, purpose_text, base_area = _parse_purpose(trip_data, destination)
    origin_city = get_or_create_city(db, origin) if origin else None

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

    # A checked plan (pilgrimage card) chosen by voice: kept only if it still names this destination.
    plan_card = _plan_card_meta(trip_data.get("planCardId"), destination)
    if plan_card:
        pref_snapshot["planCard"] = plan_card

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
        purpose_type=purpose_type,
        purpose_text=purpose_text,
        base_area_json=json.dumps(base_area) if base_area else None,
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
    print(f"[TRIP DRAFT] trip={trip.id} origin_set={'true' if origin_city else 'false'} purpose={purpose_type or 'none'} "
          f"area_set={'true' if base_area else 'false'} source=create", flush=True)

    if plan_card and _build_from_card_now(db, trip, plan_card["id"], total_days):
        return serialize_trip(trip, db)   # no AI needed: built from the card, no itinerary job queued
    enqueue_itinerary_generation(trip.id)
    return serialize_trip(trip, db)
