import json
import uuid
import re
from datetime import datetime, timedelta
from typing import Dict, Any, Tuple, List
from sqlalchemy.orm import Session

from models_trip import TripModel
from models_itinerary import ItineraryModel, ItineraryDayModel, ItineraryActivityModel
from schemas_itinerary import GeneratedItinerarySchema
from ai_provider import ai_provider_service
from itinerary_cache_service import build_itinerary_cache_key, get_cached_itinerary, set_cached_itinerary


def calculate_day_date(start_date_str: str, day_number: int) -> str:
    """
    Deterministically derives itinerary day date from trip start_date.
    Example: start_date="2026-10-15", day_number=3 -> "2026-10-17"
    """
    try:
        clean_date_str = start_date_str.split('T')[0]
        base_date = datetime.strptime(clean_date_str, "%Y-%m-%d")
        target_date = base_date + timedelta(days=day_number - 1)
        return target_date.strftime("%Y-%m-%d")
    except Exception:
        return start_date_str

def parse_time_to_minutes(time_str: str) -> int:
    """
    Converts time slots ("09:30 AM", "01:00 PM", "18:00") into minutes from midnight for chronological sorting.
    """
    if not time_str:
        return 0
    
    clean_str = time_str.strip().upper()
    
    match_12 = re.search(r'(\d{1,2}):(\d{2})\s*(AM|PM)', clean_str)
    if match_12:
        hours = int(match_12.group(1))
        minutes = int(match_12.group(2))
        period = match_12.group(3)
        if period == "PM" and hours < 12:
            hours += 12
        elif period == "AM" and hours == 12:
            hours = 0
        return hours * 60 + minutes
    
    match_24 = re.search(r'(\d{1,2}):(\d{2})', clean_str)
    if match_24:
        hours = int(match_24.group(1))
        minutes = int(match_24.group(2))
        return hours * 60 + minutes

    if "MORNING" in clean_str or "BREAKFAST" in clean_str:
        return 9 * 60
    if "LUNCH" in clean_str or "AFTERNOON" in clean_str:
        return 13 * 60
    if "SUNSET" in clean_str or "EVENING" in clean_str:
        return 17 * 60 + 30
    if "NIGHT" in clean_str or "DINNER" in clean_str:
        return 20 * 60

    return 12 * 60

GENERIC_PLACEHOLDERS = {
    "central goa", "old quarter goa", "waterfront goa",
    "central destination", "old quarter destination", "waterfront destination",
    "destination", "central location", "city center"
}

def validate_and_sanitize_itinerary(parsed_schema: GeneratedItinerarySchema, expected_days: int, start_date_str: str) -> Tuple[bool, str]:
    """
    Strict Integrity Validation & Sanitization Pipeline:
    1. Deterministically derives dates from start_date + (day_number - 1).
    2. Ensures exactly expected_days exist.
    3. Ensures dayNumbers are sequential 1..expected_days.
    4. Sorts activities chronologically within each day.
    5. Rejects generic placeholder location names.
    6. Rejects cross-day duplicate activities (same title + location).
    7. Validates coordinate diversity across distinct venues.
    """
    if not parsed_schema.days or len(parsed_schema.days) != expected_days:
        return False, f"Day count mismatch: Expected {expected_days}, got {len(parsed_schema.days) if parsed_schema.days else 0}"

    seen_activity_keys = set()
    coord_map = {}  # (lat, lng) -> set of location names

    for idx, day in enumerate(parsed_schema.days, start=1):
        # 1. Sequential day numbers
        if day.dayNumber != idx:
            return False, f"Non-sequential day number at index {idx}: got {day.dayNumber}"

        # 2. Deterministic Date Override
        day.date = calculate_day_date(start_date_str, day.dayNumber)

        # 3. Chronological Activity Ordering
        day.activities.sort(key=lambda act: parse_time_to_minutes(act.timeSlot))

        if not day.activities:
            return False, f"Day {day.dayNumber} contains no activities"

        for act in day.activities:
            act.isConfirmed = False  # Recommendation boundary rule

            # 4. Check for generic location placeholders
            loc_lower = (act.locationName or "").strip().lower()
            if not loc_lower or loc_lower in GENERIC_PLACEHOLDERS:
                return False, f"Generic or missing location placeholder on Day {day.dayNumber}: '{act.locationName}'"

            # 5. Check cross-day duplicate activities
            norm_key = (act.title.strip().lower(), loc_lower)
            if norm_key in seen_activity_keys:
                return False, f"Duplicate activity detected across days: '{act.title}' at '{act.locationName}'"
            seen_activity_keys.add(norm_key)

            # 6. Coordinate Reuse Detection
            if act.latitude is not None and act.longitude is not None:
                coord_key = (round(act.latitude, 4), round(act.longitude, 4))
                if coord_key not in coord_map:
                    coord_map[coord_key] = set()
                coord_map[coord_key].add(loc_lower)

    # Check if a single coordinate pair is hardcoded for > 2 distinctly named locations
    for coord_key, loc_set in coord_map.items():
        if len(loc_set) > 2:
            return False, f"Coordinate pair {coord_key} hardcoded for multiple distinct locations: {loc_set}"

    return True, "Valid"

