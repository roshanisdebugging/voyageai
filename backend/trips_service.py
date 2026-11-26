import os
import re
import json
import requests
from datetime import date
from typing import Any, Dict, List, Optional, Tuple
from dotenv import load_dotenv
from fastapi import HTTPException
from redis_client import redis_conn

# Load environment variables
load_dotenv(override=True)

SPOTLIGHT_CACHE_TTL = 172800  # 48 hours (172,800 seconds)
# Events: the CODE decides what is still upcoming (the model is only asked for dates). An event is kept only with
# a real start_date/end_date (YYYY-MM-DD), end_date >= today (India date), and a start at most this many days ahead.
EVENT_MAX_DAYS_AHEAD = 180
_ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _today_ist() -> date:
    from trip_lifecycle import today_ist
    return today_ist()


def _iso_day(value: Any) -> Optional[date]:
    """YYYY-MM-DD only (no times, no '14 Nov', no 'February'); None for anything else."""
    if not isinstance(value, str) or not _ISO_DAY.match(value.strip()):
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def filter_upcoming_events(events: Any, today: Optional[date] = None) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """
    The one rule for events, used after generation and on every cache read:
    - no readable start_date (or an end_date before it): dropped as undated;
    - end_date (= start_date when missing) before today: dropped as past (an event already under way is kept);
    - start_date more than EVENT_MAX_DAYS_AHEAD days ahead: dropped as far;
    - the rest sorted by start_date; each kept event's display `date` becomes its checked start_date.
    Returns (kept, counts) with counts raw / kept / dropped_past / dropped_undated / dropped_far.
    """
    today = today or _today_ist()
    items = [e for e in events if isinstance(e, dict)] if isinstance(events, list) else []
    counts = {"raw": len(items), "kept": 0, "dropped_past": 0, "dropped_undated": 0, "dropped_far": 0}
    kept = []
    for ev in items:
        start = _iso_day(ev.get("start_date", ev.get("startDate")))
        end_raw = ev.get("end_date", ev.get("endDate"))
        end = start if end_raw in (None, "") else _iso_day(end_raw)
        if start is None or end is None or end < start:
            counts["dropped_undated"] += 1
        elif end < today:
            counts["dropped_past"] += 1
        elif (start - today).days > EVENT_MAX_DAYS_AHEAD:
            counts["dropped_far"] += 1
        else:
            kept.append((start, {**ev, "start_date": start.isoformat(), "end_date": end.isoformat(), "date": start.isoformat()}))
    kept.sort(key=lambda pair: pair[0])
    counts["kept"] = len(kept)
    return [ev for _, ev in kept], counts


def _apply_event_filter(data: Dict[str, Any], city: str) -> Dict[str, Any]:
    """Filters data["events"] in place and logs one line (counts only)."""
    data["events"], c = filter_upcoming_events(data.get("events"))
    print(f"[EVENTS] city={city} raw={c['raw']} kept={c['kept']} dropped_past={c['dropped_past']} "
          f"dropped_undated={c['dropped_undated']} dropped_far={c['dropped_far']}", flush=True)
    return data
GENERIC_LOCATION_NAMES = {"local area", "current area", "live gps", "nearby", "current location", "location", "active position", "undefined", "null"}

class HighlightsUnavailable(RuntimeError):
    """Live highlights could not be generated. Never replaced with made-up data."""


