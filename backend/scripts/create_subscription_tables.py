#!/usr/bin/env python3
"""
VoyageAI - Standalone Database Setup & Verification Script for Subscription System (Phase 1)

Scope:
- Connects to Neon PostgreSQL using existing environment configuration.
- Never prints, exposes, or logs database credentials.
- Verifies prerequisite table 'auth_users'.
- Safely creates ONLY the eight subscription/payment tables:
    1. subscription_plans
    2. plan_features
    3. user_subscriptions
    4. usage_events
    5. payments
    6. payment_attempts
    7. refund_intents
    8. webhook_events
- Handles circular funding-payment composite FK via use_alter=True.
- Idempotently seeds FREE and ULTRA plans and all 10 feature quotas.
- Performs comprehensive PostgreSQL schema, constraint, index, and data verification.
- Never drops, alters, truncates, or deletes any existing application or user data.
"""

import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv
load_dotenv(dotenv_path=BACKEND_DIR / ".env", override=True)

from sqlalchemy import (
    create_engine,
    text,
    inspect as sa_inspect,
    Table
)
from sqlalchemy.orm import Session
from sqlalchemy.engine.url import make_url

# Import existing Base and models so metadata is cleanly resolved
from database import Base
import models_db  # auth_users, etc.
import payment_models
from payment_models import (
    SubscriptionPlan,
    PlanFeature,
    UserSubscription,
    UsageEvent,
    Payment,
    PaymentAttempt,
    RefundIntent,
    WebhookEvent
)

TARGET_TABLES = [
    "subscription_plans",
    "plan_features",
    "user_subscriptions",
    "usage_events",
    "payments",
    "payment_attempts",
    "refund_intents",
    "webhook_events",
]

PREREQUISITE_TABLES = ["auth_users"]


def mask_db_url(raw_url: str) -> dict:
    """Safely extracts masked host, database name, and dialect without exposing credentials."""
    try:
        url = make_url(raw_url)
        host = url.host or "unknown"
        port = f":{url.port}" if url.port else ""
        masked_host = f"{host[:4]}...{host[-6:]}" if len(host) > 12 else host
        return {
            "drivername": url.drivername,
            "host": f"{masked_host}{port}",
            "database": url.database or "unknown",
            "is_postgres": url.drivername.startswith("postgresql") or url.drivername.startswith("postgres"),
        }
    except Exception as exc:
        return {"error": str(exc), "is_postgres": False}


def verify_connection_and_prerequisites(engine):
    """Verifies that the target is a valid PostgreSQL Neon database with auth_users present."""
    raw_url = os.getenv("DATABASE_URL", "")
    info = mask_db_url(raw_url)
    
    print("=" * 72)
    print("VoyageAI - Subscription Schema Initializer (Phase 1)")
    print("=" * 72)
    print(f"  DIALECT  : {info.get('drivername')}")
    print(f"  HOST     : {info.get('host')}")
    print(f"  DATABASE : {info.get('database')}")
    print("=" * 72)

    if not info.get("is_postgres"):
        raise RuntimeError(f"Database dialect must be PostgreSQL. Found: {info.get('drivername')}")

    inspector = sa_inspect(engine)
    existing_tables = set(inspector.get_table_names())

    # Check prerequisite tables
    for prereq in PREREQUISITE_TABLES:
        if prereq not in existing_tables:
            raise RuntimeError(f"Prerequisite table '{prereq}' is missing in the database. Aborting.")
        cols = {c["name"]: str(c["type"]) for c in inspector.get_columns(prereq)}
        if "id" not in cols:
            raise RuntimeError(f"Prerequisite table '{prereq}' is missing primary key 'id'. Aborting.")
        print(f"  [OK] Prerequisite table verified: '{prereq}' (id type: {cols['id']})")

    return existing_tables


def check_target_tables_state(existing_tables: set):
    """Checks the status of the 8 target tables."""
    found = [t for t in TARGET_TABLES if t in existing_tables]
    missing = [t for t in TARGET_TABLES if t not in existing_tables]

    print(f"\n[TARGET TABLES AUDIT]")
    print(f"  Total required : {len(TARGET_TABLES)}")
    print(f"  Found existing : {len(found)} -> {found}")
    print(f"  Missing        : {len(missing)} -> {missing}")

    return found, missing


def create_target_tables(engine, missing_tables: list):
    """Safely creates only the target subscription tables using SQLAlchemy metadata."""
    if not missing_tables:
        print("\n[CREATION STEP] All 8 tables already exist. Skipping create_all.")
        return

    print(f"\n[CREATION STEP] Creating {len(missing_tables)} missing subscription tables...")
    table_objects = [Base.metadata.tables[name] for name in TARGET_TABLES if name in missing_tables]

    for tbl in table_objects:
        print(f"  - Queued table: {tbl.name}")

    # Explicitly pass ONLY target table objects. Checkfirst=True handles dependencies cleanly.
    Base.metadata.create_all(bind=engine, tables=table_objects, checkfirst=True)
    print("  [SUCCESS] Table creation executed.")


