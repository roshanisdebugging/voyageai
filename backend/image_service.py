"""
Real pictures for places, events and trip covers that are ALREADY KNOWN (title + destination + coordinates).
This module never finds places; place lookup stays Google-only elsewhere.

resolve_place_image(title, destination, lat, lng, category) -> {url, credit, credit_url, source, place_id?} or None
  1. Google Places Text Search (New), one call: "<title>, <destination>", location bias around lat/lng,
     field mask id/displayName/location/photos. The first photo is served through OUR proxy
     (/api/place-photo?name=...&w=...&sig=...), so the API key never reaches the browser. Nothing from Google is
     cached or stored (Google's terms: no storing photos or photo names); only the place_id is returned.
     The match is accepted only if the name overlaps the title or the place is within 2 km.
  2. Wikipedia: ONE batched query for all titles of a response (redirects followed, so "Amber Fort" finds
     "Amer Fort"), then per place a geosearch within 2 km for pages sharing the place's distinctive words
     (generic words like fort / palace don't count). A page is accepted only if it lies within 2 km, or Wikipedia
     resolved this exact name to it AND it names the destination (and lies within 25 km if it has coordinates).
     Only free Commons images (never en.wikipedia "fair use" files). At most 2 requests at a time; a 429 pauses
     Wikipedia for its Retry-After (img:wiki:cooldown).
  3. Pexels (PEXELS_API_KEY, optional) only for destination covers and broad categories (food, beach, market...),
     never for a named landmark.
  4. None -> the app shows a placeholder, never a random photo.
Timing: a response waits at most 2 s (LOOKUP_TIMEOUT_S). Steps 2-3 may finish in the background (up to
BACKGROUND_TIMEOUT_S) and cache their link, so the next load shows the picture.
Steps 2-3 (links only, never image bytes) are cached in Redis for 7 days; "nothing found" for 1 day; a timeout or
a provider error caches nothing. Google lookups are capped per day (IMAGE_GOOGLE_DAILY_CAP) and honour the
gmaps:paused:* keys.
Logs carry counts and timings only, never titles, keys or URLs.
"""
import hashlib
import hmac
import json
import math
import os
import re
import time
import unicodedata
import threading
from concurrent.futures import Future, ThreadPoolExecutor, wait
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urlparse

import requests

from redis_client import redis_conn

IST = timezone(timedelta(hours=5, minutes=30))

GOOGLE_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
GOOGLE_PHOTO_FIELDS = "places.id,places.displayName,places.location,places.photos"
GOOGLE_MEDIA_URL = "https://places.googleapis.com/v1/{name}/media"
WIKI_API_URL = "https://en.wikipedia.org/w/api.php"
PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"

# No contact info by default (it must be the owner's): Wikimedia then allows only 10 requests/min. Set
# WIKIMEDIA_USER_AGENT="VoyageAI/1.0 (https://your-site/; you@example.org) python-requests" for 200/min.
DEFAULT_USER_AGENT = f"VoyageAI-ImageLookup/1.0 python-requests/{requests.__version__}"

LOOKUP_TIMEOUT_S = 2.0          # the response waits at most this long for pictures
BACKGROUND_TIMEOUT_S = 12.0     # slower Wikipedia / Pexels lookups may finish (and be cached) up to this
MAX_LOOKUPS = 7                 # per highlights response
PHOTO_DEFAULT_W = 800
PHOTO_MIN_W = 64
PHOTO_MAX_W = 1600
PHOTO_MAX_BYTES = 4 * 1024 * 1024
PHOTO_CACHE_CONTROL = "private, max-age=3600"

PLACE_MATCH_KM = 2.0            # a named place / event venue
NAMED_MATCH_KM = 25.0           # exact Wikipedia name + destination named: model's coordinates may be off
COVER_MATCH_KM = 50.0           # a destination (city / region) cover
LINK_CACHE_TTL_S = 7 * 24 * 3600
NEGATIVE_CACHE_TTL_S = 24 * 3600
CACHE_VERSION = "v2"

# "places/<place id>/photos/<photo reference>": anything else is refused before any Google call.
PHOTO_NAME_RE = re.compile(r"^places/[A-Za-z0-9_-]{10,300}/photos/[A-Za-z0-9_-]{10,1200}$")
ALLOWED_PHOTO_TYPES = ("image/jpeg", "image/png", "image/webp", "image/gif")

