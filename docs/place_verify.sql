-- Place verification (backend/place_verify.py): two nullable columns on itinerary_activities.
-- database.init_db() adds them on startup (ALTER ... ADD COLUMN IF NOT EXISTS). Existing rows stay NULL
-- (= not checked); no backfill. NULL place_id / verify_status is how every older activity looks.

-- ---------- add (what init_db runs)
ALTER TABLE itinerary_activities ADD COLUMN IF NOT EXISTS place_id VARCHAR;
ALTER TABLE itinerary_activities ADD COLUMN IF NOT EXISTS verify_status VARCHAR;   -- verified | not_found | far

-- ---------- rollback (drops the stored place ids and statuses; activities themselves are untouched)
-- ALTER TABLE itinerary_activities DROP COLUMN IF EXISTS verify_status;
-- ALTER TABLE itinerary_activities DROP COLUMN IF EXISTS place_id;