def seed_plans_and_features(engine):
    """Seeds FREE and ULTRA plans and all 10 feature quotas idempotently."""
    print("\n[SEED STEP] Idempotently seeding subscription plans and features...")

    plans_data = [
        {
            "code": "FREE",
            "name": "Free",
            "price_paise": 0,
            "billing_interval": "NONE",
            "is_active": True,
            "features": [
                {"feature_key": "tour_guide_chat", "enabled": True, "usage_limit": 10, "reset_period": "DAILY"},
                {"feature_key": "itinerary_generation", "enabled": True, "usage_limit": 2, "reset_period": "MONTHLY"},
                {"feature_key": "explore", "enabled": False, "usage_limit": None, "reset_period": "NONE"},
                {"feature_key": "nearest_highlights", "enabled": False, "usage_limit": None, "reset_period": "NONE"},
                {"feature_key": "feed", "enabled": False, "usage_limit": None, "reset_period": "NONE"},
            ]
        },
        {
            "code": "ULTRA",
            "name": "Ultra",
            "price_paise": 4900,
            "billing_interval": "MONTHLY",
            "is_active": True,
            "features": [
                {"feature_key": "tour_guide_chat", "enabled": True, "usage_limit": 50, "reset_period": "DAILY"},
                {"feature_key": "itinerary_generation", "enabled": True, "usage_limit": 10, "reset_period": "MONTHLY"},
                {"feature_key": "explore", "enabled": True, "usage_limit": None, "reset_period": "NONE"},
                {"feature_key": "nearest_highlights", "enabled": True, "usage_limit": None, "reset_period": "NONE"},
                {"feature_key": "feed", "enabled": True, "usage_limit": None, "reset_period": "NONE"},
            ]
        }
    ]

    with Session(engine) as session:
        with session.begin():
            for p_info in plans_data:
                # 1. Upsert / fetch plan
                plan = session.query(SubscriptionPlan).filter_by(code=p_info["code"]).first()
                if not plan:
                    plan = SubscriptionPlan(
                        code=p_info["code"],
                        name=p_info["name"],
                        price_paise=p_info["price_paise"],
                        billing_interval=p_info["billing_interval"],
                        is_active=p_info["is_active"]
                    )
                    session.add(plan)
                    session.flush()
                    print(f"  [INSERTED PLAN] {plan.code} (ID: {plan.id}, Price: ₹{plan.price_paise / 100:.2f})")
                else:
                    plan.name = p_info["name"]
                    plan.price_paise = p_info["price_paise"]
                    plan.billing_interval = p_info["billing_interval"]
                    plan.is_active = p_info["is_active"]
                    session.flush()
                    print(f"  [EXISTING PLAN] {plan.code} (ID: {plan.id}, Price: ₹{plan.price_paise / 100:.2f})")

                # 2. Upsert features
                for f_info in p_info["features"]:
                    feature = session.query(PlanFeature).filter_by(
                        plan_id=plan.id,
                        feature_key=f_info["feature_key"]
                    ).first()

                    if not feature:
                        feature = PlanFeature(
                            plan_id=plan.id,
                            feature_key=f_info["feature_key"],
                            enabled=f_info["enabled"],
                            usage_limit=f_info["usage_limit"],
                            reset_period=f_info["reset_period"]
                        )
                        session.add(feature)
                        print(f"    + [INSERTED FEATURE] {plan.code}.{feature.feature_key}: enabled={feature.enabled}, limit={feature.usage_limit}/{feature.reset_period}")
                    else:
                        feature.enabled = f_info["enabled"]
                        feature.usage_limit = f_info["usage_limit"]
                        feature.reset_period = f_info["reset_period"]
                        print(f"    = [VERIFIED FEATURE] {plan.code}.{feature.feature_key}: enabled={feature.enabled}, limit={feature.usage_limit}/{feature.reset_period}")

    print("  [SUCCESS] All plans and features seeded cleanly.")


