import os
from contextlib import contextmanager
from dotenv import load_dotenv
import time as _t
from sqlalchemy import create_engine, text, event
from prometheus_client import Histogram

DB_QUERY_DURATION = Histogram(
    "db_query_duration_seconds",
    "Duration of SQL statements executed against Postgres",
    ["operation"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
from sqlalchemy.orm import sessionmaker, declarative_base

load_dotenv(override=True)

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    DB_USER = os.getenv("DB_USER", "postgres")
    DB_PASS = os.getenv("DB_PASS", "")  # never hard-code a password here; set DB_PASS or DATABASE_URL in backend/.env
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = os.getenv("DB_PORT", "5432")
    DB_NAME = os.getenv("DB_NAME", "voyageai")
    DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# ============================================================================
# Single Unified Engine (Thread-safe, pooled, pre-ping enabled)
# ============================================================================
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,       # Pings Neon before each query; auto-reconnects if dead
    pool_recycle=300,         # Recycles connections every 5 minutes (before Neon drops them)
    pool_size=10,             # Keep connection pool clean
    max_overflow=20,          # Up to 30 connections during bursts
    pool_timeout=15,          # Fail fast instead of hanging forever
    connect_args={
        "connect_timeout": 10,
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 5
    }
)

# Instrument every SQL statement for Prometheus (duration by operation type).
@event.listens_for(engine, "before_cursor_execute")
def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    context._prom_start = _t.perf_counter()

@event.listens_for(engine, "after_cursor_execute")
def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    try:
        dur = _t.perf_counter() - getattr(context, "_prom_start", _t.perf_counter())
        op = (statement or "").strip().split()[:1]
        op = op[0].upper() if op else "OTHER"
        DB_QUERY_DURATION.labels(operation=op).observe(dur)
    except Exception:
        pass

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ----------------------------------------------------------------------------
# 1. ORM Dependency for standard HTTP routes
# ----------------------------------------------------------------------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        try:
            db.rollback()
        except Exception:
            try:
                db.invalidate()
            except Exception:
                pass
        raise
    finally:
        try:
            db.close()
        except Exception:
            try:
                db.invalidate()
            except Exception:
                pass

# ----------------------------------------------------------------------------
# 2. Context Manager for WebSocket frames / Background tasks
# ----------------------------------------------------------------------------
@contextmanager
def get_db_context():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            try:
                db.invalidate()
            except Exception:
                pass
        raise
    finally:
        try:
            db.close()
        except Exception:
            try:
                db.invalidate()
            except Exception:
                pass

# ----------------------------------------------------------------------------
# 3. High-Speed Raw SQL Connection (Replaces psycopg2 ThreadedPool)
# ----------------------------------------------------------------------------
@contextmanager
def get_raw_connection():
    """Ultra-fast raw connection straight from SQLAlchemy's pool"""
    with engine.connect() as conn:
        yield conn
        conn.commit()

# ----------------------------------------------------------------------------
# 4. Schema Initialization
# ----------------------------------------------------------------------------
def init_db():
    """Boot-time schema sync, model registration, and indexing"""
    try:
        # Explicitly import all ORM models so Base.metadata is completely populated
        import models_db       # auth_users, user_profiles, user_preferences, sessions
        import models_trip     # trips
        import models_itinerary  # itineraries, itinerary_days, itinerary_activities
        import models_package  # trip_stays, trip_transports, trip_expenses
        import models_chat     # chat_messages
        import models_place    # cities
        import models_booking  # booking_requests (booking stage 3)

        # SKIP_BOOKING_TABLE_CREATE=true leaves booking_requests (with its sequence and open-request index) out,
        # e.g. while this checkout runs against a shared database. Unset = created like every other table.
        if os.getenv("SKIP_BOOKING_TABLE_CREATE", "").strip().lower() == "true":
            tables = [t for t in Base.metadata.sorted_tables if t.name != models_booking.TABLE]
            Base.metadata.create_all(bind=engine, tables=tables)
            print("[DATABASE INIT] booking_requests skipped (SKIP_BOOKING_TABLE_CREATE=true)")
        else:
            Base.metadata.create_all(bind=engine)
            if engine.dialect.name == "postgresql":     # columns added later (create_all doesn't add them)
                with engine.begin() as conn:
                    for col, sql_type in models_booking.ADDED_COLUMNS:
                        conn.execute(text(f"ALTER TABLE {models_booking.TABLE} ADD COLUMN IF NOT EXISTS {col} {sql_type}"))

        with engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id VARCHAR(64) PRIMARY KEY,
                    user_id VARCHAR(64) NOT NULL,
                    trip_id VARCHAR(64),
                    role VARCHAR(16) NOT NULL,
                    content TEXT NOT NULL,
                    mode VARCHAR(16) DEFAULT 'local',
                    metadata JSONB DEFAULT '{}'::jsonb,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );

                ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'::jsonb;

                CREATE INDEX IF NOT EXISTS idx_chat_user_created 
                ON chat_messages (user_id, created_at ASC);

                CREATE INDEX IF NOT EXISTS idx_chat_trip 
                ON chat_messages (trip_id) WHERE trip_id IS NOT NULL;

                CREATE INDEX IF NOT EXISTS idx_sessions_token_hash 
                ON sessions (token_hash);

                CREATE INDEX IF NOT EXISTS idx_sessions_user_id 
                ON sessions (user_id);

                CREATE INDEX IF NOT EXISTS idx_trips_user_id 
                ON trips (user_id);

                ALTER TABLE auth_users ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255);

                ALTER TABLE trips ADD COLUMN IF NOT EXISTS origin_city_id VARCHAR REFERENCES cities(id);

                ALTER TABLE itinerary_activities ADD COLUMN IF NOT EXISTS is_done BOOLEAN DEFAULT FALSE;

                CREATE TABLE IF NOT EXISTS saved_places (
                    id VARCHAR PRIMARY KEY,
                    user_id VARCHAR NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
                    place_id VARCHAR NOT NULL,
                    title VARCHAR NOT NULL,
                    category VARCHAR,
                    rating NUMERIC(2, 1),
                    location_name VARCHAR,
                    distance_text VARCHAR,
                    duration_text VARCHAR,
                    cost_text VARCHAR,
                    description TEXT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    CONSTRAINT uq_user_place UNIQUE (user_id, place_id)
                );

                CREATE INDEX IF NOT EXISTS idx_saved_places_user_id ON saved_places(user_id);
            """))
            conn.commit()
            print(f"[DATABASE INIT] Neon schema sync complete. Registered tables: {sorted(Base.metadata.tables.keys())}")
    except Exception as e:
        print(f"[DATABASE INIT WARN] Schema init notice: {e}")

# ----------------------------------------------------------------------------
# 5. Connection Pool Telemetry & Diagnostics
# ----------------------------------------------------------------------------
def get_db_pool_status():
    """Returns real-time SQLAlchemy connection pool diagnostics."""
    if hasattr(engine, "pool"):
        return {
            "size": engine.pool.size(),
            "checked_in": engine.pool.checkedin(),
            "checked_out": engine.pool.checkedout(),
            "overflow": engine.pool.overflow(),
        }
    return {}
