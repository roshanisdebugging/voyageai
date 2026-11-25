"""
VoyageAI - Google Maps Platform backend service: Places API (New), Geocoding API v4.
Google only (no other provider, no fallback to one). Redis cache with an in-memory fallback; quota/pause
detection (gmaps:paused:{key fingerprint}:{api}, see pause_key); never invents a place.
"""

import re
import json
import time
import math
import hashlib
import threading
from typing import List, Dict, Any, Optional, Tuple
import httpx
from dotenv import load_dotenv
from starlette.concurrency import run_in_threadpool
from redis_client import redis_conn

# Ensure environment variables are loaded
load_dotenv()

from services.maps_keys import resolve_server_key, server_key_source  # noqa: E402

# The server key (GOOGLE_MAPS_SERVER_KEY; the old names still work for one release, with a warning).
GOOGLE_MAPS_SERVER_KEY = resolve_server_key()


def key_fingerprint(key: str) -> str:
    """First 8 hex characters of SHA-256 of the key ('' without one): tells keys apart, never reveals any part of one."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:8] if key else ""


KEY_SOURCE = server_key_source()                             # the variable NAME, for the startup line
KEY_FINGERPRINT = key_fingerprint(GOOGLE_MAPS_SERVER_KEY)

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


def _redis_ttl(conn: Any, key: str) -> Optional[int]:
    """Seconds left (-1: no expiry), None when the key doesn't exist."""
    ttl = int(conn.ttl(key))
    return None if ttl == -2 else ttl


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

    async def ttl_left(self, key: str) -> Optional[int]:
        """Seconds left on a key (-1: no expiry), None when it isn't there. Redis decides; this process's own copy
        is used only while Redis can't be reached (so a flag cleared in Redis is gone for the running server too)."""
        try:
            return await run_in_threadpool(_redis_ttl, redis_conn, key)
        except Exception:
            entry = _in_memory_cache.get(key)
            left = entry[0] - time.time() if entry else 0
            return max(1, int(left)) if left > 0 else None


cache = RedisCacheManager()


class GoogleQuotaError(Exception):
    """Google refused the call because a quota/daily limit was reached or the (demo) key is paused.
    Callers stop at once: no retry, no further Google call for that request."""


class GoogleCallCounter:
    """Counts real Google HTTP requests (cache hits are not counted). For logs only."""

    def __init__(self) -> None:
        self.count = 0

    def add(self) -> None:
        self.count += 1


def _count(counter: Optional[GoogleCallCounter]) -> None:
    if counter is not None:
        counter.add()


QUOTA_STATUSES = {"RESOURCE_EXHAUSTED", "OVER_QUERY_LIMIT", "OVER_DAILY_LIMIT"}
QUOTA_WORDS = ("quota", "limit", "paused", "exhausted")


def is_quota_error(res: Any) -> bool:
    """HTTP 429, or a 403/200 whose Google status says a quota/daily limit was hit or the key is paused."""
    status = getattr(res, "status_code", None)
    if status == 429:
        return True
    if status not in (200, 403):
        return False
    try:
        body = res.json()
    except Exception:
        return False
    if not isinstance(body, dict):
        return False
    err = body.get("error")
    if isinstance(err, dict):
        g_status = str(err.get("status") or "")
        message = str(err.get("message") or "").lower()
        return g_status in QUOTA_STATUSES or (g_status == "PERMISSION_DENIED" and any(w in message for w in QUOTA_WORDS))
    return str(body.get("status") or "") in QUOTA_STATUSES   # Geocoding v3-style body


PER_MINUTE_PAUSE_S = 60


def _is_daily(res: Any) -> bool:
    """A daily limit (the demo key's 'GetPlaceRequest per day' = 100) or a paused key, as opposed to a per-minute one."""
    try:
        err = res.json().get("error") or {}
        text = str(err.get("message") or "").lower()
        for d in err.get("details") or []:
            text += " " + str((d.get("metadata") or {}).get("quota_limit") or "").lower()
    except Exception:
        return True
    return "per day" in text or "perday" in text or "daily" in text or "paused" in text or "minute" not in text


def _seconds_to_google_reset() -> int:
    """Google resets daily quotas at midnight Pacific time."""
    from datetime import datetime, timedelta, timezone
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/Los_Angeles")
    except Exception:
        tz = timezone(timedelta(hours=-8))   # no tz database: PST (at most one hour late in summer)
    now = datetime.now(tz)
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(60, int((midnight - now).total_seconds()) + 60)