def construct_ai_prompt(ai_input: Dict[str, Any]) -> str:
    dest = ai_input.get('destination', {})
    dest_name = dest.get('name', 'India')
    dest_lat = float(dest.get('latitude') or 0.0)
    dest_lng = float(dest.get('longitude') or 0.0)
    total_days = ai_input.get('totalDays', 5)
    start_date = ai_input.get('startDate', '2026-10-15')
    prefs = ai_input.get('preferencesSnapshot', {})
    styles = prefs.get('travelStyles', ['BALANCED'])
    budget = ai_input.get('budget', {}).get('level', 'MODERATE')
    country = dest.get('country', 'India')

    return f"""You are VoyageAI's lead itinerary architect. Generate an authentic, logistically viable {total_days}-day travel itinerary for {dest_name}, {country}.

TRIP PARAMETERS:
- Destination: {dest_name}
- Start Date: {start_date} (YYYY-MM-DD)
- Duration: Exactly {total_days} days
- Group Size: {ai_input.get('travelersCount', 2)} travelers
- Travel Style: {', '.join(styles)}
- Budget Tier: {budget}

OPERATIONAL CONSTRAINTS:
1. DATE ARITHMETIC: Days must strictly sequence from Day 1 ({start_date}) to Day {total_days} with no gaps.
2. LOGISTICAL CLUSTERING: Group activities within each day by geographic proximity to minimize transit time. Never bounce across opposite ends of a city on the same day.
3. PACING & REALISM: Schedule 3 to 4 activities per day (Morning, Lunch/Midday, Afternoon, Evening). Do not overload.
4. SPECIFICITY: Use verified, concrete attraction and establishment names instead of generic placeholders.
5. TEMPORAL CONTINUITY: Activities must follow strict 12-hour chronological order (e.g., "09:00 AM" -> "01:00 PM" -> "04:30 PM" -> "08:00 PM").
6. COORDINATES: Provide accurate, best-known latitude and longitude for the named attraction.
7. FLAGS: Set `bookingRequired: false` and `isConfirmed: false` for all generated options.

Output ONLY a single valid JSON object following this exact structure:
{{
  "title": "{total_days}-Day Curated {dest_name} Itinerary",
  "days": [
    {{
      "dayNumber": 1,
      "date": "{start_date}",
      "title": "Concise theme for Day 1",
      "summary": "1-2 sentence overview of geographic area and experiences covered.",
      "activities": [
        {{
          "timeSlot": "09:30 AM",
          "title": "Specific Attraction or Experience Name",
          "description": "Engaging, practical 1-2 sentence description highlighting key highlights.",
          "activityType": "SIGHTSEEING",
          "locationName": "Real Venue Name, Specific Neighborhood/District",
          "latitude": {dest_lat},
          "longitude": {dest_lng},
          "estimatedCostInr": 250,
          "bookingRequired": false,
          "isConfirmed": false
        }}
      ]
    }}
  ]
}}
"""