# Broad categories that may get a stock (Pexels) picture. Anything else is a named place: never Pexels.
GENERIC_CATEGORIES = {"food", "foods", "culinary", "beach", "beaches", "market", "markets", "shopping",
                      "nightlife", "festival", "festivals", "music", "street"}

_STOPWORDS = {"the", "of", "and", "a", "an", "at", "in", "on", "to", "for", "de", "la", "shri", "sri", "shree"}

_executor = ThreadPoolExecutor(max_workers=16, thread_name_prefix="img")            # leaf lookups (never wait)
_orchestrators = ThreadPoolExecutor(max_workers=4, thread_name_prefix="img-batch")  # one per response
# Wikimedia answers bursts with 429: at most 2 requests at a time from this process, and a pause after a 429.
_wiki_slots = threading.BoundedSemaphore(2)
WIKI_COOLDOWN_KEY = "img:wiki:cooldown"
WIKI_COOLDOWN_S = 60


class _OutOfTime(Exception):
    pass


class _Transient(Exception):
    """A provider error (429 / 5xx): the lookup gives None but nothing is cached."""


class PhotoNotAllowed(Exception):
    """Bad photo name, signature or width: refused without any Google call."""


class PhotoUnavailable(Exception):
    """Google quota / paused / daily cap reached, or Google failed."""


class PhotoNotFound(Exception):
    pass


# ------------------------------------------------------------------ small helpers

def _google_key() -> str:
    from services.maps_keys import resolve_server_key
    return resolve_server_key()


def _pexels_key() -> str:
    return os.getenv("PEXELS_API_KEY", "").strip()


def _user_agent() -> str:
    return os.getenv("WIKIMEDIA_USER_AGENT", "").strip() or DEFAULT_USER_AGENT


def _remaining(deadline: float, cap: float = 2.0) -> float:
    left = deadline - time.monotonic()
    if left <= 0.05:
        raise _OutOfTime()
    return min(cap, left)


def _norm(text: str) -> str:
    s = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\([^)]*\)", " ", s)                       # "Amer Fort (Amber Fort)" -> "amer fort"
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"^the ", "", s.strip())
    return re.sub(r"\s+", " ", s).strip()


def _tokens(text: str) -> set:
    return {t for t in _norm(text).split() if t not in _STOPWORDS and len(t) > 1}


def _overlap(a: str, b: str) -> float:
    """Share of a's significant words that are also in b."""
    ta, tb = _tokens(a), _tokens(b)
    return len(ta & tb) / len(ta) if ta else 0.0


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _valid_coords(lat: Any, lng: Any) -> Optional[Tuple[float, float]]:
    try:
        la, ln = float(lat), float(lng)
    except (TypeError, ValueError):
        return None
    if not (-90 <= la <= 90 and -180 <= ln <= 180) or (la == 0 and ln == 0):
        return None
    return la, ln


def image_kind(category: Optional[str]) -> str:
    """'category' for broad categories (Pexels allowed), else 'place' (a named landmark: never Pexels)."""
    words = set(re.findall(r"[a-z]+", str(category or "").lower()))
    return "category" if words & GENERIC_CATEGORIES else "place"


def _today_key() -> str:
    return datetime.now(IST).date().isoformat()


def _under_daily_cap(name: str, env: str, default: int) -> bool:
    """Counts one call against a per-day cap. Fails closed (no Google call) if Redis is down."""
    try:
        cap = int(os.getenv(env, str(default)))
    except ValueError:
        cap = default
    key = f"img:calls:{name}:{_today_key()}"
    try:
        n = redis_conn.incr(key)
        if n == 1:
            redis_conn.expire(key, 2 * 24 * 3600)
        return n <= cap
    except Exception:
        return False


def _is_paused(api: str) -> bool:
    try:
        return bool(redis_conn.get(f"gmaps:paused:{api}"))
    except Exception:
        return False