def pause_seconds(res: Any) -> int:
    """How long to skip an API after this quota error: until Google's reset, or 60 s for a per-minute limit."""
    return _seconds_to_google_reset() if _is_daily(res) else PER_MINUTE_PAUSE_S


# ---- Pause flags. The quota belongs to the key, so the flag does too: a new key never inherits an old key's pause.
# pause_key is the ONE place that builds the name. The older unscoped names (gmaps:paused:{api}) are ignored.

PAUSE_PREFIX = "gmaps:paused:"
SKIP_LOG_EVERY_S = 60
_skip_log_lock = threading.Lock()
_skip_logged_at: Dict[str, float] = {}


def pause_key(api: str) -> str:
    return f"{PAUSE_PREFIX}{KEY_FINGERPRINT}:{api}"


def _ttl_text(ttl: int) -> str:
    return f"{ttl}s" if ttl >= 0 else "no expiry"


def log_paused_skip(api: str, ttl: int) -> None:
    """A request was skipped because of a pause flag: one line per API per minute (per process)."""
    now = time.monotonic()
    with _skip_log_lock:
        last = _skip_logged_at.get(api)
        if last is not None and now - last < SKIP_LOG_EVERY_S:
            return
        _skip_logged_at[api] = now
    print(f"[GOOGLE QUOTA] {api} request skipped: paused, {_ttl_text(ttl)} left (fp={KEY_FINGERPRINT or 'none'})", flush=True)


async def mark_paused(api: str, res: Any) -> None:
    """After a quota error, skip this API (no request at all) until Google's reset, or 60 s for a per-minute limit."""
    ttl = pause_seconds(res)
    await cache.set(pause_key(api), True, ttl_seconds=ttl)
    print(f"[GOOGLE QUOTA] {api} paused for {ttl} s", flush=True)


async def is_paused(*apis: str) -> bool:
    for api in apis:
        ttl = await cache.ttl_left(pause_key(api))
        if ttl is not None:
            log_paused_skip(api, ttl)
            return True
    return False


def is_paused_sync(conn: Any, api: str) -> bool:
    """is_paused for code without an event loop (image_service), on its own Redis client. Redis down: not paused."""
    try:
        ttl = _redis_ttl(conn, pause_key(api))
    except Exception:
        return False
    if ttl is None:
        return False
    log_paused_skip(api, ttl)
    return True


def mark_paused_sync(conn: Any, api: str, res: Any) -> int:
    """mark_paused for code without an event loop. Returns the seconds."""
    ttl = pause_seconds(res)
    try:
        conn.set(pause_key(api), json.dumps(True), ex=ttl)
    except Exception:
        pass
    return ttl


def active_pauses(conn: Any = None) -> List[Tuple[str, int]]:
    """[(api, seconds left)] for the CURRENT key only. Raises when Redis can't be reached."""
    conn = conn or redis_conn
    if not KEY_FINGERPRINT:
        return []
    prefix, out = pause_key(""), []
    for name in conn.scan_iter(prefix + "*"):
        ttl = _redis_ttl(conn, name)
        if ttl is not None:
            out.append((name[len(prefix):], ttl))
    return sorted(out)


def clear_pauses(conn: Any = None) -> List[str]:
    """Deletes the CURRENT key's pause flags and nothing else. Returns the API names."""
    conn = conn or redis_conn
    apis = [api for api, _ in active_pauses(conn)]
    for api in apis:
        conn.delete(pause_key(api))
        _in_memory_cache.pop(pause_key(api), None)
    return apis


def status_line(conn: Any = None) -> str:
    """The startup line: variable name, fingerprint and active pauses. Never the key, never a flag's value."""
    if not KEY_FINGERPRINT:
        return "[MAPS] no server key set: Google Maps calls are off"
    try:
        paused = ", ".join(f"{api}:{_ttl_text(ttl)}" for api, ttl in active_pauses(conn))
    except Exception:
        paused = "unknown, Redis not reachable"
    return f"[MAPS] server key from {KEY_SOURCE} fp={KEY_FINGERPRINT} paused=[{paused}]"


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


GEOCODE_V4_URL = "https://geocode.googleapis.com/v4/geocode/location/{lat},{lng}"
GEOCODE_V4_FIELDS = "results.formattedAddress,results.addressComponents"


