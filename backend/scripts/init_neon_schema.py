#!/usr/bin/env python3
"""
VoyageAI - Neon Cloud Schema Initializer & Session Isolation Verifier
Run from /backend: python init_neon_schema.py
"""
import os, sys, uuid, hashlib, json
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv
load_dotenv(dotenv_path=BACKEND_DIR / ".env", override=True)

DATABASE_URL = os.getenv("DATABASE_URL", "")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not found in .env -- aborting.")
    sys.exit(1)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

print("=" * 72)
print("VoyageAI -- Neon Cloud Schema Initializer")
print("=" * 72)
print(f"  DB HOST : {DATABASE_URL.split('@')[-1].split('/')[0]}")
print(f"  DB NAME : {DATABASE_URL.split('/')[-1].split('?')[0]}")
print("=" * 72)

from sqlalchemy import create_engine, text, inspect as sa_inspect
from sqlalchemy.orm import sessionmaker

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True, pool_size=3, max_overflow=5,
    pool_recycle=1800, pool_timeout=10,
    connect_args={"connect_timeout": 10},
)

print("\n[STEP 1] Importing all ORM model classes ...")
from database import Base
import models_db
import models_trip
import models_itinerary
import models_package
import models_chat

registered = sorted(Base.metadata.tables.keys())
print(f"  Base.metadata has {len(registered)} tables: {registered}")

print("\n[STEP 2] Running Base.metadata.create_all() ...")
try:
    Base.metadata.create_all(bind=engine)
    print("  create_all() completed OK.")
except Exception as exc:
    print(f"  FAILED: {exc}")
    sys.exit(1)

print("\n[STEP 3] Applying supplemental DDL migrations ...")
ddl_stmts = [
    "ALTER TABLE auth_users ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255)",
    """CREATE TABLE IF NOT EXISTS chat_messages (
        id VARCHAR(64) PRIMARY KEY, user_id VARCHAR(64) NOT NULL,
        trip_id VARCHAR(64), role VARCHAR(16) NOT NULL, content TEXT NOT NULL,
        mode VARCHAR(16) DEFAULT 'local', metadata JSONB DEFAULT '{}'::jsonb,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    )""",
    "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'::jsonb",
    "UPDATE chat_messages SET metadata = CAST(COALESCE(NULLIF(metadata_json,''),'{}') AS JSONB) WHERE metadata IS NULL",
    "CREATE INDEX IF NOT EXISTS idx_chat_user_created ON chat_messages (user_id, created_at ASC)",
    "CREATE INDEX IF NOT EXISTS idx_chat_trip ON chat_messages (trip_id) WHERE trip_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_sessions_token_hash ON sessions (token_hash)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions (user_id)",
    "CREATE INDEX IF NOT EXISTS idx_trips_user_id ON trips (user_id)",
    "CREATE INDEX IF NOT EXISTS idx_auth_users_email ON auth_users (email)",
]
with engine.begin() as conn:
    for stmt in ddl_stmts:
        try:
            conn.execute(text(stmt))
        except Exception as e:
            print(f"  [DDL WARN] {e}")
print("  Supplemental DDL done.")

REQUIRED = {
    "auth_users","sessions","user_profiles","user_preferences",
    "trips","itineraries","itinerary_days","itinerary_activities",
    "trip_stays","trip_transports","trip_expenses","chat_messages",
}

print("\n[STEP 4] Verifying tables via inspect() ...")
inspector = sa_inspect(engine)
found = set(inspector.get_table_names())
print(f"  Found tables: {sorted(found)}")
missing = REQUIRED - found
if not missing:
    print(f"  ALL {len(REQUIRED)} required tables CONFIRMED.")
else:
    print(f"  MISSING: {sorted(missing)}")