def _mark_paused(api: str, res: Any) -> None:
    from services.google_maps_service import PER_MINUTE_PAUSE_S, _is_daily, _seconds_to_google_reset
    ttl = _seconds_to_google_reset() if _is_daily(res) else PER_MINUTE_PAUSE_S
    try:
        redis_conn.set(f"gmaps:paused:{api}", json.dumps(True), ex=ttl)
    except Exception:
        pass
    print(f"[GOOGLE QUOTA] {api} paused for {ttl} s (images)", flush=True)


# ------------------------------------------------------------------ Google photo proxy URLs

def _signing_key() -> bytes:
    return hashlib.sha256(b"voyageai-place-photo:" + _google_key().encode()).digest()


def photo_signature(name: str) -> str:
    return hmac.new(_signing_key(), name.encode(), hashlib.sha256).hexdigest()[:32]


def photo_proxy_url(name: str, width: int = PHOTO_DEFAULT_W) -> str:
    w = max(PHOTO_MIN_W, min(int(width), PHOTO_MAX_W))
    return f"/api/place-photo?name={quote(name, safe='/')}&w={w}&sig={photo_signature(name)}"


def check_photo_request(name: str, width: Any, sig: str) -> int:
    """Validates a proxy request (format, signature, width). Returns the width to use. No network."""
    name = (name or "").strip()
    if not PHOTO_NAME_RE.match(name):
        raise PhotoNotAllowed("name")
    if not _google_key():
        raise PhotoUnavailable("no key")
    if not sig or not hmac.compare_digest(str(sig), photo_signature(name)):
        raise PhotoNotAllowed("sig")
    try:
        w = int(width)
    except (TypeError, ValueError):
        raise PhotoNotAllowed("width")
    if w < PHOTO_MIN_W:
        raise PhotoNotAllowed("width")
    return min(w, PHOTO_MAX_W)


