import uuid
import json
import hashlib
import os
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional
from sqlalchemy.orm import Session

from models import AuthUser, UserProfile, UserPreferences, LoginRequest, RegisterRequest, OnboardingRequest
from models_db import AuthUserModel, UserProfileModel, UserPreferencesModel, SessionModel
from passlib.context import CryptContext

# CryptContext for bcrypt password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password[:72])

def verify_password(plain_password: str, hashed_password: str) -> bool:
    if not hashed_password:
        return False
    return pwd_context.verify(plain_password[:72], hashed_password)

SESSION_TTL_DAYS = int(os.getenv("SESSION_TTL_DAYS", "7"))

def get_current_iso_time() -> str:
    return datetime.now(timezone.utc).isoformat()

def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

def get_expiry_iso_time(days: int = SESSION_TTL_DAYS) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()

def to_pydantic_auth_user(db_user: AuthUserModel) -> AuthUser:
    return AuthUser(
        id=db_user.id,
        provider=db_user.provider,
        providerUserId=db_user.provider_user_id,
        email=db_user.email,
        phone=db_user.phone,
        emailVerified=db_user.email_verified,
        phoneVerified=db_user.phone_verified,
        status=db_user.status,
        createdAt=db_user.created_at,
        lastLoginAt=db_user.last_login_at
    )

def to_pydantic_user_profile(db_profile: UserProfileModel) -> UserProfile:
    return UserProfile(
        userId=db_profile.user_id,
        firstName=db_profile.first_name,
        lastName=db_profile.last_name,
        avatarUrl=db_profile.avatar_url,
        preferredLanguage=db_profile.preferred_language,
        preferredCurrency=db_profile.preferred_currency,
        timezone=db_profile.timezone,
        onboardingStatus=db_profile.onboarding_status,
        onboardingStep=db_profile.onboarding_step,
        createdAt=db_profile.created_at,
        updatedAt=db_profile.updated_at
    )

def to_pydantic_user_prefs(db_prefs: UserPreferencesModel) -> UserPreferences:
    return UserPreferences(
        userId=db_prefs.user_id,
        travelStyles=db_prefs.travel_styles,
        transportPreferences=db_prefs.transport_preferences,
        dietaryPreferences=db_prefs.dietary_preferences,
        foodInterests=db_prefs.food_interests,
        activityInterests=db_prefs.activity_interests,
        budgetLevel=db_prefs.budget_level or "MODERATE",
        createdAt=db_prefs.created_at,
        updatedAt=db_prefs.updated_at
    )

def create_session_record(db: Session, user_id: str) -> Tuple[str, SessionModel]:
    raw_token = f"token_{uuid.uuid4().hex}"
    t_hash = hash_token(raw_token)
    session_id = f"sid_{uuid.uuid4().hex[:12]}"
    now = get_current_iso_time()
    expires_at = get_expiry_iso_time(SESSION_TTL_DAYS)

    session_record = SessionModel(
        id=session_id,
        token_hash=t_hash,
        user_id=user_id,
        created_at=now,
        expires_at=expires_at,
        last_used_at=now,
        revoked_at=None
    )
    db.add(session_record)
    return raw_token, session_record

def register_user(db: Session, req: RegisterRequest) -> Tuple[str, AuthUser, UserProfile, UserPreferences]:
    clean_email = req.email.strip().lower()
    clean_name = req.name.strip()

    # Check duplicate
    existing = db.query(AuthUserModel).filter(
        (AuthUserModel.email == clean_email)
        | (AuthUserModel.provider_user_id == clean_email)
        | (AuthUserModel.provider_user_id == f"email_{clean_email}")
    ).first()
    if existing:
        raise ValueError("An account with this email already exists.")

    user_id = f"usr_{uuid.uuid4().hex[:10]}"
    hashed_pw = hash_password(req.password)
    now = get_current_iso_time()

    name_parts = clean_name.split()
    first_name = name_parts[0] if name_parts else clean_email.split('@')[0].capitalize()
    last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else None
    avatar = "https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?auto=format&fit=crop&w=400&q=80"

    db_user = AuthUserModel(
        id=user_id,
        provider="EMAIL",
        provider_user_id=clean_email,
        email=clean_email,
        password_hash=hashed_pw,
        phone=None,
        email_verified=True,
        phone_verified=True,
        status="ACTIVE",
        created_at=now,
        last_login_at=now
    )

    db_profile = UserProfileModel(
        user_id=user_id,
        first_name=first_name,
        last_name=last_name,
        avatar_url=avatar,
        preferred_language="en",
        preferred_currency="INR",
        timezone="Asia/Kolkata",
        onboarding_status="PENDING",
        onboarding_step="PREFERENCES",
        created_at=now,
        updated_at=now
    )

    db_prefs = UserPreferencesModel(
        user_id=user_id,
        travel_styles_json=json.dumps([]),
        transport_preferences_json=json.dumps([]),
        dietary_preferences_json=json.dumps([]),
        food_interests_json=json.dumps([]),
        activity_interests_json=json.dumps([]),
        budget_level="MODERATE",
        created_at=now,
        updated_at=now
    )

    raw_token, _ = create_session_record(db, user_id)

    db.add(db_user)
    db.add(db_profile)
    db.add(db_prefs)
    db.commit()

    return (
        raw_token,
        to_pydantic_auth_user(db_user),
        to_pydantic_user_profile(db_profile),
        to_pydantic_user_prefs(db_prefs)
    )

