"""
VoyageAI - Google Maps Platform Backend Proxy Service
Replaces unreliable Overpass / Nominatim APIs with Google Places API (New) & Google Geocoding.
Includes a Redis caching layer with an in-memory fallback
to conserve API quota and eliminate synthetic mock fallbacks.
"""

import os
import json
import time
import math
from typing import List, Dict, Any, Optional
import httpx
from dotenv import load_dotenv
from starlette.concurrency import run_in_threadpool
from redis_client import redis_conn

# Ensure environment variables are loaded
load_dotenv()

GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY") or os.getenv("GOOGLE_MAP_DEMO_KEY") or ""

# In-memory LRU/TTL cache fallback when Redis is offline
_in_memory_cache: Dict[str, tuple[float, Any]] = {}

def _get_in_memory(key: str) -> Optional[Any]:
    entry = _in_memory_cache.get(key)
    if entry:
        expires_at, val = entry
        if time.time() < expires_at:
            return val
        del _in_memory_cache[key]
    return None

def _set_in_memory(key: str, val: Any, ttl_seconds: int):
    _in_memory_cache[key] = (time.time() + ttl_seconds, val)
    # Prune expired if cache gets large
    if len(_in_memory_cache) > 1000:
        now = time.time()
        for k in list(_in_memory_cache.keys()):
            if _in_memory_cache[k][0] < now:
                del _in_memory_cache[k]


class RedisCacheManager:
    """Reuse the thread-safe Redis pool across the API and highlights event loops."""

    async def get(self, key: str) -> Optional[Any]:
        try:
            data = await run_in_threadpool(redis_conn.get, key)
            if data:
                return json.loads(data)
        except Exception:
            pass
        return _get_in_memory(key)

    async def set(self, key: str, value: Any, ttl_seconds: int = 3600):
        try:
            await run_in_threadpool(redis_conn.set, key, json.dumps(value), ex=ttl_seconds)
        except Exception:
            pass
        _set_in_memory(key, value, ttl_seconds)