def process_async_itinerary_generation(trip_id: str, db_session_factory):
    """
    Background worker function for asynchronous itinerary generation.
    Enforces strict integrity validation and deterministic date calculations.
    Returns the final itinerary status ("READY" or "FAILED"), or None if the trip doesn't exist.
    """
    db: Session = db_session_factory()
    try:
        trip = db.query(TripModel).filter(TripModel.id == trip_id).first()
        if not trip:
            return None

        now = datetime.utcnow().isoformat() + "Z"
        ai_input = {
            "destination": trip.destination,
            "startDate": trip.start_date,
            "endDate": trip.end_date,
            "totalDays": trip.total_days,
            "travelersCount": len(trip.travelers),
            "budget": trip.budget,
            "preferencesSnapshot": trip.preferences_snapshot
        }

        dest_dict = trip.destination if isinstance(trip.destination, dict) else {}
        dest_name = dest_dict.get('name') or str(trip.destination or 'India')
        prefs = trip.preferences_snapshot or {}
        travel_style = ', '.join(prefs.get('travelStyles', ['standard']))
        budget_dict = trip.budget if isinstance(trip.budget, dict) else {}
        pace = budget_dict.get('level', 'moderate')

        cache_key = build_itinerary_cache_key(
            destination=dest_name,
            days=trip.total_days,
            travel_style=travel_style,
            pace=pace
        )

        print(f"\n[TRIP CREATION STEP 1/3] Generating AI itinerary for '{trip.title}' (Destination: {dest_name}, {trip.total_days} Days)", flush=True)

        prompt = construct_ai_prompt(ai_input)
        parsed_schema = None
        is_valid = False
        validation_msg = ""

        # 1. Try to fetch baseline itinerary template from Redis Cache
        cached_base_plan = get_cached_itinerary(cache_key)
        if cached_base_plan:
            print(f">>> [CACHE HIT] Serving baseline itinerary from Redis (~2ms) for key: {cache_key}", flush=True)
            try:
                parsed_schema = GeneratedItinerarySchema.model_validate(cached_base_plan)
                is_valid, validation_msg = validate_and_sanitize_itinerary(parsed_schema, trip.total_days, trip.start_date)
            except Exception as cache_err:
                print(f"[CACHE WARN] Invalid cached schema: {cache_err}. Falling back to fresh generation.", flush=True)
                cached_base_plan = None

        if not cached_base_plan or not is_valid:
            print(f">>> [CACHE MISS] Calling Gemini for {cache_key} (~3-4 seconds)...", flush=True)
            print(f"[TRIP CREATION STEP 2/3] Invoking AI Provider ({ai_provider_service.__class__.__name__})...", flush=True)
            raw_json = ai_provider_service.generate_itinerary_json(ai_input, prompt)

            try:
                parsed_schema = GeneratedItinerarySchema.model_validate_json(raw_json)
                is_valid, validation_msg = validate_and_sanitize_itinerary(parsed_schema, trip.total_days, trip.start_date)
            except Exception as pyd_err:
                validation_msg = f"Schema parsing failed: {pyd_err}"

            # Retry attempt if initial LLM generation was invalid
            import os
            current_provider = os.getenv("AI_PROVIDER", "gemini").lower().strip()
            if not is_valid and current_provider != "mock":
                print(f"[TRIP CREATION WARN] Validation retry triggered: {validation_msg}", flush=True)
                retry_prompt = prompt + f"\n\nIMPORTANT CORRECTION: Your previous JSON response failed validation: {validation_msg}. Please fix this and return a valid JSON itinerary."
                try:
                    raw_json_retry = ai_provider_service.generate_itinerary_json(ai_input, retry_prompt)
                    parsed_schema = GeneratedItinerarySchema.model_validate_json(raw_json_retry)
                    is_valid, validation_msg = validate_and_sanitize_itinerary(parsed_schema, trip.total_days, trip.start_date)
                except Exception as retry_err:
                    validation_msg = f"Retry failed: {retry_err}"

            if not is_valid:
                print(f"[TRIP CREATION FAILED] Integrity check failed: {validation_msg}", flush=True)
                raise ValueError(f"AI_GENERATION_ERROR: {validation_msg}")

            # Store clean baseline template in Redis with 7-Day TTL.
            # Mock output is never cached, or it would be served as real later.
            if current_provider != "mock":
                set_cached_itinerary(cache_key, parsed_schema.model_dump())

        # Copy-on-Write: Clone this baseline plan into PostgreSQL under the user's trip_id


        # 4. Save to Database
        from ai_provider import get_ai_provider
        active_provider_instance = get_ai_provider()
        provider_name = active_provider_instance.__class__.__name__

        print(f"[TRIP CREATION STEP 3/3] Saving itinerary ({len(parsed_schema.days)} Days) to PostgreSQL database...", flush=True)
        itinerary_id = f"itin_{uuid.uuid4().hex[:12]}"
        
        existing_itin = db.query(ItineraryModel).filter(ItineraryModel.trip_id == trip_id).first()
        version = (existing_itin.version + 1) if existing_itin else 1

        if existing_itin:
            db.delete(existing_itin)
            db.commit()

        itin_record = ItineraryModel(
            id=itinerary_id,
            trip_id=trip_id,
            version=version,
            status="READY",
            provider_name=provider_name,
            created_at=now,
            updated_at=now
        )
        db.add(itin_record)
        db.flush()

        total_activities = 0
        for day_data in parsed_schema.days:
            day_id = f"day_{uuid.uuid4().hex[:10]}"
            day_record = ItineraryDayModel(
                id=day_id,
                itinerary_id=itinerary_id,
                day_number=day_data.dayNumber,
                date=day_data.date,
                title=day_data.title,
                summary=day_data.summary
            )
            db.add(day_record)
            db.flush()

            for act_data in day_data.activities:
                total_activities += 1
                act_record = ItineraryActivityModel(
                    id=f"act_{uuid.uuid4().hex[:10]}",
                    day_id=day_id,
                    time_slot=act_data.timeSlot,
                    title=act_data.title,
                    description=act_data.description,
                    activity_type=act_data.activityType,
                    location_name=act_data.locationName,
                    latitude=act_data.latitude,
                    longitude=act_data.longitude,
                    estimated_cost_inr=act_data.estimatedCostInr,
                    booking_required=act_data.bookingRequired,
                    is_confirmed=False
                )
                db.add(act_record)

        trip.itinerary_status = "READY"
        trip.updated_at = now
        db.commit()
        print(f"[TRIP CREATION SUCCESS] Trip '{trip.title}' ready with {len(parsed_schema.days)} Days and {total_activities} Activities!\n", flush=True)
        return "READY"

    except Exception as e:
        db.rollback()
        import traceback
        print(f"[ITINERARY ASYNC WARN] Generation error for trip {trip_id}: {e}", flush=True)
        print(traceback.format_exc(), flush=True)
        try:
            trip = db.query(TripModel).filter(TripModel.id == trip_id).first()
            if trip:
                trip.itinerary_status = "FAILED"
                db.commit()
        except Exception:
            pass
        return "FAILED"
    finally:
        db.close()

