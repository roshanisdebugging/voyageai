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

# One line per page for the navigate tool's description (step 3: fixes step 2's misses, e.g.
# "plan a new trip" must open plan_trip without asking for details).
MEANINGS: Dict[str, str] = {
    "home": "the home screen",
    "my_trips": "list of all the user's trips (also past trips)",
    "trip": "the currently open trip's overview",
    "itinerary": "day-by-day plan of the open trip; open it directly, set day only if the user names one",
    "map": "the map with nearby places",
    "food": "the Food page; ONLY when the user asks for the page itself ('food page kholo'). Where to eat is search_nearby",
    "rides": "book a cab/auto/ride (hands over to Uber or Google Maps)",
    "expenses": "the trip's expenses / spending",
    "explore": "things to see and do, sightseeing ideas",
    "guide": "chat with the AI tour guide",
    "saved_places": "places the user saved",
    "more": "settings, profile, language and account",
    "plan_trip": "start planning a NEW trip: opens the new-trip form. Do NOT ask for destination or dates first",
}

NEEDS_TRIP = {"trip", "itinerary"}
MIN_DAY, MAX_DAY = 1, 30

# Spoken confirmations, per page: "hi" = Roman-script Hinglish, "en" = English.
CONFIRM: Dict[str, Dict[str, str]] = {
    "home": {"hi": "Home khol diya.", "en": "Opened home.", "bn": "হোম খুলে দিলাম।"},
    "my_trips": {"hi": "Aapki trips khol di.", "en": "Opened your trips.", "bn": "আপনার ট্রিপগুলো খুলে দিলাম।"},
    "trip": {"hi": "Aapki trip khol di.", "en": "Opened your trip.", "bn": "আপনার ট্রিপ খুলে দিলাম।"},
    "itinerary": {"hi": "Aapka itinerary khol diya.", "en": "Opened your itinerary.", "bn": "আপনার ইটিনেরারি খুলে দিলাম।"},
    "itinerary_day": {"hi": "Day {n} khol diya.", "en": "Opened day {n}.", "bn": "{n} নম্বর দিন খুলে দিলাম।"},
    "map": {"hi": "Map khol diya.", "en": "Opened the map.", "bn": "ম্যাপ খুলে দিলাম।"},
    "food": {"hi": "Khane ki jagah khol di.", "en": "Opened food places.", "bn": "খাবারের জায়গাগুলো খুলে দিলাম।"},
    "rides": {"hi": "Rides khol diya.", "en": "Opened rides.", "bn": "রাইডস খুলে দিলাম।"},
    "expenses": {"hi": "Kharche khol diye.", "en": "Opened your expenses.", "bn": "আপনার খরচের হিসাব খুলে দিলাম।"},
    "explore": {"hi": "Explore khol diya.", "en": "Opened explore.", "bn": "এক্সপ্লোর খুলে দিলাম।"},
    "guide": {"hi": "Tour guide khol diya.", "en": "Opened the tour guide.", "bn": "ট্যুর গাইড খুলে দিলাম।"},
    "saved_places": {"hi": "Saved places khol diye.", "en": "Opened your saved places.", "bn": "আপনার সেভ করা জায়গাগুলো খুলে দিলাম।"},
    "more": {"hi": "Settings khol di.", "en": "Opened more options.", "bn": "সেটিংস খুলে দিলাম।"},
    "plan_trip": {"hi": "Nayi trip ka page khol diya.", "en": "Opened a new trip.", "bn": "নতুন ট্রিপের পেজ খুলে দিলাম।"},
}

NO_TRIP_REPLY = {"hi": "Abhi koi trip khuli nahi hai, aapki trips khol raha hoon.",
                 "en": "No trip is open, opening your trips.", "bn": "এখন কোনো ট্রিপ খোলা নেই, আপনার ট্রিপগুলো খুলছি।"}
WHICH_PAGE_REPLY = {"hi": "Kaunsa page kholun?", "en": "Which page should I open?", "bn": "কোন পেজ খুলব?"}


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
    from voice.languages import tkey
    lang = tkey(lang)
    if page == "itinerary" and day is not None:
        return CONFIRM["itinerary_day"][lang].format(n=day)
    return CONFIRM[page][lang]
