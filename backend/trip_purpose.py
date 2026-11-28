"""
Why the trip is made (purpose) and where the traveller will mostly be (base area). Optional, never blocks a trip.

Shared by the voice draft (voice/draft.py), trip creation (trip_lifecycle.py), the itinerary prompt and cache key
(itinerary_service.py, itinerary_cache_service.py) and the Google check (place_verify.py).

Purpose types: leisure, business (work), event (hackathon, conference, wedding, meeting a team ...), pilgrimage,
other (the user's own words). CODE maps the words to a type with the word lists below, never the model.
Only business, event and other get a base area and the focused planner rules; leisure, pilgrimage and no purpose plan
exactly as before.
The free text is kept to PURPOSE_TEXT_MAX characters of letters, digits and common punctuation, on one line; the
planner sees it only as quoted data.
"""
from __future__ import annotations

import unicodedata
from typing import Any, Dict, Optional, Tuple

PURPOSE_TYPES = ("leisure", "business", "event", "pilgrimage", "other")
FOCUSED_PURPOSES = frozenset({"business", "event", "other"})   # these get a base area question and the planner rules
PURPOSE_TEXT_MAX = 120
BASE_AREA_RADIUS_KM = 15.0   # the one radius: the planner keeps stops within it, place_verify flags stops beyond it
_TEXT_PUNCT = set(" .,'-()&/!?:;+#@%")

# Word lists, Hindi (Devanagari), Hinglish and English. Matched on whole words (voice.text_utils.words), so nukta
# and chandrabindu variants line up. The first type that matches wins, in this order.
_TYPE_WORDS = (
    ("event", ("hackathon", "hackthon", "event", "events", "conference", "seminar", "wedding", "shaadi", "shadi",
               "workshop", "interview", "exam", "exams", "summit", "expo", "convention",
               "हैकाथॉन", "हैकथॉन", "हैकाथन", "इवेंट", "कॉन्फ्रेंस", "कांफ्रेंस", "सेमिनार", "शादी", "वर्कशॉप", "इंटरव्यू",
               "एग्जाम", "परीक्षा")),
    ("business", ("kaam", "work", "business", "meeting", "meetings", "office", "client", "clients", "official",
                  "काम", "बिज़नेस", "बिजनेस", "मीटिंग", "ऑफिस", "क्लाइंट", "वर्क")),
    ("pilgrimage", ("teerth", "tirth", "yatra", "darshan", "pilgrimage", "puja", "pooja",
                    "तीर्थ", "यात्रा", "दर्शन", "पूजा")),
    ("leisure", ("ghoomna", "ghumna", "ghoomne", "ghumne", "ghoom", "ghum", "ghoomenge", "ghumenge", "holiday",
                 "holidays", "vacation", "tourism", "sightseeing", "chhutti", "chutti", "leisure",
                 "घूमना", "घूमने", "घुमना", "घुमने", "घूम", "छुट्टी", "छुट्टियां", "हॉलिडे", "वेकेशन")),
)
_TYPE_PHRASES = (("leisure", ("family trip", "bas ghoomna", "fun trip")),)
_SKIP_PHRASES = ("pata nahi", "pata nahin", "nahi pata", "kuch nahi", "kuchh nahi", "koi nahi", "koi khas nahi",
                 "skip", "chhodo", "chodo", "chhod do", "baad mein", "don't know", "dont know", "no idea", "nothing",
                 "not sure", "पता नहीं", "नहीं पता", "कुछ नहीं", "कोई नहीं", "छोड़ो", "छोड़ दो", "बाद में", "स्किप")


def _words(text: str):
    from voice.text_utils import words
    return words(text)


def _canon_set(items) -> set:
    from voice.text_utils import canon
    return {canon(w) for w in items}


def _phrase_in(words, phrase: str) -> bool:
    p = _words(phrase)
    return any(words[i:i + len(p)] == p for i in range(len(words) - len(p) + 1)) if p else False


