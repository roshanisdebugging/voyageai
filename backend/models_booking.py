"""
Booking stage 3: a confirmed booking request (booking_requests).

Created like the other tables by database.init_db() (create_all), except when SKIP_BOOKING_TABLE_CREATE=true:
then init_db leaves this table, its sequence and its index out (e.g. while the app points at a shared database).
SQL to create / drop it by hand: docs/booking_requests.sql.

One OPEN request per trip is enforced by the database: a partial unique index on trip_id where the status is
new or contacted. booked and cancelled are closed, so a new request is allowed after them.
"""
from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, Sequence, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON

from database import Base

TABLE = "booking_requests"
STATUSES = ("new", "contacted", "booked", "cancelled")
OPEN_STATUSES = ("new", "contacted")
FIRST_NUMBER = 1001
REQUEST_NO_SEQ = Sequence("booking_request_no_seq", start=FIRST_NUMBER)   # created with the table (Postgres)

_JSON = JSON().with_variant(JSONB(), "postgresql")
_OPEN_WHERE = text("status IN ('new', 'contacted')")


class BookingRequestModel(Base):
    __tablename__ = TABLE

    id = Column(String, primary_key=True)                                  # "brq_<hex>"
    request_seq = Column(Integer, REQUEST_NO_SEQ, nullable=False, unique=True)
    request_no = Column(String, nullable=False, unique=True)              # "BR-1001", "BR-1002", ...
    trip_id = Column(String, ForeignKey("trips.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("auth_users.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String, nullable=False, default="new", server_default="new")
    services = Column(_JSON, nullable=False)                               # ["train", "hotel"]
    preferences = Column(_JSON, nullable=False)                            # answers to the service questions
    travellers = Column(_JSON, nullable=False)                             # [{"name": ..., "age": ...}]
    phone = Column(String(10), nullable=False)                             # cleaned 10 digits
    partner_note = Column(Text, nullable=True)                             # the 60+ ages line, if any
    consent_text = Column(Text, nullable=False)
    consented_at = Column(DateTime(timezone=True), nullable=False)
    notify_status = Column(String, nullable=False, default="pending", server_default="pending")   # the email step
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("uq_booking_requests_open_trip", "trip_id", unique=True,
              postgresql_where=_OPEN_WHERE, sqlite_where=_OPEN_WHERE),
    )
