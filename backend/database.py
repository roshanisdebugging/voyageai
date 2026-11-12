import os
from contextlib import contextmanager
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base

load_dotenv(override=True)

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    DB_USER = os.getenv("DB_USER", "postgres")
    DB_PASS = os.getenv("DB_PASS", "7044")
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

        Base.metadata.create_all(bind=engine)

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
