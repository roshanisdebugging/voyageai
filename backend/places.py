import json
import math
from typing import List, Dict, Any, Tuple, Optional
import asyncio

def _run_sync(coro):
    """
    Safely execute an async coroutine in both sync and running-loop contexts.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(lambda: asyncio.run(coro)).result()
    else:
        return asyncio.run(coro)

def search_places(query: str) -> List[Dict[str, Any]]:
    """
    Search destinations/places exclusively using Google Places Autocomplete + Place Details.
    Zero OpenStreetMap or Nominatim dependencies.
    """
    if not query or len(query.strip()) < 2:
        return []

    clean_query = query.strip()
    try:
        from services.google_maps_service import autocomplete_places, get_place_details

        async def _google_resolve():
            suggs = await autocomplete_places(clean_query)
            if not suggs:
                return []
            tasks = [get_place_details(s["placeId"]) for s in suggs[:6] if s.get("placeId")]
            details = await asyncio.gather(*tasks, return_exceptions=True)
            results = []
            for s, d in zip(suggs[:6], details):
                if isinstance(d, dict) and d.get("latitude") is not None and d.get("longitude") is not None:
                    results.append({
                        "id": s.get("placeId") or d.get("id"),
                        "place_id": s.get("placeId") or d.get("id"),
                        "name": s.get("name") or d.get("name") or clean_query,
                        "city": s.get("city") or d.get("name"),
                        "region": s.get("city"),
                        "country": "India",
                        "latitude": d["latitude"],
                        "longitude": d["longitude"],
                        "displayName": s.get("displayName") or d.get("address") or s.get("name"),
                        "display_name": s.get("displayName") or d.get("address") or s.get("name")
                    })
            return results

        return _run_sync(_google_resolve())
    except Exception as e:
        print(f"[GOOGLE SEARCH PLACES ERR] {e}", flush=True)
        return []

class GeocoderProvider:
    def search(self, query: str) -> List[Dict[str, Any]]:
        return search_places(query)

# Compatibility instance routed exclusively through Google Maps
geocoder_service = GeocoderProvider()

def search_nearby_restaurants(query: str, lat: float = None, lon: float = None) -> List[Dict[str, Any]]:
    """
    Dynamically search for real restaurants & dining spots around query or (lat, lon) in India
    exclusively via Google Places API (New).
    """
    # Without coordinates there is nothing honest to search around (it used to default to Delhi).
    if lat is None or lon is None:
        return []
    eff_lat, eff_lon = float(lat), float(lon)
    try:
        from services.google_maps_service import search_nearby_places
        places = _run_sync(search_nearby_places(eff_lat, eff_lon, radius=5000, place_types=["restaurant", "cafe", "fast_food_restaurant"]))
        if query and query.strip():
            q_clean = query.strip().lower()
            filtered = [
                p for p in places 
                if q_clean in p.get("name", "").lower() or q_clean in (p.get("address") or "").lower()
            ]
            return filtered if filtered else places
        return places
    except Exception as e:
        print(f"[GOOGLE RESTAURANTS ERR] {e}", flush=True)
        return []

def validate_destination_payload(dest: Dict[str, Any]) -> Tuple[bool, str]:
    if not isinstance(dest, dict):
        return False, "Destination must be an object"

    name = dest.get("name")
    if not name or not isinstance(name, str) or len(name.strip()) < 2:
        return False, "Destination must include a valid name (at least 2 characters)"

    country = (dest.get("country") or "").strip().lower()
    if country and country not in ("india", "in"):
        return False, "Cruiser currently supports destinations within India only. Please select a destination within India."

    lat = dest.get("latitude")
    lon = dest.get("longitude")

    if lat is None or lon is None:
        return False, "Destination must include latitude and longitude"

    try:
        lat_f = float(lat)
        lon_f = float(lon)
        if not (-90.0 <= lat_f <= 90.0):
            return False, "Latitude must be between -90 and 90"
        if not (-180.0 <= lon_f <= 180.0):
            return False, "Longitude must be between -180 and 180"

        # India bounding box validation: ~6° N to 37.5° N, ~68° E to 97.5° E
        if not (6.0 <= lat_f <= 37.5 and 68.0 <= lon_f <= 97.5):
            return False, "Cruiser currently supports destinations within India only. Please select a location within India."

    except (ValueError, TypeError):
        return False, "Latitude and Longitude must be valid numbers"

    return True, "Valid"

def search_local_amenities(query: str, lat: float, lon: float, radius_km: float = 15.0) -> List[Dict[str, Any]]:
    """
    Search for POIs/amenities strictly bounded around coordinates via Google Places API (New).
    """
    if not query or len(query.strip()) < 2:
        return []

    from services.google_maps_service import search_nearby_places
    clean_q = query.strip().lower()
    radius_m = int(radius_km * 1000)
    try:
        places = _run_sync(search_nearby_places(lat, lon, radius=radius_m))
        matched = [
            p for p in places
            if clean_q in p.get("name", "").lower()
            or clean_q in p.get("category", "").lower()
            or clean_q in (p.get("address") or "").lower()
        ]
        return matched if matched else places[:10]
    except Exception as e:
        print(f"[GOOGLE LOCAL AMENITIES ERR] {e}", flush=True)
        return []

def get_destination_highlights(destination: str) -> Dict[str, Any]:
    from trips_service import generate_live_destination_highlights
    return generate_live_destination_highlights(destination)

def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371000.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def get_progressive_nearby_places(
    lat: float, 
    lng: float, 
    radius: Any = 5000, 
    category: Optional[str] = "all", 
    **kwargs
) -> List[Dict[str, Any]]:
    """
    Exclusively calls Google Places API (New) search_nearby_places.
    Overpass API and synthetic mocks are completely eradicated.
    Returns real places with authentic ratings, coords, and is_mock=False.
    """
    from services.google_maps_service import search_nearby_places

    if isinstance(radius, str):
        category = radius
        radius = 5000
    try:
        radius_val = int(radius)
    except (ValueError, TypeError):
        radius_val = 5000

    place_types = None
    if category and category.lower() != "all":
        cat_l = category.lower()
        if "pharmacy" in cat_l:
            place_types = ["pharmacy", "drugstore"]
        elif "hospital" in cat_l or "medical" in cat_l:
            place_types = ["hospital", "doctor"]
        elif "food" in cat_l or "restaurant" in cat_l:
            place_types = ["restaurant", "cafe"]
        elif "hotel" in cat_l or "stay" in cat_l:
            place_types = ["lodging", "hotel"]
        elif "atm" in cat_l or "bank" in cat_l:
            place_types = ["atm", "bank"]
        elif "police" in cat_l:
            place_types = ["police"]
        elif "sight" in cat_l or "attraction" in cat_l or "monument" in cat_l:
            place_types = ["tourist_attraction", "museum", "historical_landmark", "monument"]

    try:
        return _run_sync(search_nearby_places(lat, lng, radius_val, place_types=place_types))
    except Exception as e:
        print(f"[GOOGLE NEARBY PLACES ERR] {e}", flush=True)
        return []