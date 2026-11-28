-- Trip purpose and base area (backend/trip_purpose.py): three nullable columns on trips.
-- database.init_db() adds them on startup (ALTER ... ADD COLUMN IF NOT EXISTS). Existing trips stay NULL
-- (= no purpose given: planned exactly as before); no backfill.

-- ---------- add (what init_db runs)
ALTER TABLE trips ADD COLUMN IF NOT EXISTS purpose_type VARCHAR;          -- leisure | business | event | pilgrimage | other
ALTER TABLE trips ADD COLUMN IF NOT EXISTS purpose_text VARCHAR(120);     -- the user's own words (business / event / other)
ALTER TABLE trips ADD COLUMN IF NOT EXISTS base_area_json TEXT;           -- JSON {id, name, city, region, latitude, longitude}

-- ---------- rollback (drops the stored purpose and base area; the trips themselves are untouched)
-- ALTER TABLE trips DROP COLUMN IF EXISTS base_area_json;
-- ALTER TABLE trips DROP COLUMN IF EXISTS purpose_text;
-- ALTER TABLE trips DROP COLUMN IF EXISTS purpose_type;