def is_focused(purpose_type: Optional[str]) -> bool:
    return purpose_type in FOCUSED_PURPOSES


def clean_purpose_text(raw: Any) -> Optional[str]:
    """The user's own words -> one trimmed line of at most PURPOSE_TEXT_MAX characters (letters in any script with
    their vowel signs, digits, spaces and common punctuation), or None. No quotes, brackets for markup or line breaks."""
    if raw is None or isinstance(raw, (bool, int, float)):
        return None
    text = " ".join(str(raw).split())          # line breaks and tabs become single spaces
    if not text or len(text) > PURPOSE_TEXT_MAX:
        return None
    has_letter = False
    for ch in text:
        kind = unicodedata.category(ch)[0]
        if kind == "L":
            has_letter = True
        elif kind not in ("M", "N") and ch not in _TEXT_PUNCT:
            return None
    return text if has_letter else None


def classify_purpose(raw: Any) -> Tuple[Optional[str], Optional[str], bool]:
    """What the user said about why they travel -> (purpose_type, purpose_text, skipped).
    "pata nahi" / "kuch nahi" -> (None, None, True); "bas ghoomna" -> leisure; "hackathon ke liye" -> event;
    anything else that is valid text -> other with the words kept; empty / invalid -> (None, None, False).
    purpose_text is kept for business, event and other only."""
    text = " ".join(str(raw or "").split())
    words = _words(text)
    if not words:
        return None, None, False
    ws = set(words)
    found = None
    for ptype, phrases in _TYPE_PHRASES:
        if any(_phrase_in(words, p) for p in phrases):
            found = ptype
    if found is None:
        for ptype, items in _TYPE_WORDS:
            if ws & _canon_set(items):
                found = ptype
                break
    if found is None and any(_phrase_in(words, p) for p in _SKIP_PHRASES):
        return None, None, True
    if found is None:
        cleaned = clean_purpose_text(text)
        return ("other", cleaned, False) if cleaned else (None, None, False)
    return found, (clean_purpose_text(text) if found in FOCUSED_PURPOSES else None), False


def is_purpose_skip(raw: Any) -> bool:
    return classify_purpose(raw) == (None, None, True)


def km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    from plan_card_itinerary import _km
    return _km(lat1, lng1, lat2, lng2)


def base_area_ok(area: Optional[Dict[str, Any]], destination: Optional[Dict[str, Any]]) -> bool:
    """A base area with coordinates within place_verify.VERIFY_RADIUS_KM (the same 300 km sanity check) of the
    destination. A destination without coordinates can't be checked: the area is accepted."""
    from place_verify import VERIFY_RADIUS_KM
    try:
        alat, alng = float(area["latitude"]), float(area["longitude"])
    except (KeyError, TypeError, ValueError):
        return False
    try:
        dlat, dlng = float((destination or {})["latitude"]), float((destination or {})["longitude"])
    except (KeyError, TypeError, ValueError):
        return True
    return km(alat, alng, dlat, dlng) <= VERIFY_RADIUS_KM


def area_ref(hit: Dict[str, Any], said: str) -> Dict[str, Any]:
    """A place search hit -> the stored base area: id, name, city, latitude, longitude (like the origin)."""
    from voice.tools.lookups import city_state
    city, state = city_state(hit)
    return {"id": hit.get("place_id") or hit.get("id"), "name": hit.get("name") or said, "city": city or hit.get("name"),
            "region": state, "latitude": float(hit["latitude"]), "longitude": float(hit["longitude"])}


def base_area_coords(trip_or_area: Any) -> Optional[Tuple[float, float]]:
    """(lat, lng) of a trip's base area (TripModel or a dict), or None."""
    area = getattr(trip_or_area, "base_area", trip_or_area)
    if not isinstance(area, dict):
        return None
    try:
        return float(area["latitude"]), float(area["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
