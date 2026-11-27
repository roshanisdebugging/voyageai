-- Booking stage 3: booking_requests (PostgreSQL). database.init_db() creates the same objects via create_all
-- unless SKIP_BOOKING_TABLE_CREATE=true. Use this file to create or roll back by hand.

-- ---------- create
CREATE SEQUENCE IF NOT EXISTS booking_request_no_seq START WITH 1001;

CREATE TABLE IF NOT EXISTS booking_requests (
    id             VARCHAR PRIMARY KEY,
    request_seq    INTEGER NOT NULL UNIQUE,
    request_no     VARCHAR NOT NULL UNIQUE,              -- 'BR-' || request_seq
    trip_id        VARCHAR NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
    user_id        VARCHAR NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
    status         VARCHAR NOT NULL DEFAULT 'new',       -- new | contacted | booked | cancelled
    services       JSONB NOT NULL,
    preferences    JSONB NOT NULL,
    travellers     JSONB NOT NULL,
    phone          VARCHAR(10) NOT NULL,
    partner_note   TEXT,
    consent_text   TEXT NOT NULL,
    consented_at   TIMESTAMPTZ NOT NULL,
    notify_status  VARCHAR NOT NULL DEFAULT 'pending',   -- off | pending | sending | sent | failed (stage 4)
    notified_at    TIMESTAMPTZ,                          -- when the partner email was sent
    notify_error   VARCHAR(20),                          -- auth | timeout | connection | recipient | smtp | config | other
    created_at     TIMESTAMPTZ NOT NULL,
    updated_at     TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_booking_requests_trip_id ON booking_requests (trip_id);
CREATE INDEX IF NOT EXISTS ix_booking_requests_user_id ON booking_requests (user_id);

-- One OPEN request per trip (new / contacted); booked and cancelled are closed.
CREATE UNIQUE INDEX IF NOT EXISTS uq_booking_requests_open_trip
    ON booking_requests (trip_id) WHERE status IN ('new', 'contacted');

-- Stage 4 on a table created before it (init_db runs these too, unless SKIP_BOOKING_TABLE_CREATE=true):
ALTER TABLE booking_requests ADD COLUMN IF NOT EXISTS notified_at TIMESTAMPTZ;
ALTER TABLE booking_requests ADD COLUMN IF NOT EXISTS notify_error VARCHAR(20);

-- ---------- rollback (drops every booking request!)
-- DROP INDEX IF EXISTS uq_booking_requests_open_trip;
-- DROP TABLE IF EXISTS booking_requests;
-- DROP SEQUENCE IF EXISTS booking_request_no_seq;
