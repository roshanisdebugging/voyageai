import difflib
import json
import math
import re
import time
from dataclasses import dataclass, field
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

# ---------------- place search (Google only): one function for voice, the map search box and trip destinations

MAX_SUGGESTIONS = 6          # autocomplete suggestions resolved with Place Details (unchanged: 1 + up to 6 calls)
MAX_CHOICES = 3              # an ambiguous search offers at most 3 places
DUPLICATE_RADIUS_M = 300     # same name this close = the same place

# Tier 3: what a traveller usually means. Landmarks, and real places/addresses (city, area, road, the premise
# itself) are equal: Google's own order decides between them (its #1 for "Golden Temple" is typed 'premise', for
# "Marine Drive" 'route'). Only shops, stations, hotels and unknown establishments are pushed below them.
LANDMARK_TYPES = {
    "tourist_attraction", "historical_landmark", "historical_place", "monument", "museum", "place_of_worship",
    "hindu_temple", "mosque", "church", "synagogue", "buddhist_temple", "sikh_temple", "gurudwara", "park",
    "national_park", "state_park", "zoo", "aquarium", "beach", "art_gallery", "cultural_landmark", "cultural_center",
    "botanical_garden", "garden", "amusement_park", "observation_deck", "plaza", "natural_feature", "castle",
    "fort", "palace", "wildlife_park", "wildlife_refuge", "hiking_area", "lake", "island", "scenic_spot",
}
GEO_TYPES = {
    "locality", "sublocality", "sublocality_level_1", "neighborhood", "administrative_area_level_1",
    "administrative_area_level_2", "administrative_area_level_3", "colloquial_area", "country", "postal_town",
    "archipelago", "route", "premise", "street_address", "intersection", "sublocality_level_2",
}
# Tier 0: shops and services. Never picked by default.
SHOP_TYPES = {
    "service", "manufacturer", "wholesaler", "beauty_salon", "hair_salon", "hair_care", "laundry", "car_repair",
    "car_dealer", "real_estate_agency", "insurance_agency", "finance", "accounting", "lawyer", "electrician",
    "plumber", "painter", "locksmith", "moving_company", "storage", "courier_service", "travel_agency",
}
# Types that say nothing about what the place is (an address or a generic establishment).
GENERIC_TYPES = {
    "point_of_interest", "establishment", "geocode", "subpremise", "plus_code", "political",
    "association_or_organization",
}
DIGIT_WORDS = {"1": "ek", "2": "do", "3": "teen", "4": "char", "5": "paanch", "6": "chhe", "7": "saat", "8": "aath",
               "9": "nau"}


def in_india(lat: Any, lng: Any) -> bool:
    """Same box as the frontend's isInIndia()."""
    try:
        return 6.0 <= float(lat) <= 37.5 and 68.0 <= float(lng) <= 97.5
    except (TypeError, ValueError):
        return False


def place_tier(types: Optional[List[str]]) -> Optional[int]:
    """3 landmark or real place/address, 2 another known kind (restaurant, hotel, station), 1 only generic types
    (could be anything), 0 shop/service. None when Google sent no types at all (treated like 2)."""
    if not types:
        return None
    ts = set(types)
    if ts & LANDMARK_TYPES or ts & GEO_TYPES:
        return 3
    if "store" in ts or ts & SHOP_TYPES or any(t.endswith("_store") or t.endswith("_shop") for t in ts):
        return 0
    if ts - GENERIC_TYPES:
        return 2
    return 1


def place_kind(types: Optional[List[str]]) -> str:
    """landmark | area (city, area, road, address) | place | unknown | shop. For the UI/logs only."""
    tier = place_tier(types)
    if tier == 3:
        return "landmark" if set(types or []) & LANDMARK_TYPES else "area"
    return {2: "place", 1: "unknown", 0: "shop"}.get(tier, "place")


