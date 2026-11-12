import json
from sqlalchemy import Column, String, Integer, Text, ForeignKey
from database import Base
import models_place  # noqa: F401  (registers the cities table for the origin_city_id foreign key)

class TripModel(Base):
    __tablename__ = "trips"

    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("auth_users.id"), nullable=False, index=True)
    client_request_id = Column(String, nullable=True, index=True) # Idempotency guard
    origin_city_id = Column(String, ForeignKey("cities.id"), nullable=True)  # starting city
    title = Column(String, nullable=False)
    status = Column(String, default="PLANNING")                   # PLANNING, UPCOMING, ACTIVE, COMPLETED, CANCELLED, ARCHIVED
    itinerary_status = Column(String, default="GENERATING")       # GENERATING, READY, FAILED
    start_date = Column(String, nullable=False)
    end_date = Column(String, nullable=False)
    total_days = Column(Integer, nullable=False, default=1)
    destination_json = Column(Text, nullable=False)              # JSON representation of DestinationReference
    cover_media_json = Column(Text, default="{}")                # Server-resolved MediaContract
    travelers_json = Column(Text, nullable=False)                # JSON representation of List[TripTraveler]
    preferences_snapshot_json = Column(Text, default="{}")       # Immutable UserPreferences Snapshot
    budget_json = Column(Text, default="{}")                     # BudgetModel (level, target_amount, currency)
    progress_json = Column(Text, default="{}")
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)

    @property
    def destination(self):
        return json.loads(self.destination_json or "{}")

    @destination.setter
    def destination(self, val):
        self.destination_json = json.dumps(val or {})

    @property
    def cover_media(self):
        return json.loads(self.cover_media_json or "{}")

    @cover_media.setter
    def cover_media(self, val):
        self.cover_media_json = json.dumps(val or {})

    @property
    def travelers(self):
        return json.loads(self.travelers_json or "[]")

    @travelers.setter
    def travelers(self, val):
        self.travelers_json = json.dumps(val or [])

    @property
    def preferences_snapshot(self):
        return json.loads(self.preferences_snapshot_json or "{}")

    @preferences_snapshot.setter
    def preferences_snapshot(self, val):
        self.preferences_snapshot_json = json.dumps(val or {})

    @property
    def budget(self):
        return json.loads(self.budget_json or "{}")

    @budget.setter
    def budget(self, val):
        self.budget_json = json.dumps(val or {})

    @property
    def progress(self):
        return json.loads(self.progress_json or "{}")

    @progress.setter
    def progress(self, val):
        self.progress_json = json.dumps(val or {})

