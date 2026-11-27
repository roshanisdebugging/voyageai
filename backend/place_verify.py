"""
Check the AI itinerary's venues on Google before the itinerary is saved, and flag a stop far from the rest of its day.

The model writes venues, coordinates and costs from memory. This step looks up each named venue with the SAME
resolver checked-plan trips use (plan_card_itinerary.resolve: one shared, India-only Google search, then
proximity and name matching) and gives each activity a verify_status:
  verified   Google found it and the name matches;
  not_found  no result, no name match, or outside VERIFY_RADIUS_KM of the destination;
  far        found, but more than MAX_DAY_SPREAD_KM from the median position of that day's found stops
             (only checked when the day has at least 2 found stops);
  None       not checked: TRANSIT, a generic item with no named venue, or the step stopped (quota / paused /
             error / time limit / call cap). Nothing is stored for these.
Storage policy = plan_card_itinerary's for resolved stops: only Google's place_id and coordinates are kept
(verified and far). Google's name, rating, photos or any other content are never stored. Title, description,
time and cost are never changed, and no activity is ever removed.

Limits: MAX_GOOGLE_CALLS per trip (repeated venues are looked up once), MAX_WORKERS threads, TIME_LIMIT_S for
the whole step. Never raises: the trip becomes READY whatever happens here.
Log: one line, counts only: [PLACE VERIFY] trip=<id> activities=N verified=a not_found=b far=c google_calls=n ms=t
(plus stopped=<reason> when it stopped early). Never venue names, queries or keys.
"""
from __future__ import annotations

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from statistics import median
from typing import Any, Callable, Dict, List, Optional, Tuple

import plan_card_itinerary as PCI

MAX_DAY_SPREAD_KM = 40.0
VERIFY_RADIUS_KM = 300.0       # a venue farther than this from the destination is not this trip's venue
MAX_GOOGLE_CALLS = 20
MAX_WORKERS = 4
TIME_LIMIT_S = 20.0

VERIFIED, NOT_FOUND, FAR = "verified", "not_found", "far"
_NOT_FOUND_WHY = {"no_results", "outside_radius", "no_name_match"}

# Words that never name a venue by themselves: "Departure from Kochi Airport", "Free time", "Check-in at hotel".
_GENERIC = {
    "departure", "depart", "departing", "arrival", "arrive", "arriving", "transfer", "return", "back", "journey",
    "check", "in", "out", "checkin", "checkout", "free", "time", "leisure", "rest", "relax", "relaxing", "at", "to",
    "from", "the", "a", "an", "and", "of", "your", "our", "hotel", "resort", "stay", "room", "airport", "railway",
    "station", "bus", "stand", "terminal", "city", "town", "centre", "center", "local", "nearby", "area", "day",
    "morning", "afternoon", "evening", "night", "breakfast", "lunch", "dinner", "for", "on", "with", "explore",
    "exploring", "visit", "own", "pack", "packing", "head", "drive",
}


def should_verify(provider_name: str) -> bool:
    """Real AI output only: a MOCK itinerary (AI_PROVIDER=mock, tests) is invented data and never sent to Google."""
    return provider_name != "MOCK"


class _Budget:
    """The Google call cap, shared by the worker threads."""

    def __init__(self, limit: int):
        self.left, self.used, self._lock = limit, 0, threading.Lock()

    def take(self) -> bool:
        with self._lock:
            if self.left <= 0:
                return False
            self.left -= 1
            self.used += 1
            return True