def generate_live_destination_highlights(
    destination: Optional[str] = None,
    lat: Optional[float] = None,
    lng: Optional[float] = None
) -> Dict[str, Any]:
    """
    Generates authentic, real-world destination highlights via Gemini LLM.
    Uses dynamic hierarchy: Lat/Lng -> Local -> District -> State cascade ONLY when destination is unresolved/generic.
    When an explicit destination (e.g. "Jaipur") is specified, targets that exact destination.
    """
    from geo_utils import resolve_administrative_hierarchy

    raw_dest = (destination or "").strip()
    is_generic = not raw_dest or raw_dest.lower() in GENERIC_LOCATION_NAMES or len(raw_dest) <= 2

    hierarchy = {"local": None, "district": None, "state": None, "country": "India"}

    if not is_generic:
        clean_dest = raw_dest.title()
        cache_key = f"cache:spotlight:{clean_dest.lower().replace(' ', '_')}"
        use_coords_prompt = False
    else:
        if lat is not None and lng is not None:
            hierarchy = resolve_administrative_hierarchy(lat, lng)

        local_name = hierarchy.get("local") or hierarchy.get("district") or hierarchy.get("state")
        if local_name:
            clean_dest = local_name.title()
        elif lat is not None and lng is not None:
            clean_dest = "Surrounding Region"
        else:
            clean_dest = "Madhubani"

        state_name = hierarchy.get("state") or "regional"
        if lat is not None and lng is not None:
            cache_key = f"cache:spotlight:geo:{state_name.lower().replace(' ', '_')}:{round(lat, 2)}_{round(lng, 2)}"
        else:
            cache_key = f"cache:spotlight:{clean_dest.lower().replace(' ', '_')}"
        use_coords_prompt = (lat is not None and lng is not None)

    # 1. Check Redis Cache
    if redis_conn:
        try:
            cached = redis_conn.get(cache_key)
            if cached:
                if isinstance(cached, bytes):
                    cached = cached.decode("utf-8")
                print(f"[CACHE HIT] Loaded genuine data for {clean_dest} (Key: {cache_key})", flush=True)
                # The cache holds text only (older entries may still carry model-made URLs: dropped here).
                data = _apply_event_filter(strip_model_images(json.loads(cached)), clean_dest)
                return attach_highlight_images(data, clean_dest)
        except Exception as e:
            print(f"[REDIS READ ERROR] {e}", flush=True)

    print(f"[LLM GEN] Generating live dynamic content for {clean_dest} via the AI provider (Lat: {lat}, Lng: {lng}, Key: {cache_key})...", flush=True)


    today_iso = _today_ist().isoformat()
    if use_coords_prompt:
        prompt = f"""
You are an expert travel guide. 
The traveler is located at coordinates latitude: {lat}, longitude: {lng} in India (State/Region: {hierarchy.get('state') or 'Surrounding Area'}, Nearest Town: {clean_dest}).
Identify the closest real town, district, or cultural area within a 10 to 25 km radius.
Provide genuine activities, authentic landmarks, and local specialties for this specific surrounding region.
DO NOT invent fake places or return international templates.

Return strictly valid JSON matching this exact schema:
{{
  "destination": "{clean_dest}",
  "region": "{hierarchy.get('state') or 'Surrounding Region'}",
  "overview": "2 punchy, evocative sentences about {clean_dest}'s culture, vibe, and landscape.",
  "activities": [
    {{
      "id": "act_1",
      "title": "Exact Landmark or Activity Name",
      "category": "Sights | Food | Culture | Adventure",
      "tag": "Must Visit | Heritage | Culinary",
      "cost": 500,
      "duration": "2 hours",
      "location": "Specific street or neighborhood, {clean_dest}",
      "coordinates": [{lat}, {lng}],
      "description": "Authentic description of what to see and experience here."
    }}
  ],
  "events": [
    {{
      "id": "evt_1",
      "title": "Specific regional festival, live show, or cultural gathering",
      "start_date": "YYYY-MM-DD",
      "end_date": "YYYY-MM-DD",
      "time": "06:00 PM onwards",
      "price": 250,
      "location": "Exact venue or area, {clean_dest}",
      "coordinates": null,
      "category": "Festival | Music | Culture",
      "tag": "Live Experience",
      "description": "Short vivid description of the event vibe."
    }}
  ]
}}
For events: today is {today_iso} (India). Give "start_date" and "end_date" as YYYY-MM-DD (end_date equals start_date for
a one-day event), only for events that end today or later and start within the next 6 months. If you do not know an event's real
date, leave the event out; an empty "events" list is fine. Never repeat a past year's event.
Provide 5 diverse real activities and up to 2 real events. Replace [{lat}, {lng}] with actual lat/lng coordinates of each place in or near {clean_dest}.
For events, "coordinates" is the venue's actual [lat, lng]; keep null when the venue is not known.
"""
    else:
        prompt = f"""
You are an elite travel concierge. Generate an authentic, hyper-accurate travel guide for {clean_dest}.
DO NOT use generic place names like 'Top Landmarks Walk' or fake static coordinates.
Use REAL, ICONIC landmarks, local specialty restaurants, and authentic upcoming festivals/events for {clean_dest}.
Ensure the latitude and longitude coordinates accurately match the real geographic locations in {clean_dest}.

Return strictly valid JSON matching this exact schema:
{{
  "destination": "{clean_dest}",
  "overview": "2 punchy, evocative sentences about {clean_dest}'s culture, vibe, and landscape.",
  "activities": [
    {{
      "id": "act_1",
      "title": "Exact Landmark or Activity Name",
      "category": "Sights | Food | Culture | Adventure",
      "tag": "Must Visit | Heritage | Culinary",
      "cost": 500,
      "duration": "2 hours",
      "location": "Specific street or neighborhood, {clean_dest}",
      "coordinates": [26.9124, 75.7873],
      "description": "Authentic description of what to see and experience here."
    }}
  ],
  "events": [
    {{
      "id": "evt_1",
      "title": "Specific regional festival, live show, or cultural gathering",
      "start_date": "YYYY-MM-DD",
      "end_date": "YYYY-MM-DD",
      "time": "06:00 PM onwards",
      "price": 250,
      "location": "Exact venue or area, {clean_dest}",
      "coordinates": null,
      "category": "Festival | Music | Culture",
      "tag": "Live Experience",
      "description": "Short vivid description of the event vibe."
    }}
  ]
}}
For events: today is {today_iso} (India). Give "start_date" and "end_date" as YYYY-MM-DD (end_date equals start_date for
a one-day event), only for events that end today or later and start within the next 6 months. If you do not know an event's real
date, leave the event out; an empty "events" list is fine. Never repeat a past year's event.
Provide 5 diverse real activities and up to 2 real events. Replace [26.9124, 75.7873] with actual lat/lng coordinates of each place in {clean_dest}.
For events, "coordinates" is the venue's actual [lat, lng]; keep null when the venue is not known.
"""

    parsed_data = None
    try:
        from ai_provider import complete_json
        parsed_data = json.loads(complete_json(prompt, temperature=0.3, timeout=15))
        print(f">>> [AI SUCCESS] Generated live content for {clean_dest}", flush=True)
    except Exception as gen_err:
        print(f"[AI ERROR] Highlights generation failed for {clean_dest}: {gen_err}", flush=True)

    if not parsed_data or not isinstance(parsed_data, dict):
        print(f"[HIGHLIGHTS FETCH FAILED]: LLM generation failed or returned invalid payload for {clean_dest}", flush=True)
        # No made-up spots: the caller returns 503 and the app shows nothing for this section.
        raise HighlightsUnavailable(f"No live highlights for {clean_dest}")

    # Standardize data keys
    parsed_data["destination"] = parsed_data.get("destination", clean_dest)
    parsed_data["region"] = parsed_data.get("region", hierarchy.get("state") or "")
    parsed_data["overview"] = parsed_data.get("overview", f"Discover top attractions and local culture in {clean_dest}.")
    parsed_data["activities"] = parsed_data.get("activities", parsed_data.get("famous_activities", []))
    parsed_data["events"] = parsed_data.get("events", parsed_data.get("upcoming_events", []))
    strip_model_images(parsed_data)   # the model is no longer asked for pictures; drop any URL it still returns
    _apply_event_filter(parsed_data, clean_dest)   # the code, not the model, decides what is still upcoming

    # 2. Store genuine result in Redis (48 hours TTL = 172800 seconds)
    if redis_conn:
        try:
            redis_conn.setex(cache_key, SPOTLIGHT_CACHE_TTL, json.dumps(parsed_data))   # text only: no pictures yet
            print(f">>> [REDIS SPOTLIGHT CACHED] Saved genuine key: {cache_key} (48h TTL)", flush=True)
        except Exception as e:
            print(f"[REDIS SAVE ERROR] {e}", flush=True)

    return attach_highlight_images(parsed_data, clean_dest)