def optimize_day_flow_service(db: Session, trip_id: str, day_id: str, goal: str = "MINIMIZE_TRAVEL_TIME") -> Dict[str, Any]:
    day = (
        db.query(ItineraryDayModel)
        .join(ItineraryModel, ItineraryModel.id == ItineraryDayModel.itinerary_id)
        .filter(ItineraryDayModel.id == day_id, ItineraryModel.trip_id == trip_id)
        .first()
    )
    if not day:
        raise ValueError("Target itinerary day not found")

    activities = db.query(ItineraryActivityModel).filter(ItineraryActivityModel.day_id == day_id).all()
    if not activities:
        return {"status": "SUCCESS", "message": "No activities to optimize", "dayId": day_id, "activities": []}

    act_dicts = []
    for a in activities:
        act_dicts.append({
            "id": a.id,
            "timeSlot": a.time_slot,
            "title": a.title,
            "description": a.description,
            "locationName": a.location_name,
            "latitude": a.latitude,
            "longitude": a.longitude,
            "estimatedCostInr": a.estimated_cost_inr
        })

    day_info = {"dayNumber": day.day_number, "date": day.date, "title": day.title}
    optimized_list = ai_provider_service.generate_day_optimization(day_info, act_dicts, goal)

    for item in optimized_list:
        # The AI returns activity IDs; only accept ones from this day.
        act_rec = db.query(ItineraryActivityModel).filter(
            ItineraryActivityModel.id == item.get("id"), ItineraryActivityModel.day_id == day_id
        ).first()
        if act_rec:
            if item.get("timeSlot"):
                act_rec.time_slot = item["timeSlot"]
            if item.get("title"):
                act_rec.title = item["title"]

    db.commit()

    updated_acts = db.query(ItineraryActivityModel).filter(ItineraryActivityModel.day_id == day_id).all()
    result_activities = [
        {
            "id": a.id,
            "timeSlot": a.time_slot,
            "title": a.title,
            "description": a.description,
            "locationName": a.location_name,
            "latitude": a.latitude,
            "longitude": a.longitude,
            "estimatedCostInr": a.estimated_cost_inr
        }
        for a in updated_acts
    ]

    return {
        "status": "SUCCESS",
        "message": f"Day {day.day_number} itinerary optimized for {goal}",
        "dayId": day_id,
        "activities": result_activities
    }

