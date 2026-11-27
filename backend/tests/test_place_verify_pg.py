"""
Place verification, database part, on a THROWAWAY LOCAL Postgres database (voyage_verify_ci), never Neon, never
voice_test. The local user/host come from VOICE_DEBUG_DATABASE_URL in backend/.env (the password is never printed);
the script aborts unless the host is localhost / 127.0.0.1. Dropped at the end.
Checks: init_db adds itinerary_activities.place_id / verify_status to an older table (and keeps existing rows NULL);
the rollback SQL in docs/place_verify.sql works; init_db then adds them back.
Run from backend/: python -m tests.test_place_verify_pg
"""
import os
import sys
import uuid
from pathlib import Path

import dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
LOCAL_HOSTS = ("localhost", "127.0.0.1")
CI_DB = "voyage_verify_ci"

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
        return {r[0] for r in c.execute(sql("SELECT column_name FROM information_schema.columns "
                                            "WHERE table_name = 'itinerary_activities'"))}


try:
    import database  # noqa: E402
    check("engine points at the local throwaway database", database.engine.url.host in LOCAL_HOSTS
          and database.engine.url.database == CI_DB, f"{database.engine.url.host}/{database.engine.url.database}")
    database.init_db()
    eng = database.engine
    check("init_db on a new database: both columns", {"place_id", "verify_status"} <= cols(eng))

    # an older table: the columns dropped (= the rollback SQL), one existing row
    rollback = [line.lstrip("- ").strip() for line in (BACKEND_DIR.parent / "docs" / "place_verify.sql").read_text().splitlines()
                if line.startswith("-- ALTER TABLE")]
    check("docs: the rollback SQL is two DROP COLUMN statements", len(rollback) == 2 and all("DROP COLUMN IF EXISTS" in s for s in rollback), rollback)
    with eng.begin() as c:
        for stmt in rollback:
            c.execute(sql(stmt))
    check("rollback SQL removes both columns", not ({"place_id", "verify_status"} & cols(eng)))
    with eng.begin() as c:
        c.execute(sql("SET LOCAL session_replication_role = replica"))   # throwaway DB: no parent trip / user rows
        c.execute(sql("INSERT INTO itineraries (id, trip_id, version, status, created_at, updated_at) "
                      "VALUES ('itin_old', 'trip_old', 1, 'READY', 'now', 'now')"))
        c.execute(sql("INSERT INTO itinerary_days (id, itinerary_id, day_number, date, title) "
                      "VALUES ('day_old', 'itin_old', 1, '2026-12-01', 'Old')"))
        c.execute(sql("INSERT INTO itinerary_activities (id, day_id, time_slot, title, location_name) "
                      "VALUES ('act_old', 'day_old', '10:00 AM', 'Old stop', 'Somewhere')"))
    database.init_db()
    check("init_db adds place_id and verify_status to the older table", {"place_id", "verify_status"} <= cols(eng))
    with eng.connect() as c:
        old = c.execute(sql("SELECT place_id, verify_status, title FROM itinerary_activities WHERE id = 'act_old'")).one()
    check("the existing row stays (NULL, NULL), nothing else changed", tuple(old) == (None, None, "Old stop"), tuple(old))
    database.init_db()
    check("init_db again: no error, columns still there", {"place_id", "verify_status"} <= cols(eng))
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
