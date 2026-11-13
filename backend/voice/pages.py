"""
The ONLY place voice page names map to app routes (voicefirst.md step 2).
The frontend mirrors this list as an allowlist in frontend/src/voice/uiActions.ts.
"""
from typing import Dict, Optional, Tuple

ROUTES: Dict[str, str] = {
    "home": "/home",
    "my_trips": "/trips",
    "trip": "/trip",
    "itinerary": "/trip/itinerary",
    "map": "/map",
    "food": "/food",
    "rides": "/rides",
    "expenses": "/expenses",
    "explore": "/explore",
    "guide": "/guide",
    "saved_places": "/saved-places",
    "more": "/more",
    "plan_trip": "/trips/new",
}
PAGES = list(ROUTES)

NEEDS_TRIP = {"trip", "itinerary"}
MIN_DAY, MAX_DAY = 1, 30

# Spoken confirmations, per page: "hi" = Roman-script Hinglish, "en" = English.
CONFIRM: Dict[str, Dict[str, str]] = {
    "home": {"hi": "Home khol diya.", "en": "Opened home."},
    "my_trips": {"hi": "Aapki trips khol di.", "en": "Opened your trips."},
    "trip": {"hi": "Aapki trip khol di.", "en": "Opened your trip."},
    "itinerary": {"hi": "Aapka itinerary khol diya.", "en": "Opened your itinerary."},
    "itinerary_day": {"hi": "Day {n} khol diya.", "en": "Opened day {n}."},
    "map": {"hi": "Map khol diya.", "en": "Opened the map."},
    "food": {"hi": "Khane ki jagah khol di.", "en": "Opened food places."},
    "rides": {"hi": "Rides khol diya.", "en": "Opened rides."},
    "expenses": {"hi": "Kharche khol diye.", "en": "Opened your expenses."},
    "explore": {"hi": "Explore khol diya.", "en": "Opened explore."},
    "guide": {"hi": "Tour guide khol diya.", "en": "Opened the tour guide."},
    "saved_places": {"hi": "Saved places khol diye.", "en": "Opened your saved places."},
    "more": {"hi": "Settings khol di.", "en": "Opened more options."},
    "plan_trip": {"hi": "Nayi trip ka page khol diya.", "en": "Opened a new trip."},
}

NO_TRIP_REPLY = {"hi": "Abhi koi trip khuli nahi hai, aapki trips khol raha hoon.",
                 "en": "No trip is open, opening your trips."}
WHICH_PAGE_REPLY = {"hi": "Kaunsa page kholun?", "en": "Which page should I open?"}


def resolve(page: Optional[str], day: Optional[int] = None, has_trip: bool = False) -> Tuple[Optional[str], Optional[str]]:
    """(route, None) on success, else (None, "unknown_page" | "no_trip" | "bad_day")."""
    if page not in ROUTES:
        return None, "unknown_page"
    if day is not None:
        if page != "itinerary" or isinstance(day, bool) or not isinstance(day, int) or not (MIN_DAY <= day <= MAX_DAY):
            return None, "bad_day"
    if page in NEEDS_TRIP and not has_trip:
        return None, "no_trip"
    route = ROUTES[page]
    if page == "itinerary" and day is not None:
        route = f"{route}?day={day}"
    return route, None


def confirm_text(page: str, day: Optional[int], lang: str) -> str:
    lang = lang if lang in ("hi", "en") else "hi"
    if page == "itinerary" and day is not None:
        return CONFIRM["itinerary_day"][lang].format(n=day)
    return CONFIRM[page][lang]
