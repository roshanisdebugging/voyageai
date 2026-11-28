import json
import logging
from redis_client import redis_conn

logger = logging.getLogger(__name__)

# 7 Days in seconds (604,800s)
ITINERARY_CACHE_TTL = 7 * 24 * 60 * 60

# Bumped when the purpose planner rules change, so plans cached under older rules are not served again
# (v2: no invented event, venue or hotel; the stay and the event are marked with planSlot). Leisure keys: unchanged.
PURPOSE_PLAN_VERSION = 2


def build_itinerary_cache_key(destination: str, days: int, travel_style: str = "standard", pace: str = "moderate", origin: str = None,
                              purpose_type: str = None, base_area_id: str = None, purpose_text: str = None) -> str:
    """Creates a normalized, deterministic cache key with sorted style tags.
    Leisure, pilgrimage and no purpose: exactly the key from before (cached plans stay valid). Business / event /
    other add the purpose type and the base area's place id ("other" also a hash of the user's words), so a hackathon
    trip never gets the tourist plan from the cache."""
    key = _base_cache_key(destination, days, travel_style, pace, origin)
    from trip_purpose import is_focused
    if not is_focused(purpose_type):
        return key
    import hashlib
    import re
    area = re.sub(r"[^A-Za-z0-9_-]", "", str(base_area_id or ""))[:128] or "none"
    key += f":purpose_{purpose_type}:area_{area}:pv{PURPOSE_PLAN_VERSION}"
    if purpose_type == "other":
        digest = hashlib.sha256(" ".join(str(purpose_text or "").lower().split()).encode("utf-8")).hexdigest()[:16]
        key += f":text_{digest}"
    return key


def _base_cache_key(destination: str, days: int, travel_style: str = "standard", pace: str = "moderate", origin: str = None) -> str:
    """The key as it was before trip purposes (do not change: existing cache entries use it)."""
    norm_dest = str(destination or "india").strip().lower().replace(" ", "_")
    norm_pace = str(pace or "moderate").strip().lower().replace(" ", "_")

    # Split, trim, sort, and re-join styles to prevent order-dependent cache misses
    styles = [s.strip().lower().replace(" ", "_") for s in str(travel_style or "").split(",") if s.strip()]
    styles.sort()
    norm_style = "_".join(styles) if styles else "standard"

    # Transport suggestions depend on the starting city, so it is part of the key.
    norm_origin = str(origin).strip().lower().replace(" ", "_") if origin else "noorigin"
    return f"itinerary:{norm_dest}:{days}d:{norm_style}:{norm_pace}:from_{norm_origin}"


def get_cached_itinerary(cache_key: str):
    """Safe Redis lookup with fail-open error handling."""
    try:
        cached = redis_conn.get(cache_key)
        if cached:
            logger.info(f"[REDIS HIT] Key: {cache_key}")
            print(f">>> [CACHE HIT] Serving baseline itinerary from Redis for {cache_key} (~2ms)", flush=True)
            return json.loads(cached)
    except Exception as e:
        logger.warning(f"[REDIS WARNING] Failed to read itinerary cache: {e}")
        print(f"[REDIS WARNING] Failed to read itinerary cache: {e}", flush=True)
    return None

def set_cached_itinerary(cache_key: str, itinerary_data: dict):
    """Stores the generated template in Redis with 7-day TTL."""
    try:
        redis_conn.setex(cache_key, ITINERARY_CACHE_TTL, json.dumps(itinerary_data))
        logger.info(f"[REDIS STORED] Key: {cache_key} with TTL={ITINERARY_CACHE_TTL}s")
        print(f">>> [REDIS STORED] Key: {cache_key} with TTL={ITINERARY_CACHE_TTL}s", flush=True)
    except Exception as e:
        logger.warning(f"[REDIS WARNING] Failed to write itinerary cache: {e}")
        print(f"[REDIS WARNING] Failed to write itinerary cache: {e}", flush=True)