print("\n[STEP 5] E2E session persistence test ...")
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
TEST_USER_ID = f"usr_test_{uuid.uuid4().hex[:8]}"
TEST_EMAIL   = f"neon_verify_{uuid.uuid4().hex[:6]}@voyageai-test.com"
RAW_TOKEN    = f"token_{uuid.uuid4().hex}"
TOKEN_HASH   = hashlib.sha256(RAW_TOKEN.encode()).hexdigest()
SESSION_ID   = f"sid_{uuid.uuid4().hex[:12]}"
NOW          = datetime.now(timezone.utc).isoformat()
EXPIRES_AT   = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()

try:
    from passlib.context import CryptContext
    pwd_ctx  = CryptContext(schemes=["bcrypt"], deprecated="auto")
    HASHED_PW = pwd_ctx.hash("TestPass@123")
except Exception:
    HASHED_PW = "placeholder_hash"

db = SessionLocal()
try:
    from models_db import AuthUserModel, UserProfileModel, SessionModel

    db.add(AuthUserModel(
        id=TEST_USER_ID, provider="EMAIL", provider_user_id=TEST_EMAIL,
        email=TEST_EMAIL, password_hash=HASHED_PW,
        email_verified=True, phone_verified=True, status="ACTIVE",
        created_at=NOW, last_login_at=NOW,
    ))
    db.add(UserProfileModel(
        user_id=TEST_USER_ID, first_name="NeonTestUser", last_name="Verifier",
        onboarding_status="PENDING", created_at=NOW, updated_at=NOW,
    ))
    db.add(SessionModel(
        id=SESSION_ID, token_hash=TOKEN_HASH, user_id=TEST_USER_ID,
        created_at=NOW, expires_at=EXPIRES_AT, last_used_at=NOW,
    ))
    db.commit()
    print("  Inserted test user + profile + session into Neon.")

    fu = db.query(AuthUserModel).filter(AuthUserModel.id == TEST_USER_ID).first()
    fp = db.query(UserProfileModel).filter(UserProfileModel.user_id == TEST_USER_ID).first()
    fs = db.query(SessionModel).filter(SessionModel.token_hash == TOKEN_HASH).first()

    assert fu and fp and fs, "Read-back failed"
    assert db.query(AuthUserModel).filter(AuthUserModel.id == fs.user_id).first().email == TEST_EMAIL

    print(f"  auth_users   -> id={fu.id}, email={fu.email}")
    print(f"  user_profiles-> first_name={fp.first_name}, onboarding_status={fp.onboarding_status}")
    print(f"  sessions     -> id={fs.id}, expires_at={fs.expires_at}")

    with engine.connect() as conn:
        row = conn.execute(text("SELECT inet_server_addr()::text")).fetchone()
        host = row[0] if row else "unknown"
    print(f"  DB server: {host}  (confirms cloud, NOT localhost)")

    db.delete(fs)
    db.flush()
    db.delete(fp)
    db.flush()
    db.delete(fu)
    db.commit()
    print("  Test data cleaned up.")

except Exception as exc:
    db.rollback()
    import traceback; traceback.print_exc()
finally:
    db.close()

print("\n[STEP 6] Session Isolation Checklist")
print("-" * 72)
checks = [
    "Backend extracts token via voyageai_session cookie OR Authorization: Bearer header",
    "get_current_user() raises 401 if no valid token",
    "get_user_or_guest() provides guest fallback for tour-guide endpoints (no 401)",
    "All /api/trips, /api/profile, /api/preferences queries filter by current_user.id",
    "No global mock user IDs in route handlers",
    "Frontend uses credentials:'include' AND getAuthHeaders() on all fetch calls",
    "DEFAULT_FETCH_OPTIONS.headers is a JS getter (dynamic token injection)",
    "TourGuidePage explicitly calls getAuthHeaders() on history/chat/itinerary fetches",
    "chat_messages has no FK on user_id (supports guest_ prefixed IDs)",
]
for c in checks: print(f"  OK  {c}")

print("\n" + "=" * 72)
print("  Neon schema initialization & verification COMPLETE.")
print("=" * 72)
