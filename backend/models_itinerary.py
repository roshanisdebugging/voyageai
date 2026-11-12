import json
from sqlalchemy import Column, String, Integer, Float, Boolean, Text, ForeignKey
from database import Base

class ItineraryModel(Base):
    __tablename__ = "itineraries"

    id = Column(String, primary_key=True, index=True)
    trip_id = Column(String, ForeignKey("trips.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, default=1, nullable=False)
    status = Column(String, default="GENERATING")             # GENERATING, READY, FAILED
    provider_name = Column(String, default="MOCK_PROVIDER")   # MOCK_PROVIDER, FUTURE_PROVIDER
    error_message = Column(String, nullable=True)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)

class ItineraryDayModel(Base):
    __tablename__ = "itinerary_days"

    id = Column(String, primary_key=True, index=True)
    itinerary_id = Column(String, ForeignKey("itineraries.id", ondelete="CASCADE"), nullable=False, index=True)
    day_number = Column(Integer, nullable=False)
    date = Column(String, nullable=False)
    title = Column(String, nullable=False)
    summary = Column(Text, nullable=True)

class ItineraryActivityModel(Base):
    __tablename__ = "itinerary_activities"

    id = Column(String, primary_key=True, index=True)
    day_id = Column(String, ForeignKey("itinerary_days.id", ondelete="CASCADE"), nullable=False, index=True)
    time_slot = Column(String, nullable=False)               # e.g. "10:00 AM", "01:00 PM"
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    activity_type = Column(String, default="SIGHTSEEING")     # SIGHTSEEING, DINING, RELAXATION, TRANSIT
    location_name = Column(String, nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    estimated_cost_inr = Column(Integer, default=0)
    booking_required = Column(Boolean, default=False)
    is_confirmed = Column(Boolean, default=False)             # ALWAYS False for AI recommendations
    is_done = Column(Boolean, default=False)                  # traveler marked it as done
    booking_reference_id = Column(String, nullable=True)