def _words(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def venue_of(activity: Any, dest_name: str) -> Optional[str]:
    """The venue to look up, or None: TRANSIT, or nothing left once generic words and the destination are removed."""
    if str(getattr(activity, "activityType", "") or "").upper() == "TRANSIT":
        return None
    dest = set(_words(dest_name))
    for text in (getattr(activity, "locationName", None), getattr(activity, "title", None)):
        if text and [w for w in _words(text) if w not in _GENERIC and w not in dest]:
            return text.strip()
    return None


def verify_itinerary(schema, trip, search_fn: Callable = None, *, time_limit_s: float = TIME_LIMIT_S,
                     max_calls: int = MAX_GOOGLE_CALLS) -> Dict[Tuple[int, int], Dict[str, Any]]:
    """{(day_index, activity_index): {"status", "place_id", "latitude", "longitude"}} for the activities checked.
    Activities missing from the result stay unverified. Never raises. `schema` is not modified (the itinerary
    cache keeps the model's plan as it was)."""
    started = time.perf_counter()
    budget = _Budget(max_calls)
    out: Dict[Tuple[int, int], Dict[str, Any]] = {}
    stopped = None
    trip_id = getattr(trip, "id", "?")
    total = sum(len(d.activities) for d in schema.days)
    try:
        dest = trip.destination if isinstance(trip.destination, dict) else {}
        dest_name = str(dest.get("name") or trip.title or "")
        city = str(dest.get("city") or dest_name)

        def counted_search(query: str):
            if not budget.take():
                raise _CapReached()
            return (search_fn or PCI._default_search)(query)

        centre = PCI.destination_centre(trip, city, counted_search)

        venues: Dict[str, List[Tuple[int, int]]] = {}
        for di, day in enumerate(schema.days):
            for ai, act in enumerate(day.activities):
                v = venue_of(act, dest_name)
                if v:
                    venues.setdefault(v.lower(), []).append((di, ai))
        names = {k: schema.days[pos[0][0]].activities[pos[0][1]] for k, pos in venues.items()}
        halt = threading.Event()
        found: Dict[str, Tuple[Optional[Dict[str, Any]], str]] = {}

        def look(key: str):
            if halt.is_set():
                return key, (None, "stopped")
            act = names[key]
            name = venue_of(act, dest_name)
            place, why = PCI.resolve(name, city, counted_search, centre, radius_km=VERIFY_RADIUS_KM)
            if why == "error:_CapReached":
                why = "cap"
            if why in ("unavailable", "cap") or why.startswith("error:"):
                halt.set()               # quota / paused / error / cap: everything not done yet stays unverified
            return key, (place, why)

        pool = ThreadPoolExecutor(max_workers=MAX_WORKERS)
        try:
            futures = [pool.submit(look, k) for k in venues]
            done, pending = wait(futures, timeout=max(0.0, time_limit_s - (time.perf_counter() - started)))
            if pending:
                stopped = "time_limit"
                halt.set()
                for f in pending:
                    f.cancel()
            for f in done:
                key, res = f.result()
                found[key] = res
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

        whys = {why for _, why in found.values()}
        if stopped is None:
            stopped = next((w for w in ("unavailable", "cap") if w in whys), None) or \
                next((w for w in sorted(whys) if w.startswith("error:")), None)
        for key, (place, why) in found.items():
            if place is not None and why == "ok":
                rec = {"status": VERIFIED, "place_id": place["place_id"], "latitude": place["latitude"],
                       "longitude": place["longitude"]}
            elif why in _NOT_FOUND_WHY:
                rec = {"status": NOT_FOUND, "place_id": None, "latitude": None, "longitude": None}
            else:
                continue                 # stopped / unavailable / error: unverified
            for pos in venues[key]:
                out[pos] = dict(rec)

        for di, day in enumerate(schema.days):           # the distance check, per day
            mine = [(pos, r) for pos, r in out.items() if pos[0] == di and r["status"] == VERIFIED]
            if len(mine) < 2:
                continue
            mlat = median(r["latitude"] for _, r in mine)
            mlng = median(r["longitude"] for _, r in mine)
            for pos, r in mine:
                if PCI._km(mlat, mlng, r["latitude"], r["longitude"]) > MAX_DAY_SPREAD_KM:
                    r["status"] = FAR
    except Exception as err:     # noqa: BLE001 - the trip must never fail here
        stopped = f"error:{type(err).__name__}"
        out = {}                         # nothing half-checked is stored: every activity stays unverified
    counts = {s: sum(1 for r in out.values() if r["status"] == s) for s in (VERIFIED, NOT_FOUND, FAR)}
    print(f"[PLACE VERIFY] trip={trip_id} activities={total} verified={counts[VERIFIED]} not_found={counts[NOT_FOUND]} "
          f"far={counts[FAR]} google_calls={budget.used} ms={int((time.perf_counter() - started) * 1000)}"
          + (f" stopped={stopped}" if stopped else ""), flush=True)
    return out


class _CapReached(Exception):
    """MAX_GOOGLE_CALLS used: no more look-ups for this trip."""
