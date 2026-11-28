"""The fixed itinerary inputs behind the golden prompts (itinerary_prompt_<name>.txt)."""

_BASE = {
    "destination": {"name": "Bengaluru", "country": "India", "latitude": 12.97, "longitude": 77.59},
    "startDate": "2026-12-13",
    "endDate": "2026-12-15",
    "totalDays": 3,
    "travelersCount": 2,
    "adultsCount": 2,
    "childrenCount": 0,
    "budget": {"level": "PREMIUM", "targetAmount": 60000, "currency": "INR"},
    "preferencesSnapshot": {"travelStyles": ["LUXURY", "NIGHTLIFE"]},
}

GOLDEN_INPUTS = {
    "no_origin": dict(_BASE, origin=None),
    "origin": dict(_BASE, origin={"name": "Kolkata", "region": "West Bengal"}),
}
