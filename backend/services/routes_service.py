"""
Real travel times with the Google Routes API (Compute Routes). Google only: no other routing provider, no fallback.

compute_route(origin, destination, mode) -> {distance_m, duration_s, polyline, mode, warning, cached}
- One computeRoutes call, field mask routes.duration,routes.distanceMeters,routes.polyline.encodedPolyline
  (+ routes.warnings, the text Google says to show with the route). Never a wildcard mask.
- DRIVE / TWO_WHEELER use routingPreference TRAFFIC_UNAWARE (static time, cheaper). WALK must not send one
  (Google: "You can specify this option only when the travelMode is DRIVE or TWO_WHEELER, otherwise the request fails").
- Cache: ROUTES_CACHE_TTL_S seconds (default 1800) keyed by rounded origin/destination (3 decimals) + mode.
  NOTE: Google Maps Platform Service Specific Terms 19.3 allow caching only lat/lng from the Routes API;
  set ROUTES_CACHE_TTL_S=0 to stop caching route results before real users.
- Quota / paused key: RouteUnavailable, and Routes is skipped until Google's reset (shared pause helper). No retry.
- Logs carry counts and timings only: never coordinates, places or the key.
Compute Route Matrix is refused on the demo key (probe 22 Nov 2026: 403 PERMISSION_DENIED), so it is not used.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import httpx

from services import google_maps_service as gms

ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
FIELD_MASK = "routes.duration,routes.distanceMeters,routes.polyline.encodedPolyline,routes.warnings"
MODES = {"drive": "DRIVE", "two_wheeler": "TWO_WHEELER", "walk": "WALK"}
CACHE_VERSION = "v1"
TIMEOUT_S = 6.0
IST = timezone(timedelta(hours=5, minutes=30))


class RouteUnavailable(Exception):
    """Google quota reached or the key is paused: say "Route abhi available nahi hai"."""


class RouteNotFound(Exception):
    """Google answered but has no route (or failed for another reason)."""


def cache_ttl_s() -> int:
    try:
        return max(0, int(os.getenv("ROUTES_CACHE_TTL_S", "1800")))
    except ValueError:
        return 1800


def _r3(x: float) -> float:
    return round(float(x), 3)


def cache_key(o_lat: float, o_lng: float, d_lat: float, d_lng: float, mode: str) -> str:
    return f"routes:{CACHE_VERSION}:{mode}:{_r3(o_lat)}:{_r3(o_lng)}:{_r3(d_lat)}:{_r3(d_lng)}"


def _parse_duration(value: Any) -> Optional[int]:
    """Google sends durations as '1364s'."""
    if isinstance(value, str) and value.endswith("s"):
        try:
            return int(round(float(value[:-1])))
        except ValueError:
            return None
    return None


def request_body(o_lat: float, o_lng: float, d_lat: float, d_lng: float, mode: str) -> Dict[str, Any]:
    def wp(lat, lng):
        return {"location": {"latLng": {"latitude": float(lat), "longitude": float(lng)}}}
    # languageCode: without it Google picked Assamese for the warnings (eval, 22 Nov 2026).
    body: Dict[str, Any] = {"origin": wp(o_lat, o_lng), "destination": wp(d_lat, d_lng), "travelMode": MODES[mode],
                            "languageCode": "en-IN", "units": "METRIC"}
    if mode != "walk":
        body["routingPreference"] = "TRAFFIC_UNAWARE"
    return body


async def count_user_call(user_id: Optional[str]) -> Optional[int]:
    """Per-user, per-day Google Routes call count (India date). Returns today's total; never raises."""
    if not user_id:
        return None
    key = f"routes:calls:{user_id}:{datetime.now(IST):%Y-%m-%d}"
    try:
        from starlette.concurrency import run_in_threadpool
        from redis_client import redis_conn

        def _incr():
            n = redis_conn.incr(key)
            redis_conn.expire(key, 2 * 86400)
            return int(n)
        return await run_in_threadpool(_incr)
    except Exception:
        return None


async def compute_route(o_lat: float, o_lng: float, d_lat: float, d_lng: float, mode: str,
                        user_id: Optional[str] = None,
                        counter: Optional[gms.GoogleCallCounter] = None) -> Dict[str, Any]:
    """One route. Raises ValueError (bad mode), RouteUnavailable (quota/paused/no key), RouteNotFound."""
    if mode not in MODES:
        raise ValueError("mode must be one of: " + ", ".join(MODES))
    started = time.perf_counter()
    counter = counter or gms.GoogleCallCounter()
    ttl = cache_ttl_s()
    key = cache_key(o_lat, o_lng, d_lat, d_lng, mode)
    if ttl:
        cached = await gms.cache.get(key)
        if isinstance(cached, dict):
            print(f"[ROUTES] mode={mode} google_calls=0 cached=True ms={int((time.perf_counter() - started) * 1000)}", flush=True)
            return {**cached, "cached": True}

    if not gms.GOOGLE_MAPS_SERVER_KEY or await gms.is_paused("routes"):
        raise RouteUnavailable()

    headers = {"Content-Type": "application/json", "X-Goog-Api-Key": gms.GOOGLE_MAPS_SERVER_KEY, "X-Goog-FieldMask": FIELD_MASK}
    gms._count(counter)
    user_today = await count_user_call(user_id)
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            res = await client.post(ROUTES_URL, headers=headers, json=request_body(o_lat, o_lng, d_lat, d_lng, mode))
    except Exception as err:
        print(f"[ROUTES] mode={mode} google_calls={counter.count} error={type(err).__name__}", flush=True)
        raise RouteNotFound() from None
    ms = int((time.perf_counter() - started) * 1000)
    if gms.is_quota_error(res):
        await gms.mark_paused("routes", res)
        print(f"[ROUTES] mode={mode} google_calls={counter.count} quota=True user_calls_today={user_today} ms={ms}", flush=True)
        raise RouteUnavailable()
    routes = []
    if res.status_code == 200:
        try:
            routes = (res.json() or {}).get("routes") or []
        except Exception:
            routes = []
    print(f"[ROUTES] mode={mode} google_calls={counter.count} cached=False status={res.status_code} "
          f"user_calls_today={user_today} ms={ms}", flush=True)
    if not routes:
        raise RouteNotFound()
    r = routes[0]
    distance = r.get("distanceMeters")
    duration = _parse_duration(r.get("duration"))
    polyline = (r.get("polyline") or {}).get("encodedPolyline")
    if not isinstance(distance, (int, float)) or duration is None:
        raise RouteNotFound()   # never invent a distance or a time
    warnings = [w for w in (r.get("warnings") or []) if isinstance(w, str) and w.strip()]
    out = {"distance_m": int(distance), "duration_s": duration, "polyline": polyline if isinstance(polyline, str) else None,
           "mode": mode, "warning": " ".join(warnings) or None}
    if ttl:
        await gms.cache.set(key, out, ttl_seconds=ttl)
    return {**out, "cached": False}