# Picture fields the model must never fill: they are set server-side by attach_highlight_images.
MODEL_IMAGE_FIELDS = ("photos", "image", "images", "photo", "imageUrl", "image_url", "thumbnail",
                      "photoCredit", "photoCreditUrl", "photoSource", "placeId")


def strip_model_images(data: Dict[str, Any]) -> Dict[str, Any]:
    """Removes every picture field from activities and events (in place) and returns data."""
    for key in ("activities", "events"):
        items = data.get(key)
        if not isinstance(items, list):
            data[key] = []
            continue
        data[key] = [it for it in items if isinstance(it, dict)]
        for it in data[key]:
            for field in MODEL_IMAGE_FIELDS:
                it.pop(field, None)
    return data


def _coords_of(item: Dict[str, Any]):
    c = item.get("coordinates")
    if isinstance(c, (list, tuple)) and len(c) == 2:
        return c[0], c[1]
    return item.get("lat") or item.get("latitude"), item.get("lng") or item.get("longitude")


def attach_highlight_images(data: Dict[str, Any], destination: str) -> Dict[str, Any]:
    """
    Real pictures (image_service: Google only if GOOGLE_IMAGES_ENABLED, then Wikipedia, then Pexels for broad categories) for up to 7 items:
    activities first, then events. Activities get photos=[url] or [], events image=url or None, both with
    photoCredit / photoCreditUrl / photoSource. Image trouble never fails the highlights.
    """
    activities, events = data.get("activities") or [], data.get("events") or []
    for act in activities:
        act["photos"], act["photoCredit"], act["photoCreditUrl"], act["photoSource"] = [], None, None, None
    for evt in events:
        evt["image"], evt["photoCredit"], evt["photoCreditUrl"], evt["photoSource"] = None, None, None, None
    try:
        import image_service
        targets = [("act", a) for a in activities] + [("evt", e) for e in events]
        targets = targets[:image_service.MAX_LOOKUPS]
        requests_ = []
        for kind, it in targets:
            lat, lng = _coords_of(it)
            title = it.get("title") or it.get("name") or ""
            requests_.append({"title": title, "destination": data.get("destination") or destination,
                              "lat": lat, "lng": lng, "category": it.get("category")})
        found = image_service.resolve_many(requests_)
        for (kind, it), img in zip(targets, found):
            if not img:
                continue
            if kind == "act":
                it["photos"] = [img["url"]]
            else:
                it["image"] = img["url"]
            it["photoCredit"], it["photoCreditUrl"], it["photoSource"] = img.get("credit"), img.get("credit_url"), img["source"]
            if img.get("place_id"):
                it["placeId"] = img["place_id"]
    except Exception as e:
        print(f"[IMAGES] highlights pictures skipped: {type(e).__name__}", flush=True)
    return data

# Alias for backward compatibility
def get_destination_spotlight(dest_name: str, redis_client=None) -> Dict[str, Any]:
    return generate_live_destination_highlights(dest_name)
