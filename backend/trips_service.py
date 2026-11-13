import os
import json
import requests
from typing import Dict, Any, Optional
from dotenv import load_dotenv
from fastapi import HTTPException
from redis_client import redis_conn

# Load environment variables
load_dotenv(override=True)

SPOTLIGHT_CACHE_TTL = 172800  # 48 hours (172,800 seconds)
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
                return json.loads(cached)
        except Exception as e:
            print(f"[REDIS READ ERROR] {e}", flush=True)

    print(f"[LLM GEN] Generating live dynamic content for {clean_dest} via the AI provider (Lat: {lat}, Lng: {lng}, Key: {cache_key})...", flush=True)


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
      "photos": ["https://images.unsplash.com/photo-1599661046289-e31897846e41?auto=format&fit=crop&w=600&q=80"],
      "description": "Authentic description of what to see and experience here."
    }}
  ],
  "events": [
    {{
      "id": "evt_1",
      "title": "Specific regional festival, live show, or cultural gathering",
      "date": "Upcoming Date / Season",
      "time": "06:00 PM onwards",
      "price": 250,
      "location": "Exact venue or area, {clean_dest}",
      "category": "Festival | Music | Culture",
      "tag": "Live Experience",
      "image": "https://images.unsplash.com/photo-1514525253161-7a46d19cd819?auto=format&fit=crop&w=600&q=80",
      "description": "Short vivid description of the event vibe."
    }}
  ]
}}
Provide 5 diverse real activities and 2 real events. Replace [{lat}, {lng}] with actual lat/lng coordinates of each place in or near {clean_dest}.
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
      "photos": ["https://images.unsplash.com/photo-1599661046289-e31897846e41?auto=format&fit=crop&w=600&q=80"],
      "description": "Authentic description of what to see and experience here."
    }}
  ],
  "events": [
    {{
      "id": "evt_1",
      "title": "Specific regional festival, live show, or cultural gathering",
      "date": "Upcoming Date / Season",
      "time": "06:00 PM onwards",
      "price": 250,
      "location": "Exact venue or area, {clean_dest}",
      "category": "Festival | Music | Culture",
      "tag": "Live Experience",
      "image": "https://images.unsplash.com/photo-1514525253161-7a46d19cd819?auto=format&fit=crop&w=600&q=80",
      "description": "Short vivid description of the event vibe."
    }}
  ]
}}
Provide 5 diverse real activities and 2 real events. Replace [26.9124, 75.7873] with actual lat/lng coordinates of each place in {clean_dest}.
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

    # 2. Store genuine result in Redis (48 hours TTL = 172800 seconds)
    if redis_conn:
        try:
            redis_conn.setex(cache_key, SPOTLIGHT_CACHE_TTL, json.dumps(parsed_data))
            print(f">>> [REDIS SPOTLIGHT CACHED] Saved genuine key: {cache_key} (48h TTL)", flush=True)
        except Exception as e:
            print(f"[REDIS SAVE ERROR] {e}", flush=True)

    return parsed_data

# Alias for backward compatibility
def get_destination_spotlight(dest_name: str, redis_client=None) -> Dict[str, Any]:
    return generate_live_destination_highlights(dest_name)
