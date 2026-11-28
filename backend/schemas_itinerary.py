from pydantic import BaseModel, Field
from typing import List, Optional

class ActivitySchema(BaseModel):
    timeSlot: str
    title: str
    description: str
    activityType: str = "SIGHTSEEING"
    locationName: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    estimatedCostInr: int = 0
    bookingRequired: bool = False
    isConfirmed: bool = False  # Strictly forced to False for recommendations
    # Work / event trips only (itinerary_service PURPOSE RULES): "STAY" = the stay line (our code puts in the real
    # hotel near the base area), "EVENT" = the event itself (our code writes it, no invented venue or time).
    planSlot: Optional[str] = None

class DaySchema(BaseModel):
    dayNumber: int
    date: str
    title: str
    summary: str
    activities: List[ActivitySchema]

class TransportSuggestionSchema(BaseModel):
    """How to get from the starting city to the destination, chosen by the AI to fit the budget."""
    mode: str                      # TRAIN, FLIGHT, BUS, CAB
    description: str               # e.g. "Shatabdi Express from New Delhi"
    fromLocation: str
    toLocation: str
    estimatedFareInr: int = 0      # per person, one way
    durationText: Optional[str] = None
    reason: Optional[str] = None   # why this fits the budget


class GeneratedItinerarySchema(BaseModel):
    title: str
    days: List[DaySchema]
    transportSuggestions: List[TransportSuggestionSchema] = Field(default_factory=list)