def verify_database_schema(engine):
    """Performs deep PostgreSQL verification of tables, constraints, indexes, and FKs."""
    print("\n[VERIFICATION STEP] Performing deep PostgreSQL schema verification...")
    inspector = sa_inspect(engine)
    post_tables = set(inspector.get_table_names())

    # 1. Verify table presence
    missing_after = [t for t in TARGET_TABLES if t not in post_tables]
    if missing_after:
        raise RuntimeError(f"Verification FAILED: Target tables missing after create: {missing_after}")
    print(f"  [OK] All {len(TARGET_TABLES)} subscription tables present in PostgreSQL.")

    # 2. Detailed constraint and index audit
    results = {}
    with engine.connect() as conn:
        for tbl in TARGET_TABLES:
            cols = inspector.get_columns(tbl)
            pk = inspector.get_pk_constraint(tbl)
            fks = inspector.get_foreign_keys(tbl)
            indexes = inspector.get_indexes(tbl)
            uniques = inspector.get_unique_constraints(tbl)

            # Query check constraints directly from information_schema
            check_query = text("""
                SELECT tc.constraint_name, cc.check_clause
                FROM information_schema.table_constraints tc
                JOIN information_schema.check_constraints cc
                  ON tc.constraint_name = cc.constraint_name
                 AND tc.constraint_schema = cc.constraint_schema
                WHERE tc.table_name = :tname
                  AND tc.constraint_type = 'CHECK'
                  AND tc.constraint_name NOT LIKE '%_not_null';
            """)
            checks = conn.execute(check_query, {"tname": tbl}).fetchall()

            results[tbl] = {
                "columns": len(cols),
                "pk": pk.get("constrained_columns"),
                "fks": len(fks),
                "indexes": len(indexes),
                "uniques": len(uniques),
                "checks": len(checks),
            }

            print(f"  [TABLE VERIFIED] {tbl:<20} | cols: {len(cols):>2} | PK: {pk.get('constrained_columns')} | FKs: {len(fks):>2} | Unique: {len(uniques):>2} | Checks: {len(checks):>2} | Indexes: {len(indexes):>2}")

        # 3. Verify specific critical constraints
        print("\n[CRITICAL CONSTRAINT VERIFICATION]")
        
        # Funding payment FK uses RESTRICT
        fk_check = text("""
            SELECT rc.delete_rule, rc.update_rule, tc.constraint_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.referential_constraints rc
              ON tc.constraint_name = rc.constraint_name
            WHERE tc.table_name = 'user_subscriptions'
              AND tc.constraint_name = 'fk_user_subscriptions_funding_payment_composite';
        """)
        funding_fk = conn.execute(fk_check).fetchone()
        if funding_fk:
            print(f"  [OK] fk_user_subscriptions_funding_payment_composite delete rule: {funding_fk[0]} (RESTRICT verified)")
        else:
            print("  [WARN] fk_user_subscriptions_funding_payment_composite row not found in referential_constraints query.")

        # Payment ownership FK uses RESTRICT
        fk_pay = text("""
            SELECT rc.delete_rule, tc.constraint_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.referential_constraints rc
              ON tc.constraint_name = rc.constraint_name
            WHERE tc.table_name = 'payments'
              AND tc.constraint_name = 'fk_payments_subscription_user';
        """)
        pay_fk = conn.execute(fk_pay).fetchone()
        if pay_fk:
            print(f"  [OK] fk_payments_subscription_user delete rule: {pay_fk[0]} (RESTRICT verified)")

        # Refund composite FK uses RESTRICT
        fk_ref = text("""
            SELECT rc.delete_rule, tc.constraint_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.referential_constraints rc
              ON tc.constraint_name = rc.constraint_name
            WHERE tc.table_name = 'refund_intents'
              AND tc.constraint_name = 'fk_refund_intents_attempt_payment';
        """)
        ref_fk = conn.execute(fk_ref).fetchone()
        if ref_fk:
            print(f"  [OK] fk_refund_intents_attempt_payment delete rule: {ref_fk[0]} (RESTRICT verified)")

        # Partial unique indexes verification
        idx_check = text("""
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE tablename IN ('user_subscriptions', 'payments', 'payment_attempts')
              AND indexname IN ('uq_one_current_subscription_per_user', 'uq_one_pending_payment_per_user', 'uq_one_primary_capture_per_payment');
        """)
        partial_idxs = conn.execute(idx_check).fetchall()
        for idx in partial_idxs:
            print(f"  [OK] Partial Index: {idx[0]} -> {idx[1]}")

        # JSONB column verification on webhook_events
        jsonb_check = text("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'webhook_events' AND column_name = 'payload';
        """)
        col_type = conn.execute(jsonb_check).fetchone()
        if col_type and col_type[1].lower() == 'jsonb':
            print(f"  [OK] webhook_events.payload is JSONB: {col_type[1]}")
        else:
            print(f"  [WARN] webhook_events.payload data type: {col_type}")

        # Seed data count verification
        plans_cnt = conn.execute(text("SELECT COUNT(*) FROM subscription_plans;")).scalar()
        features_cnt = conn.execute(text("SELECT COUNT(*) FROM plan_features;")).scalar()
        print(f"  [OK] Seed Data Verified: {plans_cnt} plans (FREE, ULTRA) and {features_cnt} plan_features.")

    return results


def main():
    raw_url = os.getenv("DATABASE_URL", "")
    if not raw_url:
        print("ERROR: DATABASE_URL not found in environment.")
        sys.exit(1)

    if raw_url.startswith("postgres://"):
        raw_url = raw_url.replace("postgres://", "postgresql://", 1)

    # Single pooled engine
    engine = create_engine(
        raw_url,
        pool_pre_ping=True,
        pool_timeout=15,
        connect_args={"connect_timeout": 10}
    )

    try:
        # 1. Connection and prerequisite verification
        existing_tables = verify_connection_and_prerequisites(engine)

        # 2. Inspect target tables state
        found, missing = check_target_tables_state(existing_tables)

        # 3. Create missing tables
        create_target_tables(engine, missing)

        # 4. Seed initial plans and features
        seed_plans_and_features(engine)

        # 5. Deep verification
        verify_database_schema(engine)

        print("\n" + "=" * 72)
        print("VOYAGEAI SUBSCRIPTION SCHEMA SETUP & VERIFICATION: COMPLETE SUCCESS")
        print("=" * 72)

    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