def optimize_budget_service(db: Session, trip_id: str) -> Dict[str, Any]:
    trip = db.query(TripModel).filter(TripModel.id == trip_id).first()
    if not trip:
        raise ValueError("Trip not found")

    itin = db.query(ItineraryModel).filter(ItineraryModel.trip_id == trip_id).first()
    if not itin:
        raise ValueError("Itinerary not found for trip")

    days = db.query(ItineraryDayModel).filter(ItineraryDayModel.itinerary_id == itin.id).all()
    all_activities = []
    total_act_cost = 0

    for d in days:
        acts = db.query(ItineraryActivityModel).filter(ItineraryActivityModel.day_id == d.id).all()
        for a in acts:
            total_act_cost += (a.estimated_cost_inr or 0)
            all_activities.append({
                "id": a.id,
                "dayId": d.id,
                "timeSlot": a.time_slot,
                "title": a.title,
                "locationName": a.location_name,
                "estimatedCostInr": a.estimated_cost_inr,
                "latitude": a.latitude,
                "longitude": a.longitude
            })

    trip_budget = trip.budget or {"targetAmount": 30000}
    current_costs = {"totalProjected": total_act_cost}

    return ai_provider_service.generate_budget_optimization(trip_budget, current_costs, all_activities)

def weather_replan_service(db: Session, trip_id: str, forecast_override: Dict[str, Any] = None) -> Dict[str, Any]:
    trip = db.query(TripModel).filter(TripModel.id == trip_id).first()
    if not trip:
        raise ValueError("Trip not found")

    itin = db.query(ItineraryModel).filter(ItineraryModel.trip_id == trip_id).first()
    if not itin:
        raise ValueError("Itinerary not found for trip")

    forecast = forecast_override or {
        "condition": "Monsoon Heavy Downpour & Thunderstorm",
        "temp": 28,
        "icon": "Rain"
    }

    days = db.query(ItineraryDayModel).filter(ItineraryDayModel.itinerary_id == itin.id).all()
    all_activities = []
    for d in days:
        acts = db.query(ItineraryActivityModel).filter(ItineraryActivityModel.day_id == d.id).all()
        for a in acts:
            all_activities.append({
                "id": a.id,
                "dayId": d.id,
                "timeSlot": a.time_slot,
                "title": a.title,
                "description": a.description,
                "locationName": a.location_name,
                "latitude": a.latitude,
                "longitude": a.longitude,
                "estimatedCostInr": a.estimated_cost_inr
            })

    return ai_provider_service.generate_weather_replan(forecast, all_activities)

def execute_refinement_actions_service(db: Session, trip_id: str, actions: List[Dict[str, Any]]) -> Dict[str, Any]:
    trip = db.query(TripModel).filter(TripModel.id == trip_id).first()
    if not trip:
        raise ValueError("Trip not found")

    trip_activity_ids = {
        row[0]
        for row in db.query(ItineraryActivityModel.id)
        .join(ItineraryDayModel, ItineraryDayModel.id == ItineraryActivityModel.day_id)
        .join(ItineraryModel, ItineraryModel.id == ItineraryDayModel.itinerary_id)
        .filter(ItineraryModel.trip_id == trip.id)
        .all()
    }

    executed_count = 0
    for act in actions:
        act_type = act.get("type") or act.get("action")
        activity_id = act.get("activityId")
        if activity_id not in trip_activity_ids:
            continue

        if act_type == "REPLACE_ACTIVITY" and activity_id:
            rep = act.get("replacement") or {}
            target_act = db.query(ItineraryActivityModel).filter(ItineraryActivityModel.id == activity_id).first()
            if target_act:
                if rep.get("name"):
                    target_act.title = rep["name"]
                if rep.get("description"):
                    target_act.description = rep["description"]
                if rep.get("timeSlot"):
                    target_act.time_slot = rep["timeSlot"]
                if rep.get("locationName"):
                    target_act.location_name = rep["locationName"]
                if rep.get("latitude") is not None:
                    target_act.latitude = rep["latitude"]
                if rep.get("longitude") is not None:
                    target_act.longitude = rep["longitude"]
                if rep.get("estimatedCost") is not None:
                    target_act.estimated_cost_inr = rep["estimatedCost"]
                executed_count += 1

        elif act_type == "REMOVE_ACTIVITY" and activity_id:
            db.query(ItineraryActivityModel).filter(ItineraryActivityModel.id == activity_id).delete()
            executed_count += 1

    db.commit()
    print(f"[REFINEMENT EXECUTED] Applied {executed_count} database mutations for trip {trip_id}", flush=True)
    return {
        "status": "SUCCESS",
        "message": f"Successfully applied {executed_count} itinerary refinements to PostgreSQL",
        "executedCount": executed_count
    }