def authenticate_user(db: Session, req: LoginRequest) -> Tuple[str, AuthUser, UserProfile, UserPreferences]:
    """
    Email + password login for an existing account. Accounts are only created by
    register_user, so this never creates users and never skips the password check.
    """
    clean_email = (req.email or "").strip().lower()
    generic_error = "Invalid email or password."

    if not clean_email or not req.password:
        raise ValueError(generic_error)

    db_user = db.query(AuthUserModel).filter(
        (AuthUserModel.email == clean_email)
        | (AuthUserModel.provider_user_id == clean_email)
        | (AuthUserModel.provider_user_id == f"email_{clean_email}")
    ).first()

    # Same message for "no account", "no password set" and "wrong password",
    # so the response doesn't reveal which emails are registered.
    if not db_user or not db_user.password_hash or not verify_password(req.password, db_user.password_hash):
        raise ValueError(generic_error)

    if db_user.status != "ACTIVE":
        raise ValueError("This account is not active.")

    now = get_current_iso_time()
    db_user.last_login_at = now
    raw_token, _ = create_session_record(db, db_user.id)

    db_profile = db.query(UserProfileModel).filter(UserProfileModel.user_id == db_user.id).first()
    if not db_profile:
        db_profile = UserProfileModel(
            user_id=db_user.id,
            first_name=clean_email.split("@")[0].capitalize(),
            created_at=now,
            updated_at=now,
        )
        db.add(db_profile)

    db_prefs = db.query(UserPreferencesModel).filter(UserPreferencesModel.user_id == db_user.id).first()
    if not db_prefs:
        db_prefs = UserPreferencesModel(user_id=db_user.id, budget_level="MODERATE", created_at=now, updated_at=now)
        db.add(db_prefs)

    db.commit()

    return (
        raw_token,
        to_pydantic_auth_user(db_user),
        to_pydantic_user_profile(db_profile),
        to_pydantic_user_prefs(db_prefs),
    )