def _apply_components(result: Dict[str, Any], components: List[Dict[str, Any]]) -> None:
    """Places (New) / Geocoding v4 addressComponents ({longText, types}) -> city/state/country."""
    for comp in components or []:
        types = comp.get("types", [])
        if "locality" in types:
            result["city"] = comp.get("longText")
        elif "administrative_area_level_2" in types and result["city"] == "Current Location":
            result["city"] = comp.get("longText")
        elif "administrative_area_level_1" in types:
            result["state"] = comp.get("longText")
        elif "country" in types:
            result["country"] = comp.get("longText")


async def reverse_geocode(lat: float, lng: float) -> Dict[str, Any]:
    """
    Reverse geocodes (lat, lng) coordinates to a formatted address, city, state, country.
    Uses Google Geocoding API v4 (the version the Maps demo key supports; v3 is refused with REQUEST_DENIED),
    then Google Places API (New) addressComponents if v4 has no city. Cached 24 hours.
    On a quota/paused error nothing else is called.
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

    if await is_paused("geocode"):
        return result
    # 1. Google Geocoding API v4 (reverse)
    if GOOGLE_MAPS_SERVER_KEY:
        try:
            url = GEOCODE_V4_URL.format(lat=float(lat), lng=float(lng))
            headers = {"X-Goog-Api-Key": GOOGLE_MAPS_SERVER_KEY, "X-Goog-FieldMask": GEOCODE_V4_FIELDS}
            async with httpx.AsyncClient(timeout=4.0) as client:
                res = await client.get(url, headers=headers)
            if is_quota_error(res):
                await mark_paused("geocode", res)
                print("[REVERSE GEOCODE] Google quota/paused; nothing else called", flush=True)
                return result   # not cached: the key comes back the next day
            if res.status_code == 200:
                results = res.json().get("results") or []
                if results:
                    result["formatted_address"] = results[0].get("formattedAddress") or result["formatted_address"]
                    # The first result can be a plus code or a street; the city is in the first one that has it.
                    for r in results:
                        _apply_components(result, r.get("addressComponents") or [])
                        if result["city"] != "Current Location":
                            break
                    if result["city"] != "Current Location":
                        await cache.set(cache_key, result, ttl_seconds=86400)
                        return result
            else:
                print(f"[REVERSE GEOCODE GOOGLE] HTTP {res.status_code}", flush=True)
        except Exception as e:
            print(f"[REVERSE GEOCODE GOOGLE ERR] {type(e).__name__}", flush=True)

    # 2. Resilient Fallback: Google Places API (New) reverse address lookup
    if GOOGLE_MAPS_SERVER_KEY and (result["city"] == "Current Location" or not result.get("formatted_address")):
        try:
            places_url = "https://places.googleapis.com/v1/places:searchNearby"
            headers = {
                "Content-Type": "application/json",
                "X-Goog-Api-Key": GOOGLE_MAPS_SERVER_KEY,
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
                if is_quota_error(res):
                    return result
                if res.status_code == 200:
                    places = res.json().get("places", [])
                    if places:
                        p = places[0]
                        result["formatted_address"] = p.get("formattedAddress", "")
                        _apply_components(result, p.get("addressComponents", []))
                        if result["city"] != "Current Location":
                            await cache.set(cache_key, result, ttl_seconds=86400)
                            return result
        except Exception as e:
            print(f"[PLACES REVERSE GEOCODE ERR] {e}", flush=True)

    # 3. Final Clean Fallback (Never returns hardcoded Madhubani)
    await cache.set(cache_key, result, ttl_seconds=3600)
    return result


class GoogleNearbyError(Exception):
    """searchNearby failed for a reason other than quota (no key, HTTP error, network). strict=True only."""


# Jarvis "nearest hospital / medical shop / cafe" (tour_guide_service.lookup_places): exactly these fields.
NEARBY_ESSENTIAL_FIELDS = (
    "places.displayName,places.formattedAddress,places.location,places.rating,places.userRatingCount,"
    "places.currentOpeningHours.openNow,places.nationalPhoneNumber,places.googleMapsUri"
)


async def search_nearby_places(
    lat: float,
    lng: float,
    radius: int = 5000,
    place_types: Optional[List[str]] = None,
    *,
    strict: bool = False,
    counter: Optional[GoogleCallCounter] = None,
) -> List[Dict[str, Any]]:
    """
    Search nearby places using Google Places API (New) searchNearby.
    Caches results in Redis for 2 hours with key places:nearby:{lat}:{lng}:{radius}.
    Outputs formatted schema with is_mock=False.

    strict=True (Jarvis place lookups): no cache here (the caller caches 60 s), rankPreference DISTANCE,
    maxResultCount 5, field mask NEARBY_ESSENTIAL_FIELDS (adds open_now, phone, maps_uri to each place), and
    errors are raised instead of returning []: GoogleQuotaError (quota / paused key, which also pauses
    "nearby" until Google's reset) or GoogleNearbyError. One HTTP request; never a Place Details call.
    """
    # Clamp radius between 500m and 50000m
    clamped_radius = max(500, min(int(radius or 5000), 50000))
    type_tag = "_".join(sorted(place_types)) if place_types else "all"
    cache_key = f"places:nearby:{round(lat, 3)}:{round(lng, 3)}:{clamped_radius}:{type_tag}"
    if not strict:
        cached_places = await cache.get(cache_key)
        if cached_places is not None and isinstance(cached_places, list):
            return cached_places

    if not GOOGLE_MAPS_SERVER_KEY:
        print("[GOOGLE PLACES] No API key configured. Returning empty list.", flush=True)
        if strict:
            raise GoogleNearbyError("no_key")
        return []
    if strict and await is_paused("nearby"):
        raise GoogleQuotaError("nearby")

    url = "https://places.googleapis.com/v1/places:searchNearby"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_MAPS_SERVER_KEY,
        "X-Goog-FieldMask": NEARBY_ESSENTIAL_FIELDS if strict else (
            "places.id,places.displayName,places.formattedAddress,places.location,"
            "places.rating,places.userRatingCount,places.primaryType,places.editorialSummary"
        ),
    }

    types_to_include = place_types or DEFAULT_NEARBY_TYPES
    # Exclude any types that cause 400 Bad Request
    safe_types = [t for t in types_to_include if t not in ["point_of_interest", "establishment"]]

    payload = {
        "includedTypes": safe_types,
        "maxResultCount": 5 if strict else 15,
        "locationRestriction": {
            "circle": {
                "center": {"latitude": lat, "longitude": lng},
                "radius": float(clamped_radius),
            }
        },
    }
    if strict:
        payload["rankPreference"] = "DISTANCE"

    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            _count(counter)
            res = await client.post(url, headers=headers, json=payload)
            if strict and is_quota_error(res):
                await mark_paused("nearby", res)
                raise GoogleQuotaError("nearby")
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

                    item = {
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
                    }
                    if strict:
                        # Google's own values only; None when Google doesn't say (shown as unknown, never guessed).
                        open_now = (place.get("currentOpeningHours") or {}).get("openNow")
                        item["open_now"] = open_now if isinstance(open_now, bool) else None
                        item["phone"] = place.get("nationalPhoneNumber") or None
                        item["maps_uri"] = place.get("googleMapsUri") or None
                    transformed.append(item)

                # Sort by distance
                transformed.sort(key=lambda x: x["distanceMeters"])

                if strict:
                    return transformed
                # Cache in Redis with 2-hour TTL
                await cache.set(cache_key, transformed, ttl_seconds=7200)
                return transformed
            else:
                if strict:
                    print(f"[GOOGLE PLACES ERROR] nearby HTTP {res.status_code}", flush=True)
                    raise GoogleNearbyError(f"http_{res.status_code}")
                print(f"[GOOGLE PLACES ERROR] Status: {res.status_code} Body: {res.text[:300]}", flush=True)
    except (GoogleQuotaError, GoogleNearbyError):
        raise
    except Exception as e:
        if strict:
            print(f"[GOOGLE PLACES EXCEPTION] nearby {type(e).__name__}", flush=True)
            raise GoogleNearbyError(type(e).__name__) from e
        print(f"[GOOGLE PLACES EXCEPTION] {e}", flush=True)

    return []


AUTOCOMPLETE_CACHE_VERSION = "v2"  # v2 adds "types"


async def autocomplete_places(
    query: str,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    counter: Optional[GoogleCallCounter] = None,
) -> List[Dict[str, Any]]:
    """
    Search suggestions using Google Places API (New) autocomplete.
    Caches results in Redis for 1 hour. Each suggestion carries Google's "types" (no extra call).
    Raises GoogleQuotaError on a quota/paused error; other failures return [].
    """
    if not query or len(query.strip()) < 2:
        return []

    clean_q = query.strip()
    cache_key = (f"places:autocomplete:{AUTOCOMPLETE_CACHE_VERSION}:{clean_q.lower()}:"
                 f"{round(lat, 2) if lat else 'none'}:{round(lng, 2) if lng else 'none'}")
    cached_val = await cache.get(cache_key)
    if cached_val is not None:
        return cached_val

    if not GOOGLE_MAPS_SERVER_KEY:
        return []

    url = "https://places.googleapis.com/v1/places:autocomplete"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_MAPS_SERVER_KEY,
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

    if await is_paused("autocomplete"):
        raise GoogleQuotaError("autocomplete")
    try:
        _count(counter)
        async with httpx.AsyncClient(timeout=4.0) as client:
            res = await client.post(url, headers=headers, json=payload)
            if is_quota_error(res):
                await mark_paused("autocomplete", res)
                raise GoogleQuotaError("autocomplete")
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
                        "types": [t for t in (pred.get("types") or []) if isinstance(t, str)],
                    })

                await cache.set(cache_key, results, ttl_seconds=3600)
                return results
            else:
                print(f"[GOOGLE AUTOCOMPLETE ERROR] HTTP {res.status_code}", flush=True)
    except GoogleQuotaError:
        raise
    except Exception as e:
        print(f"[GOOGLE AUTOCOMPLETE EXCEPTION] {type(e).__name__}", flush=True)

    return []


TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
# No photos, reviews, ratings or hours: just what a named lookup needs.
TEXT_SEARCH_FIELDS = "places.id,places.displayName,places.formattedAddress,places.location,places.types"
TEXT_SEARCH_RATING_FIELDS = ",places.rating,places.userRatingCount"   # category search only
TEXT_SEARCH_CACHE_VERSION = "v1"
TEXT_SEARCH_PAGE = 6


async def text_search_places(query: str, counter: Optional[GoogleCallCounter] = None, *,
                             included_type: Optional[str] = None,
                             bias: Optional[Tuple[float, float, float]] = None,
                             with_rating: bool = False) -> List[Dict[str, Any]]:
    """
    ONE Places Text Search (New) call (regionCode IN): name, address, coordinates and types for up to 6 places.
    Cached 1 hour like autocomplete. Raises GoogleQuotaError on a quota/paused error; other failures return [].
    Category search (voice "X ke paas restaurant"): included_type (a Google place type, not strict), bias =
    (lat, lng, radius_m) as a locationBias circle, with_rating adds rating + userRatingCount. Still one call.
    """
    clean_q = (query or "").strip()
    if len(clean_q) < 2:
        return []
    extra = ""
    if included_type or bias or with_rating:
        b = f"{bias[0]:.3f},{bias[1]:.3f},{int(bias[2])}" if bias else "-"
        extra = f":{included_type or '-'}:{b}:{'r' if with_rating else '-'}"
    cache_key = f"places:textsearch:{TEXT_SEARCH_CACHE_VERSION}:{clean_q.lower()}{extra}"
    cached_val = await cache.get(cache_key)
    if cached_val is not None:
        return cached_val
    if not GOOGLE_MAPS_SERVER_KEY:
        return []
    if await is_paused("textsearch"):
        raise GoogleQuotaError("textsearch")
    headers = {"Content-Type": "application/json", "X-Goog-Api-Key": GOOGLE_MAPS_SERVER_KEY,
               "X-Goog-FieldMask": TEXT_SEARCH_FIELDS + (TEXT_SEARCH_RATING_FIELDS if with_rating else "")}
    payload: Dict[str, Any] = {"textQuery": clean_q, "regionCode": "IN", "languageCode": "en", "pageSize": TEXT_SEARCH_PAGE}
    if included_type:
        payload["includedType"] = included_type          # a preference, not strictTypeFiltering
    if bias:
        payload["locationBias"] = {"circle": {"center": {"latitude": bias[0], "longitude": bias[1]},
                                              "radius": float(min(max(bias[2], 100), 50000))}}
    try:
        _count(counter)
        async with httpx.AsyncClient(timeout=4.0) as client:
            res = await client.post(TEXT_SEARCH_URL, headers=headers, json=payload)
        if is_quota_error(res):
            await mark_paused("textsearch", res)
            raise GoogleQuotaError("textsearch")
        if res.status_code != 200:
            print(f"[GOOGLE TEXT SEARCH] HTTP {res.status_code}", flush=True)
            return []
        results: List[Dict[str, Any]] = []
        for p in (res.json() or {}).get("places") or []:
            loc = p.get("location") or {}
            name = (p.get("displayName") or {}).get("text")
            if not name or loc.get("latitude") is None or loc.get("longitude") is None:
                continue   # never invent a name or a position
            address = p.get("formattedAddress") or ""
            results.append({
                "id": p.get("id"), "place_id": p.get("id"), "name": name,
                "city": address, "region": address, "country": "India",
                "latitude": loc["latitude"], "longitude": loc["longitude"],
                "displayName": address or name, "display_name": address or name,
                "types": [t for t in (p.get("types") or []) if isinstance(t, str)],
                **({"rating": p["rating"], "user_rating_count": p.get("userRatingCount")}
                   if with_rating and isinstance(p.get("rating"), (int, float)) else {}),
            })
        await cache.set(cache_key, results, ttl_seconds=3600)
        return results
    except GoogleQuotaError:
        raise
    except Exception as e:
        print(f"[GOOGLE TEXT SEARCH EXCEPTION] {type(e).__name__}", flush=True)
        return []


# Google place IDs are URL-safe base64-like strings. Anything else (slashes, our own "poi-..." IDs) is rejected.
PLACE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{10,300}$")
# BASIC: what address search needs (cheap). FULL: what the place details page shows (one call per place).
PLACE_FIELDS_BASIC = "id,displayName,formattedAddress,location,addressComponents"
PLACE_FIELDS_FULL = (
    "id,displayName,formattedAddress,location,regularOpeningHours.openNow,regularOpeningHours.weekdayDescriptions,"
    "nationalPhoneNumber,websiteUri,googleMapsUri,editorialSummary"
)
DETAIL_CACHE_VERSION = "v2"  # bump when the cached shape changes, so old entries aren't reused


def is_valid_place_id(place_id: str) -> bool:
    return bool(place_id) and bool(PLACE_ID_RE.match(place_id))


def _map_full_detail(data: Dict[str, Any]) -> Dict[str, Any]:
    """Google Places (New) response -> the app's shape. Missing fields become None / [] (the page hides them)."""
    loc = data.get("location") or {}
    hours = data.get("regularOpeningHours") or {}
    return {
        "id": data.get("id"),
        "name": (data.get("displayName") or {}).get("text") or "",
        "address": data.get("formattedAddress") or "",
        "latitude": loc.get("latitude"),
        "longitude": loc.get("longitude"),
        "open_now": hours.get("openNow"),
        "hours": list(hours.get("weekdayDescriptions") or []),
        "phone": data.get("nationalPhoneNumber"),
        "website": data.get("websiteUri"),
        "maps_url": data.get("googleMapsUri"),
        "summary": (data.get("editorialSummary") or {}).get("text"),
    }


async def get_place_details(place_id: str, full: bool = False,
                            counter: Optional[GoogleCallCounter] = None) -> Optional[Dict[str, Any]]:
    """
    Details for a Google Place ID, cached 24 hours.
    full=False: id, name, address, latitude, longitude (address search; types come from autocomplete).
    full=True:  also open_now, hours, phone, website, maps_url, summary (the map's place details page).
    Returns None for an invalid ID, a missing key, or when Google has no such place.
    Raises GoogleQuotaError on a quota/paused error.
    """
    if not is_valid_place_id(place_id) or not GOOGLE_MAPS_SERVER_KEY:
        return None

    cache_key = f"places:detail:{DETAIL_CACHE_VERSION}:{'full' if full else 'basic'}:{place_id}"
    cached_val = await cache.get(cache_key)
    if cached_val is not None:
        return cached_val

    url = f"https://places.googleapis.com/v1/places/{place_id}"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_MAPS_SERVER_KEY,
        "X-Goog-FieldMask": PLACE_FIELDS_FULL if full else PLACE_FIELDS_BASIC,
    }

    if await is_paused("details"):
        raise GoogleQuotaError("details")
    try:
        _count(counter)
        async with httpx.AsyncClient(timeout=4.0) as client:
            res = await client.get(url, headers=headers)
            if is_quota_error(res):
                await mark_paused("details", res)
                raise GoogleQuotaError("details")
            if res.status_code == 200:
                data = res.json()
                if full:
                    detail = _map_full_detail(data)
                else:
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
            print(f"[GOOGLE PLACE DETAIL] HTTP {res.status_code}", flush=True)
    except GoogleQuotaError:
        raise
    except Exception as e:
        print(f"[GOOGLE PLACE DETAIL EXCEPTION] {type(e).__name__}", flush=True)

    return None
