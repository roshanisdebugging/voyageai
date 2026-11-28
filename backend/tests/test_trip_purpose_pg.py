"""
Trip purpose, database part, on a THROWAWAY LOCAL Postgres database (voyage_purpose_ci), never Neon, never voice_test.
The local user/host come from VOICE_DEBUG_DATABASE_URL in backend/.env (read only, the password is never printed);
the script aborts unless the host is localhost / 127.0.0.1. Dropped at the end.
Checks: init_db adds trips.purpose_type / purpose_text / base_area_json to an older table (existing rows stay NULL);
the rollback SQL in docs/trip_purpose.sql works; init_db then adds them back; an old trip without them serializes
with purposeType / purposeText / baseArea = null; a new one round-trips.
Run from backend/: python -m tests.test_trip_purpose_pg
"""
import os
import sys
from pathlib import Path

import dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
LOCAL_HOSTS = ("localhost", "127.0.0.1")
CI_DB = "voyage_purpose_ci"
COLS = {"purpose_type", "purpose_text", "base_area_json"}

_local = dotenv.dotenv_values(BACKEND_DIR / ".env").get("VOICE_DEBUG_DATABASE_URL")
from sqlalchemy.engine import make_url  # noqa: E402

if not _local:
    sys.exit("ABORT: VOICE_DEBUG_DATABASE_URL (the local Postgres) is not in backend/.env")
_base = make_url(_local)
if _base.host not in LOCAL_HOSTS:
    sys.exit(f"ABORT: host {_base.host!r} is not localhost/127.0.0.1")
CI_URL = _base.set(database=CI_DB)
print(f"database host={CI_URL.host} port={CI_URL.port} name={CI_URL.database}  (local only; password not shown)")

dotenv.load_dotenv = lambda *a, **k: None          # database.py must not load backend/.env (it points at Neon)
os.environ["DATABASE_URL"] = CI_URL.render_as_string(hide_password=False)
os.environ.pop("SKIP_BOOKING_TABLE_CREATE", None)
os.environ["AI_PROVIDER"] = "mock"
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)

from sqlalchemy import create_engine, text as sql  # noqa: E402

_admin = create_engine(_base.set(database="postgres"), isolation_level="AUTOCOMMIT")
with _admin.connect() as c:
    c.execute(sql(f'DROP DATABASE IF EXISTS "{CI_DB}" WITH (FORCE)'))
    c.execute(sql(f'CREATE DATABASE "{CI_DB}"'))

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail != "" else ""), flush=True)


def cols(engine):
    with engine.connect() as c:
        return {r[0] for r in c.execute(sql("SELECT column_name FROM information_schema.columns WHERE table_name = 'trips'"))}


try:
    import database  # noqa: E402
    check("engine points at the local throwaway database", database.engine.url.host in LOCAL_HOSTS
          and database.engine.url.database == CI_DB, f"{database.engine.url.host}/{database.engine.url.database}")
    database.init_db()
    eng = database.engine
    check("init_db on a new database: the three columns", COLS <= cols(eng))
    with eng.connect() as c:
        width = c.execute(sql("SELECT character_maximum_length FROM information_schema.columns "
                              "WHERE table_name = 'trips' AND column_name = 'purpose_text'")).scalar()
    check("purpose_text is VARCHAR(120)", width == 120, width)

    rollback = [line.lstrip("- ").strip() for line in (BACKEND_DIR.parent / "docs" / "trip_purpose.sql").read_text().splitlines()
                if line.startswith("-- ALTER TABLE")]
    check("docs: the rollback SQL is three DROP COLUMN statements",
          len(rollback) == 3 and all("DROP COLUMN IF EXISTS" in s for s in rollback), rollback)
    with eng.begin() as c:
        for stmt in rollback:
            c.execute(sql(stmt))
    check("rollback SQL removes the three columns", not (COLS & cols(eng)))
    with eng.begin() as c:
        c.execute(sql("SET LOCAL session_replication_role = replica"))   # throwaway DB: no parent user row
        c.execute(sql("INSERT INTO trips (id, user_id, title, start_date, end_date, total_days, destination_json, "
                      "travelers_json, created_at, updated_at) VALUES ('trip_old', 'usr_old', 'Old', '2026-12-01', "
                      "'2026-12-02', 2, '{\"name\": \"Goa\"}', '[]', 'now', 'now')"))
    database.init_db()
    check("init_db adds the three columns to the older table", COLS <= cols(eng))
    with eng.connect() as c:
        old = c.execute(sql("SELECT purpose_type, purpose_text, base_area_json, title FROM trips WHERE id = 'trip_old'")).one()
    check("the existing trip stays (NULL, NULL, NULL), nothing else changed", tuple(old) == (None, None, None, "Old"), tuple(old))

    from models_trip import TripModel  # noqa: E402
    from trip_lifecycle import serialize_trip  # noqa: E402
    with database.SessionLocal() as db:
        t = db.query(TripModel).filter(TripModel.id == "trip_old").one()
        s = serialize_trip(t, db)
        check("an old trip serializes with null purpose fields", s["purposeType"] is None and s["purposeText"] is None
              and s["baseArea"] is None and s["title"] == "Old")
        t.purpose_type, t.purpose_text = "event", "hackathon ke liye"
        t.base_area = {"id": "ChIJec", "name": "Electronic City", "city": "Bengaluru", "latitude": 12.84, "longitude": 77.66}
        db.commit()
        s = serialize_trip(db.query(TripModel).filter(TripModel.id == "trip_old").one(), db)
        check("purpose and base area round-trip", s["purposeType"] == "event" and s["purposeText"] == "hackathon ke liye"
              and s["baseArea"]["name"] == "Electronic City" and s["baseArea"]["latitude"] == 12.84, s["baseArea"])
    database.init_db()
    check("init_db again: no error, columns still there", COLS <= cols(eng))
    print(f"host used: {eng.url.host} / database: {eng.url.database}")
finally:
    try:
        import database
        database.engine.dispose()
    except Exception:
        pass
    with _admin.connect() as c:
        c.execute(sql(f'DROP DATABASE IF EXISTS "{CI_DB}" WITH (FORCE)'))
        gone = not c.execute(sql("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": CI_DB}).first()
    print(f"throwaway database {CI_DB} dropped: {gone}")

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if results and all(results) else 1)