def get_session_user(db: Session, token: str) -> Tuple[AuthUser, UserProfile, UserPreferences]:
    if not token or not token.strip():
        raise ValueError("Missing session token")

    # Redis session cache: avoid DB round-trips on hot path.
    try:
        from redis_client import redis_conn
        import json
        if redis_conn:
            cached = redis_conn.get(f"session_user:{token}")
            if cached:
                data = json.loads(cached)
                return (
                    AuthUser(**data["user"]),
                    UserProfile(**data["profile"]),
                    UserPreferences(**data["prefs"]),
                )
    except Exception:
        pass

    t_hash = hash_token(token)

    # Single round-trip: session + user + profile + preferences via joins.
    row = (
        db.query(SessionModel, AuthUserModel, UserProfileModel, UserPreferencesModel)
        .join(AuthUserModel, AuthUserModel.id == SessionModel.user_id)
        .outerjoin(UserProfileModel, UserProfileModel.user_id == AuthUserModel.id)
        .outerjoin(UserPreferencesModel, UserPreferencesModel.user_id == AuthUserModel.id)
        .filter(SessionModel.token_hash == t_hash)
        .first()
    )

    if not row:
        raise ValueError("Invalid or expired session token")

    session_record, db_user, db_profile, db_prefs = row

    if not session_record:
        raise ValueError("Invalid or expired session token")

    if session_record.revoked_at is not None:
        raise ValueError("Session token has been revoked")

    # Verify session expiration
    now = datetime.now(timezone.utc)
    is_expired = False
    if session_record.expires_at:
        try:
            iso_str = session_record.expires_at.replace("Z", "+00:00")
            expires_dt = datetime.fromisoformat(iso_str)
            if expires_dt.tzinfo is None:
                expires_dt = expires_dt.replace(tzinfo=timezone.utc)
            if expires_dt < now:
                is_expired = True
        except Exception as e:
            pass

    if is_expired:
        raise ValueError("Session token has expired")

    now_iso = get_current_iso_time()

    if not db_profile:
        db_profile = UserProfileModel(
            user_id=db_user.id,
            first_name="Traveler",
            created_at=now_iso,
            updated_at=now_iso
        )
        db.add(db_profile)

    if not db_prefs:
        db_prefs = UserPreferencesModel(
            user_id=db_user.id,
            budget_level="MODERATE",
            created_at=now_iso,
            updated_at=now_iso
        )
        db.add(db_prefs)

    # Throttle session last_used/expires update to at most once per 5 minutes.
    should_update_session = True
    if session_record.last_used_at:
        try:
            last_iso = session_record.last_used_at.replace("Z", "+00:00")
            last_dt = datetime.fromisoformat(last_iso)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            if (now - last_dt).total_seconds() < 300:
                should_update_session = False
        except Exception:
            pass

    if should_update_session:
        session_record.last_used_at = now_iso
        session_record.expires_at = get_expiry_iso_time(SESSION_TTL_DAYS)

    # Single commit for any pending changes.
    try:
        db.commit()
    except Exception:
        db.rollback()

    _auth_user = to_pydantic_auth_user(db_user)
    _profile = to_pydantic_user_profile(db_profile)
    _prefs = to_pydantic_user_prefs(db_prefs)

    try:
        from redis_client import redis_conn
        import json
        if redis_conn:
            redis_conn.setex(
                f"session_user:{token}",
                300,
                json.dumps({
                    "user": _auth_user.model_dump(),
                    "profile": _profile.model_dump(),
                    "prefs": _prefs.model_dump(),
                }),
            )
    except Exception:
        pass

    return (_auth_user, _profile, _prefs)


def revoke_session(db: Session, token: str):
    if not token or not token.strip():
        return
    t_hash = hash_token(token)
    session_record = db.query(SessionModel).filter(SessionModel.token_hash == t_hash).first()
    if session_record:
        session_record.revoked_at = get_current_iso_time()
        db.commit()

    # Invalidate cached session mapping in Redis
    try:
        from redis_client import redis_conn
        if redis_conn:
            redis_conn.delete(f"session_cache:{token}")
    except Exception:
        pass

def logout_user(db: Session, token: str):
    revoke_session(db, token)


def update_user_onboarding(db: Session, user_id: str, req: OnboardingRequest) -> Tuple[UserProfile, UserPreferences]:
    db_profile = db.query(UserProfileModel).filter(UserProfileModel.user_id == user_id).first()
    db_prefs = db.query(UserPreferencesModel).filter(UserPreferencesModel.user_id == user_id).first()

    now = get_current_iso_time()

    if not db_profile:
        first_n = req.firstName or "Traveler"
        db_profile = UserProfileModel(
            user_id=user_id,
            first_name=first_n,
            last_name=req.lastName,
            preferred_language="en",
            preferred_currency="INR",
            timezone="Asia/Kolkata",
            onboarding_status="NOT_STARTED",
            onboarding_step="welcome",
            created_at=now,
            updated_at=now
        )
        db.add(db_profile)

    if not db_prefs:
        db_prefs = UserPreferencesModel(
            user_id=user_id,
            budget_level="MODERATE",
            created_at=now,
            updated_at=now
        )
        db.add(db_prefs)

    if req.firstName is not None:
        db_profile.first_name = req.firstName
    if req.lastName is not None:
        db_profile.last_name = req.lastName
    if req.onboardingStep is not None:
        db_profile.onboarding_step = req.onboardingStep
    if req.onboardingStatus is not None:
        db_profile.onboarding_status = req.onboardingStatus

    db_profile.updated_at = now

    if req.travelStyles is not None:
        db_prefs.travel_styles = req.travelStyles
    if req.transportPreferences is not None:
        db_prefs.transport_preferences = req.transportPreferences
    if req.dietaryPreferences is not None:
        db_prefs.dietary_preferences = req.dietaryPreferences
    if req.foodInterests is not None:
        db_prefs.food_interests = req.foodInterests
    if req.activityInterests is not None:
        db_prefs.activity_interests = req.activityInterests
    if req.budgetLevel is not None:
        db_prefs.budget_level = req.budgetLevel

    db_prefs.updated_at = now
    db.commit()

    return (
        to_pydantic_user_profile(db_profile),
        to_pydantic_user_prefs(db_prefs)
    )