cache = RedisCacheManager()


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate great-circle distance between two points on Earth in meters."""
    R = 6371000.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2.0) ** 2
    )
    return 2.0 * R * math.asin(math.sqrt(a))


# Table A types supported by Places API (New) searchNearby
DEFAULT_NEARBY_TYPES = [
    "tourist_attraction",
    "museum",
    "historical_landmark",
    "park",
    "monument",
    "art_gallery",
    "cultural_center",
    "restaurant",
    "cafe",
    "lodging",
    "hotel",
    "hindu_temple",
]


async def reverse_geocode(lat: float, lng: float) -> Dict[str, Any]:
    """
    Reverse geocodes (lat, lng) coordinates to a formatted address, city, state, country.
    Uses Google Geocoding API or Google Places API (New) addressComponents, caching results for 24 hours.
    NEVER returns 'Madhubani' unless the coordinates are actually in Madhubani district.
    """
    cache_key = f"geo:reverse:{round(lat, 3)}:{round(lng, 3)}"
    cached_val = await cache.get(cache_key)
    if cached_val:
        return cached_val

    result = {
        "formatted_address": f"{round(lat, 4)}, {round(lng, 4)}",
        "city": "Current Location",
        "state": None,
        "country": "India",
        "source": "google"
    }

    # 1. Attempt Google Geocoding API
    if GOOGLE_MAPS_API_KEY:
        try:
            url = f"https://maps.googleapis.com/maps/api/geocode/json?latlng={lat},{lng}&key={GOOGLE_MAPS_API_KEY}"
            async with httpx.AsyncClient(timeout=4.0) as client:
                res = await client.get(url)
                if res.status_code == 200:
                    data = res.json()
                    status = data.get("status")
                    if status == "OK" and data.get("results"):
                        first = data["results"][0]
                        result["formatted_address"] = first.get("formatted_address", "")
                        for comp in first.get("address_components", []):
                            types = comp.get("types", [])
                            if "locality" in types:
                                result["city"] = comp.get("long_name")
                            elif "administrative_area_level_2" in types and result["city"] == "Current Location":
                                result["city"] = comp.get("long_name")
                            elif "administrative_area_level_1" in types:
                                result["state"] = comp.get("long_name")
                            elif "country" in types:
                                result["country"] = comp.get("long_name")
                        await cache.set(cache_key, result, ttl_seconds=86400)
                        return result
        except Exception as e:
            print(f"[REVERSE GEOCODE GOOGLE ERR] {e}", flush=True)

    # 2. Resilient Fallback: Google Places API (New) reverse address lookup
    if GOOGLE_MAPS_API_KEY and (result["city"] == "Current Location" or not result.get("formatted_address")):
        try:
            places_url = "https://places.googleapis.com/v1/places:searchNearby"
            headers = {
                "Content-Type": "application/json",
                "X-Goog-Api-Key": GOOGLE_MAPS_API_KEY,
                "X-Goog-FieldMask": "places.id,places.formattedAddress,places.displayName,places.addressComponents"
            }
            payload = {
                "maxResultCount": 1,
                "locationRestriction": {
                    "circle": {
                        "center": {"latitude": lat, "longitude": lng},
                        "radius": 1000.0
                    }
                }
            }
            async with httpx.AsyncClient(timeout=4.0) as client:
                res = await client.post(places_url, headers=headers, json=payload)
                if res.status_code == 200:
                    places = res.json().get("places", [])
                    if places:
                        p = places[0]
                        result["formatted_address"] = p.get("formattedAddress", "")
                        for comp in p.get("addressComponents", []):
                            types = comp.get("types", [])
                            if "locality" in types:
                                result["city"] = comp.get("longText")
                            elif "administrative_area_level_2" in types and result["city"] == "Current Location":
                                result["city"] = comp.get("longText")
                            elif "administrative_area_level_1" in types:
                                result["state"] = comp.get("longText")
                            elif "country" in types:
                                result["country"] = comp.get("longText")
                        if result["city"] != "Current Location":
                            await cache.set(cache_key, result, ttl_seconds=86400)
                            return result
        except Exception as e:
            print(f"[PLACES REVERSE GEOCODE ERR] {e}", flush=True)

    # 3. Final Clean Fallback (Never returns hardcoded Madhubani)
    await cache.set(cache_key, result, ttl_seconds=3600)
    return result


async def search_nearby_places(
    lat: float,
    lng: float,
    radius: int = 5000,
    place_types: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """
    Search nearby places using Google Places API (New) searchNearby.
    Caches results in Redis for 2 hours with key places:nearby:{lat}:{lng}:{radius}.
    Outputs formatted schema with is_mock=False.
    """
    # Clamp radius between 500m and 50000m
    clamped_radius = max(500, min(int(radius or 5000), 50000))
    type_tag = "_".join(sorted(place_types)) if place_types else "all"
    cache_key = f"places:nearby:{round(lat, 3)}:{round(lng, 3)}:{clamped_radius}:{type_tag}"
    cached_places = await cache.get(cache_key)
    if cached_places is not None and isinstance(cached_places, list):
        return cached_places

    if not GOOGLE_MAPS_API_KEY:
        print("[GOOGLE PLACES] No API key configured. Returning empty list.", flush=True)
        return []

    url = "https://places.googleapis.com/v1/places:searchNearby"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_MAPS_API_KEY,
        "X-Goog-FieldMask": (
            "places.id,places.displayName,places.formattedAddress,places.location,"
            "places.rating,places.userRatingCount,places.primaryType,places.editorialSummary"
        ),
    }

    types_to_include = place_types or DEFAULT_NEARBY_TYPES
    # Exclude any types that cause 400 Bad Request
    safe_types = [t for t in types_to_include if t not in ["point_of_interest", "establishment"]]

    payload = {
        "includedTypes": safe_types,
        "maxResultCount": 15,
        "locationRestriction": {
            "circle": {
                "center": {"latitude": lat, "longitude": lng},
                "radius": float(clamped_radius),
            }
        },
    }

    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            res = await client.post(url, headers=headers, json=payload)
            if res.status_code == 200:
                data = res.json()
                raw_places = data.get("places", [])
                transformed: List[Dict[str, Any]] = []

                for place in raw_places:
                    loc = place.get("location", {})
                    p_lat = loc.get("latitude")
                    p_lng = loc.get("longitude")
                    if p_lat is None or p_lng is None:
                        continue

                    dist_m = round(haversine_meters(lat, lng, p_lat, p_lng))
                    primary_type = place.get("primaryType") or "attraction"
                    category_name = primary_type.replace("_", " ").title()

                    name = place.get("displayName", {}).get("text")
                    if not name:
                        continue  # never invent a name
                    address = place.get("formattedAddress", "")
                    # Only Google's own summary; no invented description.
                    summary = place.get("editorialSummary", {}).get("text", "")

                    # None when Google has no rating; the app then shows no stars.
                    rating = place.get("rating")
                    if rating is not None:
                        rating = round(float(rating), 1)

                    transformed.append({
                        "id": place.get("id"),
                        "name": name,
                        "title": name,
                        "category": category_name,
                        "latitude": p_lat,
                        "longitude": p_lng,
                        "rating": rating,
                        "userRatingCount": place.get("userRatingCount", 0),
                        "distanceMeters": dist_m,
                        "address": address,
                        "description": summary,
                        "is_mock": False,
                        "_isMock": False,
                    })

                # Sort by distance
                transformed.sort(key=lambda x: x["distanceMeters"])

                # Cache in Redis with 2-hour TTL
                await cache.set(cache_key, transformed, ttl_seconds=7200)
                return transformed
            else:
                print(f"[GOOGLE PLACES ERROR] Status: {res.status_code} Body: {res.text[:300]}", flush=True)
    except Exception as e:
        print(f"[GOOGLE PLACES EXCEPTION] {e}", flush=True)

    return []


async def autocomplete_places(
    query: str,
    lat: Optional[float] = None,
    lng: Optional[float] = None
) -> List[Dict[str, Any]]:
    """
    Search suggestions using Google Places API (New) autocomplete.
    Caches results in Redis for 1 hour.
    """
    if not query or len(query.strip()) < 2:
        return []

    clean_q = query.strip()
    cache_key = f"places:autocomplete:{clean_q.lower()}:{round(lat, 2) if lat else 'none'}:{round(lng, 2) if lng else 'none'}"
    cached_val = await cache.get(cache_key)
    if cached_val is not None:
        return cached_val

    if not GOOGLE_MAPS_API_KEY:
        return []

    url = "https://places.googleapis.com/v1/places:autocomplete"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_MAPS_API_KEY,
    }

    payload: Dict[str, Any] = {
        "input": clean_q,
        "includedRegionCodes": ["in"],
    }

    if lat is not None and lng is not None:
        payload["locationBias"] = {
            "circle": {
                "center": {"latitude": lat, "longitude": lng},
                "radius": 50000.0,
            }
        }

    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            res = await client.post(url, headers=headers, json=payload)
            if res.status_code == 200:
                data = res.json()
                suggestions = data.get("suggestions", [])
                results: List[Dict[str, Any]] = []

                for s in suggestions:
                    pred = s.get("placePrediction", {})
                    place_id = pred.get("placeId")
                    if not place_id:
                        continue

                    structured = pred.get("structuredFormat", {})
                    main_text = structured.get("mainText", {}).get("text", "")
                    secondary_text = structured.get("secondaryText", {}).get("text", "")
                    full_text = pred.get("text", {}).get("text", "")

                    results.append({
                        "id": place_id,
                        "placeId": place_id,
                        "name": main_text or full_text,
                        "displayName": full_text or main_text,
                        "city": secondary_text,
                        "description": full_text,
                    })

                await cache.set(cache_key, results, ttl_seconds=3600)
                return results
            else:
                print(f"[GOOGLE AUTOCOMPLETE ERROR] Status: {res.status_code} Body: {res.text[:300]}", flush=True)
    except Exception as e:
        print(f"[GOOGLE AUTOCOMPLETE EXCEPTION] {e}", flush=True)

    return []


async def get_place_details(place_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve exact latitude, longitude, and address for a Google Place ID.
    Caches for 24 hours.
    """
    if not place_id or not GOOGLE_MAPS_API_KEY:
        return None

    cache_key = f"places:detail:{place_id}"
    cached_val = await cache.get(cache_key)
    if cached_val is not None:
        return cached_val

    url = f"https://places.googleapis.com/v1/places/{place_id}"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_MAPS_API_KEY,
        "X-Goog-FieldMask": "id,displayName,formattedAddress,location,addressComponents",
    }

    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            res = await client.get(url, headers=headers)
            if res.status_code == 200:
                data = res.json()
                loc = data.get("location", {})
                detail = {
                    "id": data.get("id"),
                    "name": data.get("displayName", {}).get("text", ""),
                    "address": data.get("formattedAddress", ""),
                    "latitude": loc.get("latitude"),
                    "longitude": loc.get("longitude"),
                }
                await cache.set(cache_key, detail, ttl_seconds=86400)
                return detail
    except Exception as e:
        print(f"[GOOGLE PLACE DETAIL EXCEPTION] {e}", flush=True)

    return None