def fetch_place_photo(name: str, width: Any, sig: str) -> Tuple[bytes, str]:
    """
    The bytes of one Google place photo for the proxy endpoint (never stored). Two calls: the media endpoint with
    skipHttpRedirect (key in a header) gives a short-lived googleusercontent URL; that URL is fetched WITHOUT the key.
    """
    w = check_photo_request(name, width, sig)
    if _is_paused("photo"):
        raise PhotoUnavailable("paused")
    if not _under_daily_cap("photo", "IMAGE_PHOTO_DAILY_CAP", 1000):
        raise PhotoUnavailable("cap")
    try:
        res = requests.get(GOOGLE_MEDIA_URL.format(name=name),
                           params={"maxWidthPx": w, "skipHttpRedirect": "true"},
                           headers={"X-Goog-Api-Key": _google_key()}, timeout=4)
    except Exception as e:
        print(f"[PLACE PHOTO] media call failed: {type(e).__name__}", flush=True)
        raise PhotoUnavailable("network")
    from services.google_maps_service import is_quota_error
    if is_quota_error(res):
        _mark_paused("photo", res)
        raise PhotoUnavailable("quota")
    if res.status_code in (400, 404):
        raise PhotoNotFound()
    if res.status_code != 200:
        print(f"[PLACE PHOTO] media HTTP {res.status_code}", flush=True)
        raise PhotoUnavailable("http")
    try:
        photo_uri = str((res.json() or {}).get("photoUri") or "")
    except Exception:
        photo_uri = ""
    host = (urlparse(photo_uri).hostname or "").lower()
    if not photo_uri.startswith("https://") or not (host.endswith(".googleusercontent.com") or host.endswith(".ggpht.com")):
        raise PhotoNotFound()
    try:
        img = requests.get(photo_uri, timeout=6, stream=True)
        ctype = (img.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if img.status_code != 200 or ctype not in ALLOWED_PHOTO_TYPES:
            raise PhotoNotFound()
        data = bytearray()
        for chunk in img.iter_content(64 * 1024):
            data.extend(chunk)
            if len(data) > PHOTO_MAX_BYTES:
                raise PhotoNotFound()
        return bytes(data), ctype
    except PhotoNotFound:
        raise
    except Exception as e:
        print(f"[PLACE PHOTO] image fetch failed: {type(e).__name__}", flush=True)
        raise PhotoUnavailable("network")


# ------------------------------------------------------------------ 1. Google

def _google_lookup(title: str, destination: str, coords: Optional[Tuple[float, float]],
                   deadline: float) -> Tuple[Optional[Dict[str, Any]], Optional[Tuple[float, float]]]:
    """(image or None, Google's location of the matched place or None)."""
    key = _google_key()
    if not key or _is_paused("textsearch"):
        return None, None
    if not _under_daily_cap("google", "IMAGE_GOOGLE_DAILY_CAP", 300):
        return None, None
    query = f"{title}, {destination}" if destination and _norm(destination) not in _norm(title) else title
    payload: Dict[str, Any] = {"textQuery": query, "regionCode": "IN", "languageCode": "en", "pageSize": 1}
    if coords:
        payload["locationBias"] = {"circle": {"center": {"latitude": coords[0], "longitude": coords[1]},
                                              "radius": 5000.0}}
    res = requests.post(GOOGLE_TEXT_SEARCH_URL, json=payload, timeout=_remaining(deadline),
                        headers={"Content-Type": "application/json", "X-Goog-Api-Key": key,
                                 "X-Goog-FieldMask": GOOGLE_PHOTO_FIELDS})
    from services.google_maps_service import is_quota_error
    if is_quota_error(res):
        _mark_paused("textsearch", res)
        return None, None
    if res.status_code != 200:
        return None, None
    places = (res.json() or {}).get("places") or []
    if not places:
        return None, None
    p = places[0]
    name = (p.get("displayName") or {}).get("text") or ""
    loc = p.get("location") or {}
    g_coords = _valid_coords(loc.get("latitude"), loc.get("longitude"))
    near = bool(coords and g_coords and _haversine_km(*coords, *g_coords) <= PLACE_MATCH_KM)
    named = _overlap(title, name) >= 0.5 or _overlap(name, title) >= 0.5
    if not (named or near):
        return None, None                     # Google returned some other place: not this one's picture
    photos = [ph for ph in (p.get("photos") or []) if PHOTO_NAME_RE.match(str(ph.get("name") or ""))]
    if not photos:
        return None, g_coords
    photo = photos[0]
    authors = [a for a in (photo.get("authorAttributions") or []) if a.get("displayName")]
    return {
        "url": photo_proxy_url(photo["name"]),
        "credit": ", ".join(a["displayName"] for a in authors) or "Google Maps",
        "credit_url": next((a.get("uri") for a in authors if str(a.get("uri") or "").startswith("https://")), None),
        "source": "google",
        "place_id": p.get("id"),
    }, g_coords


# ------------------------------------------------------------------ 2. Wikipedia

def _wiki_request(url: str, params: Optional[Dict[str, Any]], deadline: float):
    """One Wikipedia GET: at most 2 at a time, none during a 429 cool-down. Raises _Transient on 429 / 5xx."""
    try:
        if redis_conn.get(WIKI_COOLDOWN_KEY):
            raise _Transient("wikipedia cooling down after a 429")
    except _Transient:
        raise
    except Exception:
        pass
    if not _wiki_slots.acquire(timeout=_remaining(deadline)):
        raise _OutOfTime()
    try:
        res = requests.get(url, params=params, headers={"User-Agent": _user_agent(), "Accept": "application/json"},
                           timeout=_remaining(deadline))
    finally:
        _wiki_slots.release()
    if res.status_code == 429:
        try:
            wait_s = int(res.headers.get("Retry-After") or WIKI_COOLDOWN_S)
        except (TypeError, ValueError):
            wait_s = WIKI_COOLDOWN_S
        try:
            redis_conn.set(WIKI_COOLDOWN_KEY, "1", ex=max(5, min(wait_s, 600)))
        except Exception:
            pass
        raise _Transient("wikipedia HTTP 429")
    return res


WIKI_QUERY = {
    "action": "query", "format": "json", "formatversion": "2", "redirects": "1",
    "prop": "pageimages|coordinates|pageprops|extracts|info", "inprop": "url", "piprop": "thumbnail|original",
    "pithumbsize": "960", "ppprop": "disambiguation|wikibase-shortdesc", "exintro": "1", "explaintext": "1",
    "exsentences": "3", "exlimit": "20", "colimit": "50",
}

# Words that name a KIND of place, not which one: sharing only these is not a match ("Amber Fort" vs "Jaigarh Fort").
GENERIC_PLACE_WORDS = {
    "fort", "palace", "temple", "mandir", "lake", "garden", "gardens", "museum", "market", "bazaar", "bazar", "road",
    "street", "beach", "falls", "waterfall", "trek", "walk", "tour", "park", "national", "valley", "river", "hill",
    "hills", "mahal", "gate", "church", "mosque", "masjid", "dargah", "ghat", "ghats", "village", "city", "old",
    "new", "famous", "visit", "restaurant", "cafe", "food", "festival", "experience", "center", "centre", "view",
    "point", "india", "observatory", "stepwell", "ka", "ki", "ke", "state", "district", "area",
}


def _distinct(text: str, exclude: set) -> set:
    return {t for t in _tokens(text) if t not in GENERIC_PLACE_WORDS and t not in exclude}


def names_match(title: str, page_title: str, destination: str = "") -> bool:
    """Both names share their distinctive words (generic words like fort/palace and the destination don't count)."""
    dest = _tokens(destination)
    a, b = _distinct(title, dest), _distinct(page_title, dest)
    if not a or not b:
        return False
    shared = a & b
    return len(shared) / len(a) >= 0.5 and len(shared) / len(b) > 0.5


def _page_summary(p: Dict[str, Any]) -> Dict[str, Any]:
    """An action-API page in the shape wiki_summary_matches / _wiki_result read."""
    coords = (p.get("coordinates") or [{}])[0] or {}
    props = p.get("pageprops") or {}
    return {
        "type": "disambiguation" if "disambiguation" in props else "standard",
        "title": p.get("title") or "",
        "description": props.get("wikibase-shortdesc") or p.get("description") or "",
        "extract": p.get("extract") or "",
        "coordinates": {"lat": coords.get("lat"), "lon": coords.get("lon")} if coords else None,
        "thumbnail": p.get("thumbnail") or {},
        "originalimage": p.get("original") or {},
        "content_urls": {"desktop": {"page": p.get("fullurl")}},
    }


def _wiki_pages(titles: List[str], deadline: float) -> Dict[str, Dict[str, Any]]:
    """ONE Wikipedia query for many titles (redirects followed). Returns {requested title: page summary}."""
    wanted = list(dict.fromkeys(t.replace("|", " ").strip() for t in titles if t and t.strip()))[:40]
    if not wanted:
        return {}
    res = _wiki_request(WIKI_API_URL, {**WIKI_QUERY, "titles": "|".join(wanted)}, deadline)
    if res.status_code != 200:
        raise _Transient(f"wikipedia HTTP {res.status_code}")       # not cached as "no picture"
    q = (res.json() or {}).get("query") or {}
    normalized = {n.get("from"): n.get("to") for n in q.get("normalized") or []}
    redirects = {r.get("from"): r.get("to") for r in q.get("redirects") or []}
    pages = {p.get("title"): p for p in q.get("pages") or []
             if isinstance(p, dict) and not p.get("missing") and not p.get("invalid")}
    out = {}
    for t in wanted:
        name = normalized.get(t, t)
        name = redirects.get(name, name)
        if name in pages:
            out[t] = _page_summary(pages[name])
    return out


COMMONS_HOSTS = ("upload.wikimedia.org", "thumb.wikimedia.org")


def _is_commons(url: str) -> bool:
    """A file on Wikimedia Commons (free licence), served from a Wikimedia image host over https."""
    u = urlparse(url or "")
    return u.scheme == "https" and (u.hostname or "").lower() in COMMONS_HOSTS and u.path.startswith("/wikipedia/commons/")


def _commons_image(summary: Dict[str, Any]) -> Optional[str]:
    """The page image, only if it is a free Commons file (en.wikipedia-local files are often non-free)."""
    thumb = str((summary.get("thumbnail") or {}).get("source") or "")
    orig = summary.get("originalimage") or {}
    if not _is_commons(thumb):
        return None
    if re.search(r"/\d+px-", thumb) and int(orig.get("width") or 0) >= 960:
        return re.sub(r"/\d+px-", "/960px-", thumb)
    orig_src = str(orig.get("source") or "")
    return orig_src if _is_commons(orig_src) else thumb


def wiki_summary_matches(summary: Dict[str, Any], title: str, destination: str,
                         coords: Optional[Tuple[float, float]], max_km: float,
                         exact: bool = False, loose: bool = False) -> bool:
    """
    Is this Wikipedia page about this place?
      - page within max_km (2 km for a place, 50 km for a cover) -> yes;
      - exact=True (Wikipedia resolved this very name to the page, redirects included) and the page names the
        destination: yes if it has no coordinates, or they are within 25 km (same city, model's coordinates a bit off);
      - no coordinates and not exact: the page title must equal the name, and the page must name the destination.
    loose (festivals, food...): a page that names India counts as naming the destination.
    """
    if not isinstance(summary, dict) or summary.get("type") == "disambiguation":
        return False
    text = _norm(" ".join(str(summary.get(k) or "") for k in ("description", "extract")))
    words = text.split()
    names_place = (bool(destination) and _norm(destination) in text) or ((loose or not destination) and "india" in words)
    page_coords = summary.get("coordinates") or {}
    pc = _valid_coords(page_coords.get("lat"), page_coords.get("lon"))
    if coords and pc:
        d = _haversine_km(*coords, *pc)
        if d <= max_km:
            return True
        return exact and d <= max(max_km, NAMED_MATCH_KM) and names_place
    if exact:
        return names_place
    page_title = _norm(summary.get("title") or "")
    wanted = {_norm(title)}
    if destination:
        wanted.add(_norm(f"{title}, {destination}"))
        wanted.add(_norm(f"{title} {destination}"))
    return page_title in wanted and names_place


def _wiki_result(summary: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    img = _commons_image(summary)
    if not img:
        return None
    page = ((summary.get("content_urls") or {}).get("desktop") or {}).get("page")
    return {"url": img, "credit": "Wikimedia Commons (CC BY-SA)",
            "credit_url": page or "https://commons.wikimedia.org/", "source": "wikipedia"}


def _wiki_geo(title: str, destination: str, coords: Tuple[float, float], deadline: float) -> Optional[Dict[str, Any]]:
    """Articles within 2 km whose name shares the place's distinctive words (one geosearch + one page query)."""
    res = _wiki_request(WIKI_API_URL, {
        "action": "query", "list": "geosearch", "gscoord": f"{coords[0]}|{coords[1]}",
        "gsradius": int(PLACE_MATCH_KM * 1000), "gslimit": 20, "format": "json"}, deadline)
    if res.status_code != 200:
        raise _Transient(f"wikipedia geosearch HTTP {res.status_code}")
    hits = ((res.json() or {}).get("query") or {}).get("geosearch") or []
    names = [str(h.get("title") or "") for h in hits if names_match(title, str(h.get("title") or ""), destination)][:3]
    pages = _wiki_pages(names, deadline)
    for name in names:
        s = pages.get(name)
        if s and s.get("type") != "disambiguation":
            found = _wiki_result(s)
            if found:
                return found
    return None


# ------------------------------------------------------------------ 3. Pexels

def _pexels_lookup(query: str, deadline: float) -> Optional[Dict[str, Any]]:
    key = _pexels_key()
    if not key or not query.strip():
        return None
    res = requests.get(PEXELS_SEARCH_URL, params={"query": query, "per_page": 1, "orientation": "landscape"},
                       headers={"Authorization": key, "User-Agent": _user_agent()}, timeout=_remaining(deadline))
    if res.status_code != 200:
        raise _Transient(f"pexels HTTP {res.status_code}")
    photos = (res.json() or {}).get("photos") or []
    if not photos:
        return None
    ph = photos[0]
    src = ph.get("src") or {}
    url = src.get("large") or src.get("landscape") or src.get("medium")
    if not url or not str(url).startswith("https://"):
        return None
    who = ph.get("photographer") or "a Pexels photographer"
    return {"url": url, "credit": f"Photo by {who} on Pexels",
            "credit_url": ph.get("url") or "https://www.pexels.com/", "source": "pexels"}


# ------------------------------------------------------------------ link cache (Wikipedia / Pexels only)

def _cache_key(kind: str, title: str, destination: str) -> str:
    digest = hashlib.sha1(f"{_norm(title)}|{_norm(destination)}".encode()).hexdigest()[:24]
    return f"img:{CACHE_VERSION}:{kind}:{digest}"


_MISS = object()


def _cache_get(key: str) -> Any:
    try:
        raw = redis_conn.get(key)
    except Exception:
        return _MISS
    if raw is None:
        return _MISS
    try:
        val = json.loads(raw)
    except Exception:
        return _MISS
    if val == "none":
        return None
    return val if isinstance(val, dict) and val.get("source") in ("wikipedia", "pexels") else _MISS


def _cache_put(key: str, val: Optional[Dict[str, Any]]) -> None:
    try:
        if val is None:
            redis_conn.set(key, json.dumps("none"), ex=NEGATIVE_CACHE_TTL_S)
        elif val.get("source") in ("wikipedia", "pexels"):
            redis_conn.set(key, json.dumps(val), ex=LINK_CACHE_TTL_S)
    except Exception:
        pass


# ------------------------------------------------------------------ public

def _prepare(it: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    title = str(it.get("title") or "").strip()
    destination = str(it.get("destination") or "").strip()
    if len(title) < 2:
        return None
    kind = it.get("kind") or image_kind(it.get("category"))
    candidates = [title]
    if destination and _norm(destination) not in _norm(title):
        candidates.insert(0, f"{title}, {destination}")
    return {"title": title, "destination": destination, "kind": kind, "category": it.get("category"),
            "coords": _valid_coords(it.get("lat"), it.get("lng")), "candidates": candidates,
            "max_km": COVER_MATCH_KM if kind == "cover" else PLACE_MATCH_KM,
            "key": _cache_key(kind, title, destination)}


def _settle(fut: Future, value: Optional[Dict[str, Any]]) -> None:
    if not fut.done():
        fut.set_result(value)


def _safe_google(it: Dict[str, Any], deadline: float):
    try:
        return _google_lookup(it["title"], it["destination"], it["coords"], deadline)
    except _OutOfTime:
        return None, None
    except Exception as e:
        print(f"[IMAGES] google lookup failed: {type(e).__name__}", flush=True)
        return None, None


def _pexels_query(it: Dict[str, Any]) -> str:
    if it["kind"] == "cover":
        return f"{it['title']} India"
    broad = next((w for w in re.findall(r"[a-z]+", str(it.get("category") or "").lower()) if w in GENERIC_CATEGORIES),
                 "travel")
    return f"{it['destination']} {broad}".strip()


def _finish_item(it: Dict[str, Any], fut: Future, deadline: float) -> None:
    """Last steps for one item: Wikipedia geosearch (places), then Pexels (covers / broad categories only).
    The final answer (picture or 'none') is cached; a timeout or provider error caches nothing."""
    try:
        found = None
        if it["kind"] != "cover" and it["coords"]:
            found = _wiki_geo(it["title"], it["destination"], it["coords"], deadline)
        if not found and it["kind"] in ("cover", "category"):
            found = _pexels_lookup(_pexels_query(it), deadline)
        _cache_put(it["key"], found)
        _settle(fut, found)
    except _OutOfTime:
        _settle(fut, None)
    except _Transient as e:
        print(f"[IMAGES] {e}", flush=True)
        _settle(fut, None)
    except Exception as e:
        print(f"[IMAGES] lookup failed: {type(e).__name__}", flush=True)
        _settle(fut, None)


def _run_batch(items: List[Optional[Dict[str, Any]]], futs: List[Future], response_deadline: float) -> None:
    """
    1. Google for every item (never for covers), in parallel, until the response deadline.
    2. Cached Wikipedia / Pexels links.
    3. ONE Wikipedia query for all remaining titles.
    4. Per item: geosearch, then Pexels (broad categories / covers).
    Steps 3-4 may run past the response deadline (up to BACKGROUND_TIMEOUT_S): the response then shows a
    placeholder and the next load finds the cached link.
    """
    bg_deadline = time.monotonic() + BACKGROUND_TIMEOUT_S
    for it, fut in zip(items, futs):
        if it is None:
            _settle(fut, None)
    live = [i for i, it in enumerate(items) if it is not None]

    google = {_executor.submit(_safe_google, items[i], response_deadline): i for i in live if items[i]["kind"] != "cover"}
    if google:
        wait(list(google), timeout=max(0.0, response_deadline - time.monotonic()))
    for f, i in google.items():
        if not f.done():
            continue
        found, g_coords = f.result()
        if found:
            _settle(futs[i], found)
        elif g_coords:
            items[i]["coords"] = g_coords          # Google's position beats the model's for the Wikipedia check

    pending = [i for i in live if not futs[i].done()]
    for i in pending:
        cached = _cache_get(items[i]["key"])
        if cached is not _MISS:
            _settle(futs[i], cached)
    pending = [i for i in pending if not futs[i].done()]
    if not pending:
        return

    try:
        pages = _wiki_pages([c for i in pending for c in items[i]["candidates"]], bg_deadline)
    except (_OutOfTime, _Transient) as e:
        if isinstance(e, _Transient):
            print(f"[IMAGES] {e}", flush=True)
        for i in pending:
            _settle(futs[i], None)                  # nothing cached: try again next time
        return
    for i in pending:
        it = items[i]
        for cand in it["candidates"]:
            s = pages.get(cand)
            if s and wiki_summary_matches(s, it["title"], it["destination"], it["coords"], it["max_km"],
                                          exact=True, loose=it["kind"] != "place"):
                found = _wiki_result(s)
                if found:
                    _cache_put(it["key"], found)
                    _settle(futs[i], found)
                    break
    for i in [i for i in pending if not futs[i].done()]:
        _executor.submit(_finish_item, items[i], futs[i], bg_deadline)


def _run_batch_safe(items, futs, response_deadline) -> None:
    try:
        _run_batch(items, futs, response_deadline)
    except Exception as e:
        print(f"[IMAGES] batch failed: {type(e).__name__}", flush=True)
        for f in futs:
            _settle(f, None)


_background: set = set()


def wait_background(timeout: float = 15.0) -> None:
    """Waits for lookups still finishing in the background (tests and scripts)."""
    wait(list(_background), timeout=timeout)


def resolve_many(items: List[Dict[str, Any]], *, timeout: float = LOOKUP_TIMEOUT_S,
                 max_items: int = MAX_LOOKUPS) -> List[Optional[Dict[str, Any]]]:
    """
    Pictures for up to max_items known places ({title, destination, lat, lng, category, kind?}). Waits at most
    `timeout` (2 s): items past the cap or not ready by then get None (placeholder); slow ones finish in the
    background and are cached for the next load. Never raises.
    """
    started = time.monotonic()
    out: List[Optional[Dict[str, Any]]] = [None] * len(items)
    futs: List[Future] = []
    try:
        prepared = [_prepare(it) for it in items[:max_items]]
        futs = [Future() for _ in prepared]
        for f in futs:
            _background.add(f)
            f.add_done_callback(_background.discard)
        _orchestrators.submit(_run_batch_safe, prepared, futs, started + timeout)
        wait(futs, timeout=timeout + 0.3)
        for i, f in enumerate(futs):
            if f.done():
                out[i] = f.result()
    except Exception as e:
        print(f"[IMAGES] batch failed: {type(e).__name__}", flush=True)
    counts: Dict[str, int] = {}
    for i, r in enumerate(out[:max_items]):
        label = r["source"] if r else ("none" if i < len(futs) and futs[i].done() else "still looking")
        counts[label] = counts.get(label, 0) + 1
    print(f"[IMAGES] {min(len(items), max_items)} lookups in {time.monotonic() - started:.1f} s: "
          + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())), flush=True)
    return out


def resolve_place_image(title: str, destination: str = "", lat: Any = None, lng: Any = None,
                        category: Optional[str] = None, *, timeout: float = LOOKUP_TIMEOUT_S,
                        kind: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """A picture of this known place, or None. Never raises."""
    return resolve_many([{"title": title, "destination": destination, "lat": lat, "lng": lng,
                          "category": category, "kind": kind}], timeout=timeout, max_items=1)[0]


def resolve_cover_image(name: str, region: str = "", lat: Any = None, lng: Any = None,
                        *, timeout: float = LOOKUP_TIMEOUT_S) -> Optional[Dict[str, Any]]:
    """A destination cover: the destination's Wikipedia page, then Pexels. Never Google. Never raises."""
    return resolve_place_image(name, region if _norm(region) != _norm(name) else "", lat, lng,
                               timeout=timeout, kind="cover")