def _norm_name(s: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", (s or "").lower()).split())


def name_score(query: str, name: str) -> float:
    """How well a result's name matches what was asked, 0..1. '4 minar' also reads as 'char minar' (speech-to-text
    writes the Hindi number as a digit). Used only to re-rank within a tier and to spot close calls."""
    q, n = _norm_name(query), _norm_name(name)
    if not q or not n:
        return 0.0
    variants = {q, " ".join(DIGIT_WORDS.get(w, w) for w in q.split())}
    best = 0.0
    for v in variants:
        for a, b in ((v, n), (v.replace(" ", ""), n.replace(" ", ""))):
            if a == b:
                return 1.0
            best = max(best, difflib.SequenceMatcher(None, a, b).ratio())
            if len(a) >= 4 and (a in b or b in a):
                best = max(best, 0.85)
    return best


@dataclass
class PlaceSearch:
    results: List[Dict[str, Any]] = field(default_factory=list)   # ranked, India only
    ambiguous: bool = False                                        # ask the user instead of picking results[0]
    choices: List[Dict[str, Any]] = field(default_factory=list)    # up to 3 when ambiguous
    unavailable: bool = False                                      # Google quota reached / key paused
    google_calls: Optional[int] = 0                                # real Google requests (cache hits not counted)


class MapSearchUnavailable(Exception):
    """Google quota reached or the demo key is paused. Show "Map search isn't available right now"."""

    def __init__(self, google_calls: int = 0):
        super().__init__("map search unavailable")
        self.google_calls = google_calls


class PlaceResults(list):
    """search_places() result: a plain list of places (JSON as before) that also carries the ranking verdict."""
    ambiguous: bool = False
    choices: List[Dict[str, Any]] = []
    google_calls: int = 0


MAP_SEARCH_UNAVAILABLE_MESSAGE = "Map search isn't available right now. Please try again later."


def rank_places(query: str, results: List[Dict[str, Any]]) -> PlaceSearch:
    """Landmarks and real places first, then other known places, then unknowns, shops last; within a tier a
    near-exact name match goes first, otherwise Google's order is kept. Never invents or drops a real result
    (except ones outside India)."""
    india = [r for r in results if r.get("latitude") is not None and in_india(r.get("latitude"), r.get("longitude"))]
    scored = []
    for i, r in enumerate(india):
        tier = place_tier(r.get("types"))
        score = name_score(query, r.get("name") or "")
        r["kind"] = place_kind(r.get("types"))
        scored.append((-(2 if tier is None else tier), 0 if score >= 0.9 else 1, i, score, tier, r))
    scored.sort(key=lambda x: x[:3])
    # One place often comes back several times (the landmark, its address, its area) a few metres apart.
    # Keep only the best-ranked of results with the same name within DUPLICATE_RADIUS_M, before judging ambiguity.
    kept = []
    for x in scored:
        r = x[5]
        name = _norm_name(r.get("name") or "")
        if any(_norm_name(k[5].get("name") or "") == name
               and haversine_meters(float(r["latitude"]), float(r["longitude"]),
                                    float(k[5]["latitude"]), float(k[5]["longitude"])) <= DUPLICATE_RADIUS_M
               for k in kept):
            continue
        kept.append(x)
    scored = kept
    ranked = [x[5] for x in scored]
    out = PlaceSearch(results=ranked)
    if not scored:
        return out
    top_score, top_tier = scored[0][3], scored[0][4]
    if top_tier is not None and top_tier <= 1:
        # The best match is a shop or an unknown establishment/address: never pick it by default.
        out.ambiguous = True
    elif len(scored) > 1 and top_tier == 3 and scored[1][4] == 3 and top_score < 0.9:
        # Several landmarks/places and none is clearly what was said ("Varanasi ghat").
        out.ambiguous = True
    if out.ambiguous:
        out.choices = ranked[:MAX_CHOICES]
    return out


def search_places_detailed(query: str) -> PlaceSearch:
    """
    THE place search (Google Places Autocomplete (New) + Place Details (New), nothing else): 1 autocomplete call
    plus up to 6 detail calls, each cached. Used by voice look-ups, the map search box and trip destination search.
    On a Google quota/paused error it stops at once (no retry, no other provider) and sets unavailable=True.
    Logs the Google call count only (never the query or the key).
    """
    if not query or len(query.strip()) < 2:
        return PlaceSearch()

    clean_query = query.strip()
    started = time.perf_counter()
    from services.google_maps_service import (GoogleCallCounter, GoogleQuotaError, autocomplete_places,
                                              get_place_details, is_paused)
    counter = GoogleCallCounter()

    async def _google_resolve():
        if await is_paused("autocomplete", "details"):   # a quota error earlier today: no request at all
            raise GoogleQuotaError("paused")
        suggs = await autocomplete_places(clean_query, counter=counter)
        if not suggs:
            return []
        suggs = [s for s in suggs[:MAX_SUGGESTIONS] if s.get("placeId")]
        details = await asyncio.gather(*[get_place_details(s["placeId"], counter=counter) for s in suggs],
                                       return_exceptions=True)
        if any(isinstance(d, GoogleQuotaError) for d in details):
            raise GoogleQuotaError("details")
        results = []
        for s, d in zip(suggs, details):
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
                    "display_name": s.get("displayName") or d.get("address") or s.get("name"),
                    "types": list(s.get("types") or []),   # from autocomplete (no extra call, no extra field)
                })
        return results

    out = PlaceSearch()
    try:
        out = rank_places(clean_query, _run_sync(_google_resolve()))
    except GoogleQuotaError:
        out = PlaceSearch(unavailable=True)
    except Exception as e:
        print(f"[GOOGLE SEARCH PLACES ERR] {type(e).__name__}", flush=True)
    out.google_calls = counter.count
    print(f"[PLACES SEARCH] google_calls={out.google_calls} results={len(out.results)} ambiguous={out.ambiguous} "
          f"unavailable={out.unavailable} ms={int((time.perf_counter() - started) * 1000)}", flush=True)
    return out


def search_places(query: str) -> PlaceResults:
    """Ranked India-only results of search_places_detailed, for the map search box, trip destination search
    and voice look-ups. Raises MapSearchUnavailable when Google's quota is reached or the key is paused."""
    found = search_places_detailed(query)
    if found.unavailable:
        raise MapSearchUnavailable(found.google_calls)
    out = PlaceResults(found.results)
    out.ambiguous, out.choices, out.google_calls = found.ambiguous, list(found.choices), found.google_calls
    return out

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