from fastapi import FastAPI, HTTPException, Header, Depends, Response, Request, BackgroundTasks, status, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import HTMLResponse
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, List, Dict, Any, Union
from sqlalchemy.orm import Session
import json
import os
import uuid
from datetime import datetime, timezone

from database import get_db, SessionLocal, engine, Base, get_db_context, get_db_pool_status
from models import LoginRequest, RegisterRequest, OnboardingRequest, SessionResponse, AuthUser, UserProfile, UserPreferences
from models_trip import TripModel
from models_itinerary import ItineraryModel, ItineraryDayModel, ItineraryActivityModel
from models_package import TripStayModel, TripTransportModel, TripExpenseModel
from media_service import media_service
from places import search_places, search_nearby_restaurants, validate_destination_payload
import auth
from trip_lifecycle import create_trip_for_user, serialize_trip, TripValidationError
from ownership import (
    trip_id_candidates,
    find_owned_trip,
    require_owned_trip,
    latest_owned_trip,
    find_owned_activity,
    require_owned_activity,
)

from pydantic import BaseModel
from task_queue import enqueue_itinerary_generation
from itinerary_service import (
    process_async_itinerary_generation,
    optimize_day_flow_service,
    optimize_budget_service,
    weather_replan_service,
    execute_refinement_actions_service
)

import asyncio
from starlette.concurrency import run_in_threadpool
from contextlib import asynccontextmanager
from events_listener import start_redis_events_listener
import models_db
import models_trip
import models_itinerary
import models_package
import models_chat

from database import init_db

# Ensure database tables and indexes are created safely
try:
    init_db()
except Exception as e:
    print(f"[DATABASE] Table creation notice: {e}")



def _trip_owner_id(trip_id: str) -> Optional[str]:
    with SessionLocal() as db:
        trip = db.query(TripModel).filter(TripModel.id == trip_id).first()
        return trip.user_id if trip else None


async def broadcast_trip_update_to_clients(trip_id: str, payload: dict):
    """Called for each Redis Pub/Sub trip event. Only the trip owner's sockets are notified."""
    try:
        owner_id = await run_in_threadpool(_trip_owner_id, trip_id)
        if not owner_id:
            return
        await connection_registry.push_to_user(owner_id, payload.get("type", "ITINERARY_READY"), payload)
    except Exception as e:
        print(f"[WS BROADCAST ERROR] Failed to push trip update: {e}", flush=True)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Flush stale mock spotlight caches on startup
    from redis_client import redis_conn
    if redis_conn:
        try:
            count = 0
            for key in redis_conn.scan_iter("cache:spotlight:*"):
                redis_conn.delete(key)
                count += 1
            print(f">>> [CLEANUP] Deleted {count} stale spotlight cache keys from Redis.", flush=True)
        except Exception as e:
            print(f"⚠️ [REDIS CLEANUP WARN] {e}", flush=True)

    # STARTUP: Launch Pub/Sub listener as a concurrent background task
    listener_task = asyncio.create_task(
        start_redis_events_listener(broadcast_trip_update_to_clients)
    )
    yield
    # SHUTDOWN: Cancel task cleanly when server stops
    listener_task.cancel()
    try:
        await listener_task
    except asyncio.CancelledError:
        pass

app = FastAPI(title="VoyageAI Auth, Preferences & Trip API", version="1.0.0", lifespan=lifespan)

# CORS: only these sites may call the API with the user's login cookie.
# Add more with the comma-separated ALLOWED_ORIGINS env var.
_DEFAULT_ALLOWED_ORIGINS = [
    "https://tour-guide-v1.netlify.app",
    "http://localhost",
    "http://localhost:80",
    "http://127.0.0.1",
    "http://127.0.0.1:80",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5248",
    "http://127.0.0.1:5248",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
ALLOWED_ORIGINS = list(dict.fromkeys(
    _DEFAULT_ALLOWED_ORIGINS
    + [o.strip().rstrip("/") for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]
))


def is_allowed_origin(origin: Optional[str]) -> bool:
    return bool(origin) and origin.rstrip("/") in ALLOWED_ORIGINS


app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SERVER_PORT = os.environ.get("PORT")

@app.middleware("http")
async def add_server_identity_header(request: Request, call_next):
    response = await call_next(request)
    server_info = request.scope.get("server") if hasattr(request, "scope") and request.scope else None
    port = SERVER_PORT or (server_info[1] if server_info and len(server_info) > 1 else "8000")
    response.headers["X-Backend-Node"] = f"node-{port}"
    return response

from fastapi.responses import JSONResponse

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    import traceback
    traceback.print_exc()
    # Errors skip the CORS middleware, so add its headers here for allowed sites only.
    # The exception text stays in the server log and is not sent to the client.
    headers = {}
    origin = request.headers.get("origin")
    if is_allowed_origin(origin):
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Credentials"] = "true"
        headers["Vary"] = "Origin"
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error occurred"},
        headers=headers,
    )

from rate_limiter import (
    NetworkRateLimiter,
    UserRateLimiter,
    cache_user_session,
    invalidate_cached_session,
    check_ws_rate_limit,
    client_ip_from,
    normalize_ip,
)

# Production Rate Limiters: Network (Auth/Public) & User (Heavy Compute/Paid/Session)
# Login and paid AI limiters fail closed: if Redis is down they reject instead of letting everything through.
auth_login_limiter = NetworkRateLimiter(requests=5, window_seconds=60, key_prefix="rl:auth:login", fail_closed=True)
auth_register_limiter = NetworkRateLimiter(requests=5, window_seconds=60, key_prefix="rl:auth:register", fail_closed=True)

ai_trip_limiter = UserRateLimiter(requests=10, window_seconds=60, key_prefix="rl:ai:trip", fail_closed=True)
ai_chat_limiter = UserRateLimiter(requests=20, window_seconds=60, key_prefix="rl:ai:chat", fail_closed=True)
tts_limiter = UserRateLimiter(requests=15, window_seconds=60, key_prefix="rl:ai:tts", fail_closed=True)

places_limiter = UserRateLimiter(requests=60, window_seconds=60, key_prefix="rl:places", allow_guest=True)
osm_limiter = places_limiter
general_limiter = UserRateLimiter(requests=120, window_seconds=60, key_prefix="rl:general", allow_guest=True)

# Backward-compatibility alias
ai_limiter = ai_trip_limiter

COOKIE_NAME = "voyageai_session"
GUEST_COOKIE_NAME = "guest_session_id"
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"

def cookie_flags(request: Optional[Request]) -> tuple:
    """(secure, samesite) for auth cookies: Secure + SameSite=None over HTTPS, Lax over plain HTTP."""
    if request is None:
        return True, "none"
    is_https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").startswith("https")
    return (True, "none") if is_https else (False, "lax")


def set_session_cookie(response: Response, token: str, request: Optional[Request] = None):
    is_secure, samesite = cookie_flags(request)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        max_age=7 * 24 * 3600,
        expires=7 * 24 * 3600,
        samesite=samesite,
        secure=is_secure,
        path="/"
    )

def delete_session_cookie(response: Response, request: Optional[Request] = None):
    is_secure, samesite = cookie_flags(request)
    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        httponly=True,
        samesite=samesite,
        secure=is_secure
    )

def log_event(msg: str):
    pass

def print_json_pretty(data: Any) -> str:
    try:
        if hasattr(data, "dict"):
            return json.dumps(data.dict(), indent=2, default=str)
        elif hasattr(data, "model_dump"):
            return json.dumps(data.model_dump(), indent=2, default=str)
        elif isinstance(data, (dict, list)):
            return json.dumps(data, indent=2, default=str)
        elif isinstance(data, str):
            try:
                parsed = json.loads(data)
                return json.dumps(parsed, indent=2, default=str)
            except Exception:
                return data
        return str(data)
    except Exception:
        return str(data)

def log_pipeline_5_steps(
    flow_name: str,
    user_sends: Any,
    backend_received: Any,
    given_to_ai: Any,
    ai_returned: Any,
    send_to_frontend: Any
):
    """
    Prints the complete execution flow in the EXACT 5-step order requested:
    1. WHAT USER SENDS
    2. WHAT BACKEND RECEIVED
    3. WHAT BACKEND IS GIVING TO AI
    4. WHAT AI HAS RETURNED
    5. WHAT YOU WILL SEND TO FRONTEND
    """
    border = "=" * 80
    sub_border = "-" * 80

    print(f"\n{border}", flush=True)
    print(f"🚀 [5-STEP PIPELINE LOG] Flow: {flow_name}", flush=True)
    print(f"{border}", flush=True)

    print("\n1️⃣  WHAT USER SENDS (Frontend Request Payload):", flush=True)
    print(sub_border, flush=True)
    print(print_json_pretty(user_sends), flush=True)

    print("\n2️⃣  WHAT BACKEND RECEIVED (Parsed & Extracted Payload):", flush=True)
    print(sub_border, flush=True)
    print(print_json_pretty(backend_received), flush=True)

    print("\n3️⃣  WHAT BACKEND IS GIVING TO AI (Constructed Prompt & Context):", flush=True)
    print(sub_border, flush=True)
    if isinstance(given_to_ai, dict) and "prompt" in given_to_ai:
        print("🔹 AI Input Context Data:", flush=True)
        print(print_json_pretty(given_to_ai.get("input_data", {})), flush=True)
        print("\n🔹 Constructed Prompt Sent To Model:", flush=True)
        print(given_to_ai.get("prompt"), flush=True)
    else:
        print(print_json_pretty(given_to_ai), flush=True)

    print("\n4️⃣  WHAT AI HAS RETURNED (Raw Model Output):", flush=True)
    print(sub_border, flush=True)
    print(print_json_pretty(ai_returned), flush=True)

    print("\n5️⃣  WHAT YOU WILL SEND TO FRONTEND (Final Response Sent Back to UI):", flush=True)
    print(sub_border, flush=True)
    print(print_json_pretty(send_to_frontend), flush=True)

    print(f"\n{border}\n", flush=True)

def log_frontend_payload(endpoint: str, payload: Any, user_email: Optional[str] = None, usage_summary: Optional[Dict[str, str]] = None):
    """
    Formatted terminal output printer for all incoming data received from the frontend.
    """
    print("\n" + "=" * 80, flush=True)
    print(f"[FRONTEND DATA RECEIVED] -> Endpoint: {endpoint}", flush=True)
    if user_email:
        print(f"[USER] User: {user_email}", flush=True)
    print("-" * 80, flush=True)
    print("[PAYLOAD] Payload Data Received From Frontend:", flush=True)
    try:
        print(print_json_pretty(payload), flush=True)
    except Exception:
        print(str(payload), flush=True)
    
    if usage_summary:
        print("-" * 80, flush=True)
        print("[FIELD USAGE] Field Usage & Explanation in Backend:", flush=True)
        for key, explanation in usage_summary.items():
            print(f"   * {key}: {explanation}", flush=True)
    print("=" * 80 + "\n", flush=True)

def extract_token_optional(request: Request, authorization: Optional[str] = Header(None)) -> Optional[str]:
    # 1. HttpOnly session cookie
    token = request.cookies.get(COOKIE_NAME)
    # 2. Authorization header (Bearer ...) or X-Auth-Token header
    if not token:
        auth_hdr = authorization or request.headers.get("authorization") or request.headers.get("x-auth-token")
        if auth_hdr:
            auth_hdr = auth_hdr.strip()
            if auth_hdr.lower().startswith("bearer "):
                token = auth_hdr[7:].strip()
            else:
                token = auth_hdr
    return token

def extract_token(request: Request, authorization: Optional[str] = Header(None)) -> str:
    token = extract_token_optional(request, authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Authentication token missing")
    return token

def extract_ws_token(websocket: WebSocket, data: Optional[dict] = None) -> Optional[str]:
    # 1. Extract from WebSocket cookie
    token = websocket.cookies.get(COOKIE_NAME)
    if not token and "cookie" in websocket.headers:
        cookie_hdr = websocket.headers.get("cookie", "")
        for part in cookie_hdr.split(";"):
            part = part.strip()
            if part.startswith(f"{COOKIE_NAME}="):
                token = part.split("=", 1)[1]
                break
    # 2. Extract from WebSocket headers
    if not token:
        auth_hdr = websocket.headers.get("authorization") or websocket.headers.get("x-auth-token")
        if auth_hdr:
            auth_hdr = auth_hdr.strip()
            if auth_hdr.lower().startswith("bearer "):
                token = auth_hdr[7:].strip()
            else:
                token = auth_hdr
    # 3. Fallback to payload data
    if not token and data and isinstance(data, dict):
        token = data.get("token")
        if not token and isinstance(data.get("payload"), dict):
            token = data["payload"].get("token")
    # 4. Fallback to query params
    if not token and hasattr(websocket, "query_params"):
        token = websocket.query_params.get("token")
    return token

def get_current_user(
    request: Request,
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db)
) -> AuthUser:
    cached_user = getattr(request.state, "user", None)
    if isinstance(cached_user, AuthUser):
        return cached_user
    token = extract_token(request, authorization)
    try:
        auth_user, _, _ = auth.get_session_user(db, token)
        request.state.user = auth_user
        return auth_user
    except Exception as err:
        log_event(f"❌ Session user lookup failed: {str(err)}")
        raise HTTPException(status_code=401, detail="Invalid or expired session")

def get_current_user_profile(
    request: Request,
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    token = extract_token(request, authorization)
    try:
        return auth.get_session_user(db, token)
    except Exception as err:
        log_event(f"❌ Session user lookup failed: {str(err)}")
        raise HTTPException(status_code=401, detail="Invalid or expired session")

def get_current_user_or_guest(
    request: Request,
    response: Response,
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    """
    Extracts authenticated user session token from HttpOnly cookie or Authorization header.
    If no valid auth token is present, resolves or creates a unique guest_session_id cookie (guest_<uuid>).
    Returns (AuthUser, UserProfile, UserPreferences, is_authenticated: bool).
    """
    token = extract_token_optional(request, authorization)
    if token:
        try:
            auth_user, user_profile, user_prefs = auth.get_session_user(db, token)
            return auth_user, user_profile, user_prefs, True
        except Exception:
            pass

    guest_id = request.cookies.get(GUEST_COOKIE_NAME)
    if not guest_id or not str(guest_id).startswith("guest_"):
        guest_id = f"guest_{uuid.uuid4().hex[:10]}"

    is_secure, samesite = cookie_flags(request)

    try:
        response.set_cookie(
            key=GUEST_COOKIE_NAME,
            value=guest_id,
            httponly=True,
            secure=is_secure,
            samesite=samesite,
            max_age=365 * 86400,
            path="/"
        )
    except Exception:
        pass

    from models import AuthUser
    guest_auth_user = AuthUser(
        id=guest_id,
        provider="GUEST",
        providerUserId=guest_id,
        email=None,
        phone=None,
        emailVerified=False,
        phoneVerified=False,
        status="GUEST",
        createdAt=auth.get_current_iso_time(),
        lastLoginAt=auth.get_current_iso_time()
    )

    return guest_auth_user, None, None, False

def get_user_or_guest(
    request: Request,
    response: Response,
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db)
) -> AuthUser:
    """Dependency returning authenticated AuthUser if session token valid, or guest AuthUser without throwing 401."""
    auth_user, _, _, _ = get_current_user_or_guest(request, response, authorization, db)
    return auth_user

def get_current_user_optional(
    request: Request,
    response: Response,
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    auth_user, user_profile, user_prefs, _ = get_current_user_or_guest(request, response, authorization, db)
    return auth_user, user_profile, user_prefs

def verify_trip_ownership(trip_id: str, user_id: str, db: Session) -> TripModel:
    return require_owned_trip(db, trip_id, user_id)



@app.get("/")
def root():
    return {"app": "VoyageAI OS PostgreSQL API", "status": "online"}

@app.post("/api/auth/register", dependencies=[Depends(auth_register_limiter)])
async def register(req: RegisterRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    log_frontend_payload(
        endpoint="POST /api/auth/register",
        payload={"email": req.email, "name": req.name},
        user_email=req.email,
        usage_summary={
            "name, email & password": "User registration credentials. Hashes password with bcrypt and writes records to auth_users, user_profiles, user_preferences."
        }
    )
    clean_email = req.email.strip().lower()

    from models_db import AuthUserModel
    existing = db.query(AuthUserModel).filter(
        (AuthUserModel.email == clean_email)
        | (AuthUserModel.provider_user_id == clean_email)
        | (AuthUserModel.provider_user_id == f"email_{clean_email}")
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="An account with this email already exists.")

    try:
        token, auth_user, user_profile, user_prefs = await run_in_threadpool(auth.register_user, db, req)
        set_session_cookie(response, token, request)
        await cache_user_session(token, auth_user.id)
        return {
            "status": "success",
            "message": "User registered successfully",
            "token": token,
            "authUser": auth_user,
            "userProfile": user_profile,
            "userPreferences": user_prefs,
            "user": {
                "id": auth_user.id,
                "email": auth_user.email,
                "name": f"{user_profile.firstName} {user_profile.lastName or ''}".strip()
            },
            "onboardingStep": "PREFERENCES"
        }
    except Exception as e:
        log_event(f"❌ Registration Execution Error: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/auth/login", dependencies=[Depends(auth_login_limiter)])
async def login(req: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    log_frontend_payload(
        endpoint="POST /api/auth/login",
        payload=req,
        user_email=req.email,
        usage_summary={
            "email & provider": f"User login credentials ({req.provider}). Used to look up or register user session in PostgreSQL."
        }
    )
    try:
        token, auth_user, user_profile, user_prefs = await run_in_threadpool(auth.authenticate_user, db, req)
        set_session_cookie(response, token, request)
        await cache_user_session(token, auth_user.id)
        return {
            "token": token,
            "authUser": auth_user,
            "userProfile": user_profile,
            "userPreferences": user_prefs
        }
    except Exception as e:
        log_event(f"❌ Login Execution Error: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/auth/me", dependencies=[Depends(general_limiter)])
@app.get("/api/auth/session", dependencies=[Depends(general_limiter)])
def get_auth_me(
    request: Request,
    response: Response,
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    """
    Returns active session data for authenticated users, or guest details if unauthenticated.
    """
    auth_user, user_profile, user_prefs, is_authenticated = get_current_user_or_guest(request, response, authorization, db)
    token = extract_token_optional(request, authorization)
    if is_authenticated:
        return {
            "authenticated": True,
            "token": token,
            "authUser": auth_user,
            "userProfile": user_profile,
            "userPreferences": user_prefs
        }
    return {
        "authenticated": False,
        "guestId": auth_user.id,
        "token": None,
        "authUser": None,
        "userProfile": None,
        "userPreferences": None
    }

@app.post("/api/auth/logout")
async def logout(
    request: Request,
    response: Response,
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    try:
        token = extract_token_optional(request, authorization)
        if token:
            await run_in_threadpool(auth.revoke_session, db, token)
            await invalidate_cached_session(token)
    except Exception:
        pass

    delete_session_cookie(response, request)
    log_event("🚪 POST /api/auth/logout | Cookie Deleted & Session Revoked")
    return {"message": "Logged out successfully"}


@app.post("/api/user/onboarding", dependencies=[Depends(general_limiter)])
def update_onboarding(
    req: OnboardingRequest,
    request: Request,
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    token = extract_token_optional(request, authorization)
    if not token and req.token:
        token = req.token.strip()

    if not token:
        log_event("❌ update_onboarding: No authentication token found in cookies, headers, or body")
        raise HTTPException(status_code=401, detail="Authentication token missing")

    try:
        current_user, _, _ = auth.get_session_user(db, token)
    except Exception as err:
        log_event(f"❌ Session user lookup failed: {str(err)}")
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    log_frontend_payload(
        endpoint="POST /api/user/onboarding",
        payload=req,
        user_email=current_user.email,
        usage_summary={
            "firstName / lastName": "User profile name saved to PostgreSQL.",
            "travelStyles": "Preferred trip vibes used by AI itinerary generator.",
            "budgetTier": "Spending preference tier used for recommendation filtering."
        }
    )
    try:
        updated_profile, updated_prefs = auth.update_user_onboarding(db, current_user.id, req)
        return {
            "userProfile": updated_profile,
            "userPreferences": updated_prefs
        }
    except Exception as e:
        log_event(f"❌ Onboarding Update Error: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/user/preferences", dependencies=[Depends(general_limiter)])
@app.get("/api/preferences", dependencies=[Depends(general_limiter)])
def get_user_preferences(
    current_user: AuthUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    from models_db import UserPreferencesModel
    prefs = db.query(UserPreferencesModel).filter(UserPreferencesModel.user_id == current_user.id).first()
    if not prefs:
        raise HTTPException(status_code=404, detail="Preferences not found")
    return auth.to_pydantic_user_prefs(prefs)

@app.get("/api/user/profile", dependencies=[Depends(general_limiter)])
@app.get("/api/profile", dependencies=[Depends(general_limiter)])
def get_user_profile(
    current_user: AuthUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    from models_db import UserProfileModel
    profile = db.query(UserProfileModel).filter(UserProfileModel.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return auth.to_pydantic_user_profile(profile)


class LocationPayload(BaseModel):
    latitude: float
    longitude: float
    accuracy_meters: Optional[float] = None
    address_name: Optional[str] = None
    source: Optional[str] = "gps"

@app.post("/api/user/location")
def update_user_location(
    payload: LocationPayload,
    current_user: AuthUser = Depends(get_user_or_guest)
):
    import math
    user_id = current_user.id

    acc = payload.accuracy_meters
    is_accurate = True
    if payload.source == "gps" and acc is not None and acc > 1000:
        is_accurate = False

    # Haversine distance from last known position (meters)
    distance_delta_m = None
    uid_key = user_id
    if uid_key in _user_location_history and len(_user_location_history[uid_key]) > 0:
        last = _user_location_history[uid_key][-1]
        lat1, lon1 = math.radians(last["latitude"]), math.radians(last["longitude"])
        lat2, lon2 = math.radians(payload.latitude), math.radians(payload.longitude)
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        distance_delta_m = round(6371000 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)), 1)

    # Store timestamped location entry
    from datetime import datetime, timezone
    entry = {
        "latitude": payload.latitude,
        "longitude": payload.longitude,
        "accuracy_meters": acc,
        "address_name": payload.address_name or "User Location",
        "source": payload.source,
        "is_accurate": is_accurate,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "distance_delta_m": distance_delta_m
    }
    if uid_key not in _user_location_history:
        _user_location_history[uid_key] = []
    _user_location_history[uid_key].append(entry)
    # Keep only last 100 entries per user
    if len(_user_location_history[uid_key]) > 100:
        _user_location_history[uid_key] = _user_location_history[uid_key][-100:]

    delta_str = f" | Delta: {distance_delta_m}m" if distance_delta_m is not None else ""
    log_event(
        f"📍 USER LOCATION RECORDED | User: {user_id or 'Guest'} | "
        f"Coords: ({payload.latitude:.5f}, {payload.longitude:.5f}) | "
        f"Accuracy: {acc if acc is not None else 'N/A'}m | Accurate: {is_accurate} | "
        f"Source: {payload.source} | Address: '{payload.address_name or 'N/A'}'{delta_str}"
    )

    return {
        "status": "success" if is_accurate else "low_accuracy",
        "is_accurate": is_accurate,
        "latitude": payload.latitude,
        "longitude": payload.longitude,
        "accuracy_meters": acc,
        "address_name": payload.address_name or "Captured Location",
        "source": payload.source,
        "distance_delta_m": distance_delta_m,
        "timestamp": entry["timestamp"],
        "message": "Exact location updated successfully" if is_accurate else "GPS accuracy > 1000m (1km). Manual location recommended."
    }

# In-memory location history store (per user)
_user_location_history: dict = {}

# ── WEBSOCKET REALTIME LOCATION INFRASTRUCTURE ──

class LocationConnectionManager:
    """Manages active WebSockets by user_id and trip_id for live streaming and broadcasting."""
    def __init__(self):
        self.active_user_connections: Dict[str, set] = {}
        self.active_trip_connections: Dict[str, set] = {}

    async def connect(self, websocket: WebSocket, user_id: str, trip_id: Optional[str]):
        await websocket.accept()
        if user_id not in self.active_user_connections:
            self.active_user_connections[user_id] = set()
        self.active_user_connections[user_id].add(websocket)

        if trip_id:
            if trip_id not in self.active_trip_connections:
                self.active_trip_connections[trip_id] = set()
            self.active_trip_connections[trip_id].add(websocket)

    def disconnect(self, websocket: WebSocket, user_id: str, trip_id: Optional[str]):
        if user_id in self.active_user_connections:
            self.active_user_connections[user_id].discard(websocket)
            if not self.active_user_connections[user_id]:
                del self.active_user_connections[user_id]

        if trip_id and trip_id in self.active_trip_connections:
            self.active_trip_connections[trip_id].discard(websocket)
            if not self.active_trip_connections[trip_id]:
                del self.active_trip_connections[trip_id]

    async def broadcast_to_trip(self, trip_id: str, message: dict, sender_ws: WebSocket):
        if trip_id in self.active_trip_connections:
            for connection in list(self.active_trip_connections[trip_id]):
                if connection != sender_ws:
                    try:
                        await connection.send_json(message)
                    except Exception:
                        pass

location_manager = LocationConnectionManager()

@app.websocket("/ws/location")
async def websocket_location_endpoint(
    websocket: WebSocket,
    token: Optional[str] = Query(None),
    trip_id: Optional[str] = Query(None)
):
    """
    Real-time WebSocket endpoint for continuous GPS streaming & subscriber broadcast.
    Validates user authentication and trip ownership.
    """
    import math
    from datetime import datetime, timezone

    user_id = f"guest_{uuid.uuid4().hex[:10]}"
    is_authenticated = False
    if token:
        db = SessionLocal()
        try:
            session = await run_in_threadpool(resolve_ws_session, db, token)
            if session:
                user_id = session[0].id
                is_authenticated = True
            # Only the trip owner may join a trip's live-location room.
            if trip_id:
                owned = is_authenticated and await run_in_threadpool(find_owned_trip, db, trip_id, user_id)
                if not owned:
                    await websocket.accept()
                    await websocket.close(code=4003)
                    return
        finally:
            db.close()
    elif trip_id:
        await websocket.accept()
        await websocket.close(code=4003)
        return

    await location_manager.connect(websocket, user_id, trip_id)
    log_event(f"🔌 [WS LOCATION CONNECTED] User: {user_id} | Trip: {trip_id or 'Global'}")

    try:
        while True:
            data = await websocket.receive_json()
            lat = data.get("lat") if data.get("lat") is not None else data.get("latitude")
            lng = data.get("lng") if data.get("lng") is not None else data.get("longitude")
            acc = data.get("accuracy") if data.get("accuracy") is not None else data.get("accuracy_meters")
            source = data.get("source", "gps")
            address_name = data.get("address_name") or "Live Position"
            req_trip_id = trip_id  # only the room joined (and ownership-checked) at connect time

            if lat is not None and lng is not None:
                uid_key = user_id
                distance_delta_m = None
                if uid_key in _user_location_history and len(_user_location_history[uid_key]) > 0:
                    last = _user_location_history[uid_key][-1]
                    lat1, lon1 = math.radians(last["latitude"]), math.radians(last["longitude"])
                    lat2, lon2 = math.radians(lat), math.radians(lng)
                    dlat = lat2 - lat1
                    dlon = lon2 - lon1
                    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
                    distance_delta_m = round(6371000 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)), 1)

                is_accurate = True if (source != "gps" or acc is None or acc <= 1000) else False

                entry = {
                    "latitude": lat,
                    "longitude": lng,
                    "accuracy_meters": acc,
                    "heading": data.get("heading"),
                    "speed": data.get("speed"),
                    "address_name": address_name,
                    "source": source,
                    "is_accurate": is_accurate,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "distance_delta_m": distance_delta_m,
                    "trip_id": req_trip_id
                }

                if uid_key not in _user_location_history:
                    _user_location_history[uid_key] = []
                _user_location_history[uid_key].append(entry)
                if len(_user_location_history[uid_key]) > 100:
                    _user_location_history[uid_key] = _user_location_history[uid_key][-100:]

                # Send ACK back to client
                await websocket.send_json({
                    "type": "location_ack",
                    "status": "success",
                    "timestamp": entry["timestamp"],
                    "distance_delta_m": distance_delta_m
                })

                # Broadcast to trip subscribers if active
                if req_trip_id:
                    await location_manager.broadcast_to_trip(
                        req_trip_id,
                        {
                            "type": "location_broadcast",
                            "user_id": user_id,
                            "trip_id": req_trip_id,
                            "location": entry
                        },
                        websocket
                    )

    except WebSocketDisconnect:
        location_manager.disconnect(websocket, user_id, trip_id)
        log_event(f"🔌 [WS LOCATION DISCONNECTED] User: {user_id} | Trip: {trip_id or 'Global'}")
    except Exception as e:
        location_manager.disconnect(websocket, user_id, trip_id)
        log_event(f"⚠️ [WS LOCATION ERROR] User: {user_id} | Error: {e}")
    finally:
        if not is_authenticated:
            _user_location_history.pop(user_id, None)

# ── UNIFIED WEBSOCKET ACTION DISPATCHER ──

# WebSocket actions anyone may call without logging in.
WS_PUBLIC_ACTIONS = {
    "auth:login", "auth:session", "auth:logout",
    "location:update", "location:latest", "location:search",
    "places:search", "places:nearby",
    "tour_guide:get_nearby", "tour_guide:visit",
}

# Actions on one trip. The trip is checked against the logged-in user before the action runs.
WS_TRIP_ACTIONS = {
    "trips:delete", "trips:get_itinerary",
    "trips:get_stays", "trips:add_stay",
    "trips:get_transports", "trips:add_transport",
    "trips:get_expenses", "trips:add_expense",
    "trips:weather_replan", "trips:optimize_day", "trips:optimize_budget",
    "trips:refine", "trips:regenerate_itinerary", "trips:swap_activity",
    "trips:set_activity_done",
}

# (bucket, requests per minute) per action. Anything not listed uses "general".
WS_RATE_LIMITS = {
    "auth:login": ("login", 5),
    "tour_guide:chat": ("chat", 20),
    "concierge:chat": ("chat", 20),
    "ai:concierge": ("chat", 20),
    "tts:synthesize": ("tts", 15),
    "trips:create": ("ai_trip", 10),
    "trips:regenerate_itinerary": ("ai_trip", 10),
    "trips:refine": ("ai_trip", 10),
    "trips:optimize_day": ("ai_trip", 10),
    "trips:optimize_budget": ("ai_trip", 10),
    "trips:weather_replan": ("ai_trip", 10),
}
WS_GENERAL_LIMIT = ("general", 120)


def resolve_ws_session(db: Session, token: Optional[str]):
    """Returns (AuthUser, UserProfile, UserPreferences) for a valid token, else None."""
    if not token:
        return None
    try:
        return auth.get_session_user(db, token)
    except Exception:
        return None


async def process_ws_action(
    reqname: str,
    data: dict,
    db: Session,
    websocket: WebSocket,
    session=None,
    guest_key: str = "guest",
) -> Any:
    from datetime import datetime, timezone

    user = session[0] if session else None

    if reqname not in WS_PUBLIC_ACTIONS and not user:
        raise PermissionError("Authentication required. Please log in.")

    if reqname in WS_TRIP_ACTIONS:
        trip = find_owned_trip(db, data.get("trip_id") or data.get("tripId"), user.id)
        if not trip:
            raise LookupError("Trip not found")
        data = {**data, "trip_id": trip.id, "tripId": trip.id}

    # 1. Auth Actions
    if reqname == "auth:login":
        req = LoginRequest(**data)
        token, auth_user, user_profile, user_prefs = auth.authenticate_user(db, req)
        await cache_user_session(token, auth_user.id)
        return {
            "token": token,
            "authUser": auth_user,
            "userProfile": user_profile,
            "userPreferences": user_prefs
        }

    elif reqname == "auth:session":
        if not session:
            return {"authUser": None, "userProfile": None, "userPreferences": None}
        auth_user, user_profile, user_prefs = session
        return {
            "authUser": auth_user,
            "userProfile": user_profile,
            "userPreferences": user_prefs
        }

    elif reqname == "auth:logout":
        token = extract_ws_token(websocket, data)
        if token:
            auth.logout_user(db, token)
            await invalidate_cached_session(token)
        return {"message": "Logged out successfully"}

    elif reqname == "auth:onboarding":
        onb_req = OnboardingRequest(**data)
        profile, prefs = auth.update_user_onboarding(db, user.id, onb_req)
        return {
            "authUser": user,
            "userProfile": profile,
            "userPreferences": prefs
        }

    # 2. Location & Places Actions
    elif reqname == "location:update":
        location_key = user.id if user else guest_key
        entry = {
            "latitude": data.get("latitude"),
            "longitude": data.get("longitude"),
            "accuracy_meters": data.get("accuracy_meters") or data.get("accuracy"),
            "address_name": data.get("address_name") or "Live Position",
            "source": data.get("source", "gps"),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        history = _user_location_history.setdefault(location_key, [])
        history.append(entry)
        del history[:-100]
        return {"status": "success", "location": entry}

    elif reqname == "location:latest":
        history = _user_location_history.get(user.id if user else guest_key, [])
        return {"status": "success", "location": history[-1] if history else None}

    elif reqname in ("location:search", "places:search"):
        q = data.get("query") or data.get("q") or ""
        if not q.strip():
            return []
        return await run_in_threadpool(search_places, q)

    elif reqname == "places:nearby":
        q = data.get("query") or data.get("q") or ""
        lat = data.get("lat") or data.get("latitude")
        lon = data.get("lon") or data.get("lng") or data.get("longitude")
        return await run_in_threadpool(search_nearby_restaurants, q, lat, lon)

    # 3. Tour Guide Actions
    elif reqname == "tour_guide:get_nearby":
        from tour_guide_service import (
            search_nearby_pois, rank_places, get_or_create_session, check_proactive_alert
        )
        raw_lat = data.get("lat") or data.get("latitude")
        raw_lng = data.get("lng") or data.get("longitude")
        if raw_lat is None or raw_lng is None:
            return {"places": []}
        lat = float(raw_lat)
        lng = float(raw_lng)
        radius = min(int(data.get("radius") or data.get("radius_m") or 5000), 5000)

        user_prefs = None
        if session and session[2]:
            user_prefs = {
                "activityInterests": session[2].activityInterests or [],
                "travelStyles": session[2].travelStyles or [],
            }

        raw_places = await run_in_threadpool(search_nearby_pois, lat, lng, radius_m=radius, category="all")
        ranked = rank_places(raw_places, user_prefs, limit=10)

        guide_session = get_or_create_session(user.id if user else guest_key)
        guide_session["nearby_places"] = ranked
        guide_session["last_nearby_lat"] = lat
        guide_session["last_nearby_lng"] = lng
        guide_session["last_nearby_refresh"] = __import__("time").time()

        alert_place = check_proactive_alert(guide_session, lat, lng, ranked)

        return {
            "places": ranked,
            "center": {"latitude": lat, "longitude": lng},
            "radius_m": radius,
            "count": len(ranked),
            "total_raw": len(raw_places),
            "proactive_alert": alert_place
        }

    elif reqname in ("tour_guide:chat", "ai:concierge", "concierge:chat"):
        from tour_guide_service import process_concierge_message

        target_mode = data.get("mode") or "local"
        target_trip_id = data.get("trip_id") or data.get("tripId")
        user_msg = data.get("message") or data.get("user_message") or data.get("query") or ""
        dest_name = data.get("destination_name") or data.get("destinationName") or data.get("destination")
        lat = data.get("latitude") or data.get("lat")
        lng = data.get("longitude") or data.get("lng")

        if target_trip_id or target_mode == "trip":
            trip_model = (
                find_owned_trip(db, target_trip_id, user.id) if target_trip_id
                else latest_owned_trip(db, user.id)
            )
            target_trip_id = trip_model.id if trip_model else None
            if trip_model and not dest_name:
                dest = trip_model.destination
                dest_name = (dest.get("name") if isinstance(dest, dict) else None) or trip_model.title

        res = await run_in_threadpool(
            process_concierge_message,
            user_id=user.id,
            message=user_msg,
            mode=target_mode,
            trip_id=target_trip_id,
            destination_name=dest_name,
            lat=lat if target_mode == "local" else None,
            lng=lng if target_mode == "local" else None,
            db=db
        )

        return {
            "reply": res.get("reply", ""),
            "chips": res.get("chips", []),
            "card": res.get("card"),
            "mode": target_mode,
            "trip_id": target_trip_id,
            "error": res.get("error"),
            "source": "websocket"
        }

    elif reqname == "tour_guide:visit":
        from tour_guide_service import get_or_create_session
        place_id = data.get("place_id")
        guide_session = get_or_create_session(user.id if user else guest_key)
        guide_session["current_place_id"] = place_id
        return {"status": "success", "current_place_id": place_id}

    elif reqname == "tts:synthesize":
        from tts_service import synthesize_speech_sarvam
        text = (data.get("text") or "")[:2000]
        lang = data.get("target_language_code", "hi-IN")
        speaker = data.get("speaker", "meera")
        audio_b64 = await run_in_threadpool(
            synthesize_speech_sarvam,
            text=text,
            target_language_code=lang,
            speaker=speaker,
            poi_id=data.get("poi_id")
        )
        return {"audio_base64": audio_b64, "speaker": speaker, "language": lang}

    # 4. Trip Domain Actions
    elif reqname == "trips:list":
        db_trips = db.query(TripModel).filter(TripModel.user_id == user.id).all()
        return [serialize_trip(t, db) for t in db_trips]

    elif reqname == "trips:create":
        auth_user, user_profile, user_prefs = session
        return create_trip_for_user(db, auth_user, user_profile, user_prefs, data)

    elif reqname == "trips:delete":
        trip_id = data["trip_id"]
        itineraries = db.query(ItineraryModel).filter(ItineraryModel.trip_id == trip_id).all()
        for itin in itineraries:
            days = db.query(ItineraryDayModel).filter(ItineraryDayModel.itinerary_id == itin.id).all()
            for day in days:
                db.query(ItineraryActivityModel).filter(ItineraryActivityModel.day_id == day.id).delete()
            db.query(ItineraryDayModel).filter(ItineraryDayModel.itinerary_id == itin.id).delete()
        db.query(ItineraryModel).filter(ItineraryModel.trip_id == trip_id).delete()
        db.query(TripStayModel).filter(TripStayModel.trip_id == trip_id).delete()
        db.query(TripTransportModel).filter(TripTransportModel.trip_id == trip_id).delete()
        db.query(TripExpenseModel).filter(TripExpenseModel.trip_id == trip_id).delete()
        db.query(TripModel).filter(TripModel.id == trip_id, TripModel.user_id == user.id).delete()
        db.commit()
        log_event(f"Deleted trip {trip_id} via WebSocket")
        return {"status": "success", "message": "Trip deleted successfully"}

    elif reqname == "trips:get_itinerary":
        trip_id = (data.get("trip_id") or "").strip()
        candidates = [trip_id, f"trip_{trip_id}", trip_id.replace("trip_", "")]
        itinerary = db.query(ItineraryModel).filter(ItineraryModel.trip_id.in_(candidates)).first()
        if not itinerary:
            return None
        days = db.query(ItineraryDayModel).filter(ItineraryDayModel.itinerary_id == itinerary.id).order_by(ItineraryDayModel.day_number).all()
        day_list = []
        for d in days:
            acts = db.query(ItineraryActivityModel).filter(ItineraryActivityModel.day_id == d.id).all()
            day_list.append({
                "id": d.id,
                "dayNumber": d.day_number,
                "date": d.date,
                "title": d.title,
                "summary": d.summary,
                "theme": getattr(d, "theme", None),
                "activities": [
                    {
                        "id": a.id,
                        "timeSlot": a.time_slot,
                        "title": getattr(a, "title", getattr(a, "name", "")),
                        "name": getattr(a, "title", getattr(a, "name", "")),
                        "description": a.description,
                        "locationName": a.location_name,
                        "latitude": a.latitude,
                        "longitude": a.longitude,
                        "estimatedCostInr": getattr(a, "estimated_cost_inr", getattr(a, "estimated_cost", 0)),
                        "estimatedCost": getattr(a, "estimated_cost_inr", getattr(a, "estimated_cost", 0)),
                        "activityType": a.activity_type,
                        "bookingRequired": getattr(a, "booking_required", False),
                        "isConfirmed": getattr(a, "is_confirmed", False),
                        "isDone": bool(getattr(a, "is_done", False))
                    }
                    for a in acts
                ]
            })
        return {
            "id": itinerary.id,
            "tripId": itinerary.trip_id,
            "status": itinerary.status,
            "version": itinerary.version,
            "days": day_list
        }

    elif reqname == "trips:get_stays":
        trip_id = (data.get("trip_id") or "").strip()
        candidates = [trip_id, f"trip_{trip_id}", trip_id.replace("trip_", "")]
        stays = db.query(TripStayModel).filter(TripStayModel.trip_id.in_(candidates)).order_by(TripStayModel.created_at.desc()).all()
        return [
            {
                "id": s.id,
                "tripId": s.trip_id,
                "activityId": s.activity_id,
                "hotelName": s.hotel_name,
                "locationName": s.location_name,
                "checkInDate": s.check_in_date,
                "checkOutDate": s.check_out_date,
                "nights": s.nights,
                "pricePerNight": s.price_per_night,
                "totalPrice": s.total_price,
                "status": s.status,
                "confirmationCode": s.confirmation_code,
                "createdAt": s.created_at,
                "updatedAt": s.updated_at,
                "name": s.hotel_name,
                "address": s.location_name,
                "checkIn": s.check_in_date,
                "checkOut": s.check_out_date,
                "cost": s.total_price
            }
            for s in stays
        ]

    elif reqname == "trips:add_stay":
        trip_id = (data.get("trip_id") or "").strip()
        candidates = [trip_id, f"trip_{trip_id}", trip_id.replace("trip_", "")]
        resolved_trip = db.query(TripModel).filter(TripModel.id.in_(candidates)).first()
        target_trip_id = resolved_trip.id if resolved_trip else trip_id

        hotel_name = data.get("hotelName") or data.get("name") or "Hotel Stay"
        location_name = data.get("locationName") or data.get("address") or "City Center"
        check_in_date = data.get("checkInDate") or data.get("checkIn") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        check_out_date = data.get("checkOutDate") or data.get("checkOut") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        total_price = int(data.get("totalPrice") or data.get("cost") or 0)
        nights = int(data.get("nights") or 1)
        price_per_night = int(data.get("pricePerNight") or (total_price // max(nights, 1)))

        stay = TripStayModel(
            id=f"stay-{uuid.uuid4().hex[:8]}",
            trip_id=target_trip_id,
            hotel_name=hotel_name,
            location_name=location_name,
            check_in_date=check_in_date,
            check_out_date=check_out_date,
            nights=nights,
            price_per_night=price_per_night,
            total_price=total_price,
            status=data.get("status", "SELECTED"),
            confirmation_code=data.get("confirmationCode"),
            created_at=datetime.now(timezone.utc).isoformat(),
            updated_at=datetime.now(timezone.utc).isoformat()
        )
        db.add(stay)
        db.commit()
        return {
            "id": stay.id,
            "tripId": stay.trip_id,
            "hotelName": stay.hotel_name,
            "locationName": stay.location_name,
            "checkInDate": stay.check_in_date,
            "checkOutDate": stay.check_out_date,
            "nights": stay.nights,
            "pricePerNight": stay.price_per_night,
            "totalPrice": stay.total_price,
            "status": stay.status,
            "name": stay.hotel_name,
            "address": stay.location_name,
            "checkIn": stay.check_in_date,
            "checkOut": stay.check_out_date,
            "cost": stay.total_price
        }

    elif reqname == "trips:get_transports":
        trip_id = (data.get("trip_id") or "").strip()
        candidates = [trip_id, f"trip_{trip_id}", trip_id.replace("trip_", "")]
        transports = db.query(TripTransportModel).filter(TripTransportModel.trip_id.in_(candidates)).order_by(TripTransportModel.created_at.desc()).all()
        return [
            {
                "id": t.id,
                "tripId": t.trip_id,
                "activityId": t.activity_id,
                "transportType": t.transport_type,
                "providerName": t.provider_name,
                "pickupLocation": t.pickup_location,
                "dropoffLocation": t.dropoff_location,
                "pickupTime": t.pickup_time,
                "estimatedFare": t.estimated_fare,
                "status": t.status,
                "bookingReference": t.booking_reference,
                "createdAt": t.created_at,
                "updatedAt": t.updated_at,
                "mode": t.transport_type,
                "details": f"{t.pickup_location} to {t.dropoff_location}",
                "departureTime": t.pickup_time,
                "cost": t.estimated_fare
            }
            for t in transports
        ]

    elif reqname == "trips:add_transport":
        trip_id = (data.get("trip_id") or "").strip()
        candidates = [trip_id, f"trip_{trip_id}", trip_id.replace("trip_", "")]
        resolved_trip = db.query(TripModel).filter(TripModel.id.in_(candidates)).first()
        target_trip_id = resolved_trip.id if resolved_trip else trip_id

        transport = TripTransportModel(
            id=f"trans-{uuid.uuid4().hex[:8]}",
            trip_id=target_trip_id,
            transport_type=data.get("transportType") or data.get("mode") or "CAB",
            provider_name=data.get("providerName") or "VoyageAI Ride",
            pickup_location=data.get("pickupLocation") or data.get("details") or "Pickup Point",
            dropoff_location=data.get("dropoffLocation") or "Destination Point",
            pickup_time=data.get("pickupTime") or data.get("departureTime") or datetime.now(timezone.utc).strftime("%H:%M"),
            estimated_fare=int(data.get("estimatedFare") or data.get("cost") or 0),
            status=data.get("status", "SELECTED"),
            booking_reference=data.get("bookingReference"),
            created_at=datetime.now(timezone.utc).isoformat(),
            updated_at=datetime.now(timezone.utc).isoformat()
        )
        db.add(transport)
        db.commit()
        return {
            "id": transport.id,
            "tripId": transport.trip_id,
            "transportType": transport.transport_type,
            "providerName": transport.provider_name,
            "pickupLocation": transport.pickup_location,
            "dropoffLocation": transport.dropoff_location,
            "pickupTime": transport.pickup_time,
            "estimatedFare": transport.estimated_fare,
            "status": transport.status,
            "mode": transport.transport_type,
            "details": f"{transport.pickup_location} to {transport.dropoff_location}",
            "departureTime": transport.pickup_time,
            "cost": transport.estimated_fare
        }

    elif reqname == "trips:get_expenses":
        trip_id = (data.get("trip_id") or "").strip()
        candidates = [trip_id, f"trip_{trip_id}", trip_id.replace("trip_", "")]
        expenses = db.query(TripExpenseModel).filter(TripExpenseModel.trip_id.in_(candidates)).order_by(TripExpenseModel.created_at.desc()).all()

        return [
            {
                "id": e.id,
                "tripId": e.trip_id,
                "activityId": e.activity_id,
                "title": e.title,
                "amount": e.amount,
                "category": e.category,
                "paidBy": e.paid_by,
                "isSplit": e.is_split,
                "createdAt": e.created_at,
                "description": e.title,
                "date": e.created_at
            }
            for e in expenses
        ]

    elif reqname == "trips:add_expense":
        trip_id = data.get("trip_id")
        expense = TripExpenseModel(
            id=f"exp-{uuid.uuid4().hex[:8]}",
            trip_id=trip_id,
            title=data.get("title") or data.get("description") or "Expense",
            amount=float(data.get("amount") or 0.0),
            category=data.get("category") or "Other",
            paid_by=data.get("paidBy") or data.get("paid_by") or "Me",
            is_split=bool(data.get("isSplit") or False),
            created_at=data.get("createdAt") or data.get("date") or datetime.now(timezone.utc).isoformat()
        )
        db.add(expense)
        db.commit()
        return {
            "id": expense.id,
            "tripId": expense.trip_id,
            "title": expense.title,
            "amount": expense.amount,
            "category": expense.category,
            "paidBy": expense.paid_by,
            "isSplit": expense.is_split,
            "createdAt": expense.created_at,
            "description": expense.title,
            "date": expense.created_at
        }

    elif reqname == "trips:weather_replan":
        trip_id = data.get("trip_id") or data.get("tripId")
        if not trip_id:
            raise ValueError("trip_id is required for weather_replan")
        return weather_replan_service(db, trip_id)

    elif reqname == "trips:optimize_day":
        trip_id = data.get("trip_id") or data.get("tripId")
        day_id = data.get("day_id") or data.get("dayId")
        goal = data.get("goal", "MINIMIZE_TRAVEL_TIME")
        if not trip_id or not day_id:
            raise ValueError("trip_id and day_id are required for optimize_day")
        return optimize_day_flow_service(db, trip_id, day_id, goal)

    elif reqname == "trips:optimize_budget":
        trip_id = data.get("trip_id") or data.get("tripId")
        if not trip_id:
            raise ValueError("trip_id is required for optimize_budget")
        return optimize_budget_service(db, trip_id)

    elif reqname == "trips:refine":
        trip_id = data.get("trip_id") or data.get("tripId")
        actions = data.get("actions", [])
        if not trip_id:
            raise ValueError("trip_id is required for refine")
        return execute_refinement_actions_service(db, trip_id, actions)

    elif reqname == "trips:regenerate_itinerary":
        trip_id = data.get("trip_id") or data.get("tripId")
        if not trip_id:
            raise ValueError("trip_id is required for regenerate_itinerary")
        trip = db.query(TripModel).filter(TripModel.id == trip_id, TripModel.user_id == user.id).first()
        if trip:
            trip.itinerary_status = "GENERATING"
            db.commit()
            enqueue_itinerary_generation(trip_id)
        return {"status": "GENERATING", "tripId": trip_id}

    elif reqname == "trips:set_activity_done":
        owned = find_owned_activity(db, data.get("activity_id") or data.get("activityId"), user.id)
        if not owned or owned[1].id != data["trip_id"]:
            raise LookupError("Activity not found")
        activity, trip = owned
        activity.is_done = bool(data.get("done", True))
        db.flush()  # the session doesn't autoflush; count must see this change
        trip_activities = (
            db.query(ItineraryActivityModel.is_done)
            .join(ItineraryDayModel, ItineraryDayModel.id == ItineraryActivityModel.day_id)
            .join(ItineraryModel, ItineraryModel.id == ItineraryDayModel.itinerary_id)
            .filter(ItineraryModel.trip_id == trip.id)
            .all()
        )
        progress = dict(trip.progress or {})
        progress["completedActivitiesCount"] = sum(1 for (done,) in trip_activities if done)
        progress["totalActivitiesCount"] = len(trip_activities)
        trip.progress = progress
        db.commit()
        return {"activityId": activity.id, "isDone": activity.is_done, "progress": progress}

    elif reqname == "trips:swap_activity":
        trip_id = data.get("trip_id") or data.get("tripId")
        activity_id = data.get("activity_id") or data.get("activityId")
        replacement = data.get("replacement") or {}
        if not activity_id:
            raise ValueError("activity_id is required for swap_activity")
        owned = find_owned_activity(db, activity_id, user.id)
        if not owned or owned[1].id != data["trip_id"]:
            raise LookupError("Activity not found")
        act = owned[0]
        if replacement:
            act.title = replacement.get("name") or replacement.get("title") or act.title
            act.description = replacement.get("description", act.description)
            act.location_name = replacement.get("locationName", act.location_name)
            if replacement.get("latitude"):
                act.latitude = replacement["latitude"]
            if replacement.get("longitude"):
                act.longitude = replacement["longitude"]
            if replacement.get("estimatedCost"):
                act.estimated_cost_inr = replacement["estimatedCost"]
            db.commit()
        return {"status": "SUCCESS", "activityId": activity_id}

    else:
        raise ValueError(f"Unknown WebSocket request action: [{reqname}]")

class ConnectionRegistry:
    """Open /ws/app sockets, and which logged-in user (if any) each one belongs to."""

    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.connection_users: Dict[str, str] = {}

    async def connect(self, connection_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[connection_id] = websocket

    def set_user(self, connection_id: str, user_id: Optional[str]):
        if user_id:
            self.connection_users[connection_id] = user_id
        else:
            self.connection_users.pop(connection_id, None)

    def disconnect(self, connection_id: str):
        self.active_connections.pop(connection_id, None)
        self.connection_users.pop(connection_id, None)

    async def push_to_user(self, user_id: str, action: str, data: dict):
        """Sends a server event only to the sockets of one user."""
        frame = {"id": None, "action": action, "data": data}
        targets = [cid for cid, uid in self.connection_users.items() if uid == user_id]
        for cid in targets:
            ws = self.active_connections.get(cid)
            if not ws:
                continue
            try:
                await ws.send_json(frame)
            except Exception:
                self.disconnect(cid)

connection_registry = ConnectionRegistry()


def _ws_error_status(err: Exception) -> int:
    if isinstance(err, HTTPException):
        return err.status_code
    if isinstance(err, PermissionError):
        return 401
    if isinstance(err, LookupError):
        return 404
    return 400


def _ws_error_message(err: Exception) -> str:
    if isinstance(err, HTTPException):
        return str(err.detail)
    if isinstance(err, (PermissionError, LookupError, ValueError)):
        return str(err)
    return "Request failed"


@app.websocket("/ws")
@app.websocket("/ws/app")
@app.websocket("/ws/tour-app")
async def websocket_tour_app_endpoint(websocket: WebSocket):
    """
    Central WebSocket endpoint for the app.
    Frames: { id, action, payload } (or legacy { requestId, reqname, data }).
    Every frame carries its own login token; the user is checked per frame.
    """
    conn_id = f"conn_{uuid.uuid4().hex[:10]}"
    guest_key = f"guest_{conn_id}"
    client_ip = normalize_ip(client_ip_from(websocket.headers, websocket.client.host if websocket.client else None))
    await connection_registry.connect(conn_id, websocket)

    try:
        while True:
            frame = await websocket.receive_json()

            req_id = frame.get("id") or frame.get("requestId")
            action = frame.get("action") or frame.get("reqname")
            payload = frame.get("payload") if "payload" in frame else (frame.get("data") or {})
            if not action:
                continue
            if not isinstance(payload, dict):
                payload = {}

            db = SessionLocal()
            try:
                token = extract_ws_token(websocket, payload)
                session = await run_in_threadpool(resolve_ws_session, db, token)
                user_id = session[0].id if session else None
                connection_registry.set_user(conn_id, user_id)

                bucket, limit = WS_RATE_LIMITS.get(action, WS_GENERAL_LIMIT)
                # Login is limited per network so it can't be used to guess passwords.
                subject = client_ip if bucket == "login" or not user_id else user_id
                await check_ws_rate_limit(bucket, subject, limit)

                result = await process_ws_action(action, payload, db, websocket, session=session, guest_key=guest_key)
                response_frame = {
                    "id": req_id,
                    "action": f"{action}:reply",
                    "status": 200,
                    "data": jsonable_encoder(result),
                    "error": None,
                    "type": "response",
                    "reqname": f"{action}:response",
                    "requestId": req_id
                }
            except Exception as err:
                status_code = _ws_error_status(err)
                if status_code >= 500 or status_code == 400 and not isinstance(err, (ValueError, HTTPException)):
                    import traceback
                    traceback.print_exc()
                log_event(f"[WS ACTION ERROR] {action}: {err}")
                response_frame = {
                    "id": req_id,
                    "action": f"{action}:reply",
                    "status": status_code,
                    "data": None,
                    "error": _ws_error_message(err),
                    "type": "response",
                    "reqname": f"{action}:response",
                    "requestId": req_id
                }
            finally:
                db.close()

            await websocket.send_json(response_frame)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        log_event(f"[WS ERROR] {e}")
    finally:
        connection_registry.disconnect(conn_id)
        _user_location_history.pop(guest_key, None)

@app.get("/api/admin/pool-status")
def get_pool_status():
    """
    Returns real-time SQLAlchemy connection pool metrics:
    size, checkedout, and overflow connections.
    """
    status_data = get_db_pool_status()
    log_event(f"📊 [POOL STATUS] Size: {status_data['pool_size']} | Checked Out: {status_data['checkedout']} | Overflow: {status_data['overflow']}")
    return status_data

@app.get("/api/user/location/latest", dependencies=[Depends(general_limiter)])
def get_latest_user_location(
    current_user: AuthUser = Depends(get_current_user)
):
    """Get the most recent location for the authenticated user."""
    history = _user_location_history.get(current_user.id, [])
    if not history:
        return {"status": "no_location", "message": "No location recorded yet."}

    latest = history[-1]
    return {
        "status": "success",
        "location": latest,
        "total_updates": len(history)
    }

@app.get("/api/user/location/search", dependencies=[Depends(osm_limiter)])
def search_user_location(query: str = ""):
    if not query or len(query.strip()) < 2:
        return []
    log_event(f"🔍 GET /api/user/location/search?query={query}")
    return search_places(query)

# ── PLACES & GEOCODING ENDPOINTS ──

@app.get("/api/location/reverse", dependencies=[Depends(places_limiter)])
async def location_reverse(lat: float, lng: float):
    """Reverse geocode coordinates using Google Geocoding proxy with Redis caching."""
    from services.google_maps_service import reverse_geocode
    return await reverse_geocode(lat, lng)

@app.get("/api/places/autocomplete", dependencies=[Depends(places_limiter)])
async def places_autocomplete(q: str = "", lat: Optional[float] = None, lng: Optional[float] = None):
    """Google Places Autocomplete proxy with Redis caching."""
    if not q or len(query_clean := q.strip()) < 2:
        return []
    from services.google_maps_service import autocomplete_places
    return await autocomplete_places(q, lat, lng)

@app.get("/api/places/details", dependencies=[Depends(places_limiter)])
async def places_details(place_id: str):
    """Google Places Details proxy with Redis caching."""
    from services.google_maps_service import get_place_details
    detail = await get_place_details(place_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Place details not found.")
    return detail

@app.get("/api/places/search", dependencies=[Depends(osm_limiter)])
def search_destinations(q: str = ""):
    if not q or len(q.strip()) < 2:
        return []
    log_event(f"🔍 GET /api/places/search?q={q}")
    return search_places(q)

@app.get("/api/places/nearby", dependencies=[Depends(places_limiter)])
async def get_nearby_places(
    q: Optional[str] = None,
    category: Optional[str] = "all",
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    lng: Optional[float] = None,
    radius: Optional[int] = 5000
):
    """
    Direct Google Places API (New) discovery endpoint.
    All Overpass network calls and synthetic mocks are completely eliminated.
    """
    resolved_lng = lng if lng is not None else lon
    if lat is None or resolved_lng is None:
        raise HTTPException(status_code=400, detail="Latitude and Longitude are required.")

    log_event(f"🗺️ GET /api/places/nearby | Cat: {category} | Query: {q} | Coords: ({lat:.4f}, {resolved_lng:.4f})")

    try:
        from services.google_maps_service import search_nearby_places

        place_types = None
        if category and category.lower() != "all":
            cat_l = category.lower()
            if "pharmacy" in cat_l:
                place_types = ["pharmacy", "drugstore"]
            elif "hospital" in cat_l or "medical" in cat_l:
                place_types = ["hospital", "doctor"]
            elif "food" in cat_l or "restaurant" in cat_l:
                place_types = ["restaurant", "cafe"]
            elif "hotel" in cat_l or "stay" in cat_l:
                place_types = ["lodging", "hotel"]
            elif "atm" in cat_l or "bank" in cat_l:
                place_types = ["atm", "bank"]
            elif "police" in cat_l:
                place_types = ["police"]
            elif "sight" in cat_l or "attraction" in cat_l or "monument" in cat_l:
                place_types = ["tourist_attraction", "museum", "historical_landmark", "monument"]

        places = await search_nearby_places(lat, resolved_lng, radius=radius or 5000, place_types=place_types)
        
        if q and len(q.strip()) >= 2:
            clean_q = q.strip().lower()
            places = [
                p for p in places 
                if clean_q in p.get("name", "").lower() 
                or clean_q in p.get("category", "").lower() 
                or clean_q in (p.get("address") or "").lower()
            ]

        return places
    except Exception as e:
        print(f"[NEARBY ENDPOINT ERROR]: {e}", flush=True)
        return []

# ── SARVAM AI TTS SYNTHESIS ENDPOINT ──

class TTSRequest(BaseModel):
    text: str
    target_language_code: Optional[str] = "hi-IN"
    speaker: Optional[str] = "meera"
    poi_id: Optional[str] = None

@app.post("/api/tts/synthesize", dependencies=[Depends(tts_limiter)])
async def tts_synthesize(req: TTSRequest):
    try:
        from tts_service import synthesize_speech_sarvam
        base64_audio = await run_in_threadpool(
            synthesize_speech_sarvam,
            text=req.text,
            target_language_code=req.target_language_code or "hi-IN",
            speaker=req.speaker or "meera",
            poi_id=req.poi_id
        )
        return {
            "audio_base64": base64_audio,
            "format": "audio/wav",
            "speaker": req.speaker,
            "language": req.target_language_code,
            "status": "ok" if base64_audio else "unavailable"
        }
    except Exception as e:
        print(f"[TTS SYNTHESIZE ERROR]: {e}", flush=True)
        return {"audio_base64": None, "status": "error", "message": str(e)}

class SpeakRequest(BaseModel):
    text: Optional[str] = None
    language: Optional[str] = "hi-IN"
    speaker: Optional[str] = "ritu"
    place_id: Optional[str] = None
    place_name: Optional[str] = None
    category: Optional[str] = "attraction"
    address: Optional[str] = None

@app.post("/api/tts/speak", dependencies=[Depends(tts_limiter)])
def text_to_speech_endpoint(req: SpeakRequest):
    try:
        from tts_service import synthesize_speech_sarvam
        from tour_guide_service import generate_poi_story

        narration_text = req.text
        if not narration_text or len(narration_text.strip()) == 0:
            if req.place_name:
                narration_text = generate_poi_story(req.place_name, req.category or "attraction", req.address or "")
            else:
                return {"status": "error", "message": "Either text or place_name must be provided.", "audio_base64": None}

        audio_b64 = synthesize_speech_sarvam(
            text=narration_text,
            target_language_code=req.language or "hi-IN",
            speaker=req.speaker or "ritu",
            poi_id=req.place_id
        )
        return {
            "status": "ok" if audio_b64 else "unavailable",
            "story": narration_text,
            "audio_base64": audio_b64
        }
    except Exception as e:
        print(f"[TTS SPEAK ERROR]: {e}", flush=True)
        return {"status": "error", "message": str(e), "audio_base64": None}

# ── AI CONCIERGE HTTP FALLBACK ENDPOINT ──

class ConciergeRequest(BaseModel):
    message: Optional[str] = None
    query: Optional[str] = None
    intent: Optional[str] = "CHAT"
    mode: Optional[str] = "local"
    tripId: Optional[str] = None
    trip_id: Optional[str] = None
    activityId: Optional[str] = None
    activity_id: Optional[str] = None
    dayId: Optional[str] = None
    day_id: Optional[str] = None
    itineraryId: Optional[str] = None
    itinerary_id: Optional[str] = None
    userId: Optional[str] = None
    user_id: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    context: Optional[Dict[str, Any]] = None
    tripContext: Optional[Dict[str, Any]] = None
    trip_context: Optional[Dict[str, Any]] = None
    messages: Optional[List[Dict[str, Any]]] = None

    class Config:
        extra = "allow"
        populate_by_name = True

# ── TRIP HIGHLIGHTS & ITINERARY ADD ENDPOINTS ──

@app.get("/api/trips/highlights")
def get_trip_highlights_query(
    destination: Optional[str] = Query(None),
    lat: Optional[float] = Query(None),
    lng: Optional[float] = Query(None)
):
    try:
        from trips_service import generate_live_destination_highlights
        return generate_live_destination_highlights(destination=destination, lat=lat, lng=lng)
    except Exception as e:
        print(f"[HIGHLIGHTS FETCH FAILED]: {e}", flush=True)
        return {
            "destination": f"MOCK {(destination or 'DESTINATION').upper()} • MOCK MOCK",
            "region": "MOCK REGION",
            "overview": "MOCK DATA: Live data failed to fetch from backend. Inspect backend logs.",
            "is_mock": True,
            "activities": [
                {
                    "id": "mock_1",
                    "title": "MOCK SPOT 1 • MOCK MOCK",
                    "category": "MOCK",
                    "tag": "MOCK",
                    "location": f"MOCK LOCATION • {destination or 'DESTINATION'}",
                    "duration": "MOCK",
                    "cost": 0,
                    "is_mock": True,
                    "heads_up": "MOCK: Live data failed to fetch from backend"
                },
                {
                    "id": "mock_2",
                    "title": "MOCK SPOT 2 • MOCK MOCK",
                    "category": "MOCK",
                    "tag": "MOCK",
                    "location": f"MOCK LOCATION • {destination or 'DESTINATION'}",
                    "duration": "MOCK",
                    "cost": 0,
                    "is_mock": True,
                    "heads_up": "MOCK: LLM fallback triggered"
                }
            ],
            "events": []
        }

@app.get("/api/trips/{destination}/highlights")
def get_trip_highlights_endpoint(
    destination: str,
    lat: Optional[float] = Query(None),
    lng: Optional[float] = Query(None)
):
    try:
        from trips_service import generate_live_destination_highlights
        return generate_live_destination_highlights(destination=destination, lat=lat, lng=lng)
    except Exception as e:
        print(f"[HIGHLIGHTS FETCH FAILED]: {e}", flush=True)
        return {
            "destination": f"MOCK {destination.upper()} • MOCK MOCK",
            "region": "MOCK REGION",
            "overview": "MOCK DATA: Live data failed to fetch from backend. Inspect backend logs.",
            "is_mock": True,
            "activities": [
                {
                    "id": "mock_1",
                    "title": "MOCK SPOT 1 • MOCK MOCK",
                    "category": "MOCK",
                    "tag": "MOCK",
                    "location": f"MOCK LOCATION • {destination}",
                    "duration": "MOCK",
                    "cost": 0,
                    "is_mock": True,
                    "heads_up": "MOCK: Live data failed to fetch from backend"
                },
                {
                    "id": "mock_2",
                    "title": "MOCK SPOT 2 • MOCK MOCK",
                    "category": "MOCK",
                    "tag": "MOCK",
                    "location": f"MOCK LOCATION • {destination}",
                    "duration": "MOCK",
                    "cost": 0,
                    "is_mock": True,
                    "heads_up": "MOCK: LLM fallback triggered"
                }
            ],
            "events": []
        }

# ── SAVED PLACES (BOOKMARKS) SCHEMAS & ENDPOINTS ──

# ── SAVED PLACES (BOOKMARKS) SCHEMAS & ENDPOINTS ──

class SavePlaceRequest(BaseModel):
    place_id: str
    title: str
    category: Optional[str] = None
    rating: Optional[float] = None
    location_name: Optional[str] = None
    location: Optional[str] = None
    coordinates: Optional[List[float]] = None
    distance_text: Optional[str] = None
    duration_text: Optional[str] = None
    cost_text: Optional[str] = None
    description: Optional[str] = None

@app.post("/api/places/save")
@app.post("/api/user/saved-places")
def save_place(
    req: SavePlaceRequest,
    current_user: AuthUser = Depends(get_user_or_guest),
    db: Session = Depends(get_db)
):
    from redis_client import redis_conn
    from models_db import SavedPlaceModel, AuthUserModel

    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required to save places")

    user_id = current_user.id
    # Ensure user exists in auth_users table (e.g., guest sessions) to preserve foreign key integrity
    user_record = db.query(AuthUserModel.id).filter(AuthUserModel.id == user_id).first()
    if not user_record:
        try:
            now_iso = auth.get_current_iso_time()
            guest_record = AuthUserModel(
                id=user_id,
                provider="GUEST",
                provider_user_id=user_id,
                email=f"{user_id}@guest.voyageai",
                phone=None,
                email_verified=False,
                phone_verified=False,
                status="GUEST",
                created_at=now_iso,
                last_login_at=now_iso
            )
            db.add(guest_record)
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"[SAVED PLACES USER SYNC WARN]: {e}", flush=True)

    loc = req.location_name or req.location or ""

    existing = db.query(SavedPlaceModel).filter(
        SavedPlaceModel.user_id == user_id,
        SavedPlaceModel.place_id == req.place_id
    ).first()

    if existing:
        existing.title = req.title
        existing.category = req.category
        existing.rating = req.rating
        existing.location_name = loc
        existing.distance_text = req.distance_text
        existing.duration_text = req.duration_text
        existing.cost_text = req.cost_text
        existing.description = req.description
    else:
        new_place = SavedPlaceModel(
            id=f"sp_{uuid.uuid4().hex[:12]}",
            user_id=user_id,
            place_id=req.place_id,
            title=req.title,
            category=req.category,
            rating=req.rating,
            location_name=loc,
            distance_text=req.distance_text,
            duration_text=req.duration_text,
            cost_text=req.cost_text,
            description=req.description
        )
        db.add(new_place)

    db.commit()

    # Atomically invalidate/update Redis cache
    try:
        redis_conn.delete(f"saved_places:{user_id}")
    except Exception as e:
        print(f"[SAVED PLACES CACHE WARN]: {e}", flush=True)

    return {"status": "saved", "place_id": req.place_id}

@app.delete("/api/places/save/{place_id}")
@app.delete("/api/user/saved-places/{place_id}")
def remove_saved_place(
    place_id: str,
    current_user: AuthUser = Depends(get_user_or_guest),
    db: Session = Depends(get_db)
):
    from redis_client import redis_conn
    from models_db import SavedPlaceModel

    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")

    user_id = current_user.id
    db.query(SavedPlaceModel).filter(
        SavedPlaceModel.user_id == user_id,
        SavedPlaceModel.place_id == place_id
    ).delete()

    db.commit()

    # Invalidate cache
    try:
        redis_conn.delete(f"saved_places:{user_id}")
    except Exception as e:
        print(f"[SAVED PLACES CACHE WARN]: {e}", flush=True)

    return {"status": "removed", "place_id": place_id}

@app.delete("/api/user/saved-places")
def remove_saved_place_legacy_body(
    req: SavePlaceRequest,
    current_user: AuthUser = Depends(get_user_or_guest),
    db: Session = Depends(get_db)
):
    return remove_saved_place(req.place_id, current_user, db)

@app.get("/api/places/saved")
@app.get("/api/user/saved-places")
def get_saved_places(
    current_user: AuthUser = Depends(get_user_or_guest),
    db: Session = Depends(get_db)
):
    if not current_user:
        return []

    from redis_client import redis_conn
    from models_db import SavedPlaceModel

    user_id = current_user.id
    cache_key = f"saved_places:{user_id}"

    # Cache-aside pattern
    try:
        cached = redis_conn.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception as e:
        print(f"[SAVED PLACES CACHE READ WARN]: {e}", flush=True)

    places = db.query(SavedPlaceModel).filter(
        SavedPlaceModel.user_id == user_id
    ).order_by(SavedPlaceModel.created_at.desc()).all()

    results = []
    for sp in places:
        created_str = sp.created_at.isoformat() if hasattr(sp.created_at, "isoformat") else str(sp.created_at)
        results.append({
            "id": sp.id,
            "place_id": sp.place_id,
            "title": sp.title,
            "category": sp.category,
            "rating": float(sp.rating) if sp.rating is not None else None,
            "location_name": sp.location_name,
            "location": sp.location_name,
            "distance_text": sp.distance_text,
            "duration_text": sp.duration_text,
            "cost_text": sp.cost_text,
            "description": sp.description,
            "created_at": created_str
        })

    try:
        redis_conn.setex(cache_key, 600, json.dumps(results))
    except Exception as e:
        print(f"[SAVED PLACES CACHE WRITE WARN]: {e}", flush=True)

    return results

@app.get("/api/places/saved/check/{place_id}")
def check_place_saved(
    place_id: str,
    current_user: AuthUser = Depends(get_user_or_guest),
    db: Session = Depends(get_db)
):
    if not current_user:
        return {"is_saved": False}

    from models_db import SavedPlaceModel

    exists = db.query(SavedPlaceModel.id).filter(
        SavedPlaceModel.user_id == current_user.id,
        SavedPlaceModel.place_id == place_id
    ).first()

    return {"is_saved": bool(exists)}


class AddItineraryItemRequest(BaseModel):
    trip_id: Optional[str] = "active_trip"
    destination: Optional[str] = ""
    item_id: Optional[str] = None
    title: str
    location: Optional[str] = ""
    location_name: Optional[str] = None
    tag: Optional[str] = None
    price: Optional[Union[str, int, float]] = None
    estimated_cost_inr: Optional[int] = None
    day_id: Optional[str] = None
    day_number: Optional[int] = 1
    time_slot: Optional[str] = "Morning"
    scheduled_time: Optional[str] = None
    order_index: Optional[int] = 0
    activity_type: Optional[str] = None
    is_confirmed: Optional[bool] = True

@app.post("/api/trips/itinerary/add")
def add_to_itinerary(
    req: AddItineraryItemRequest,
    user_data = Depends(get_current_user_or_guest),
    db: Session = Depends(get_db)
):
    from redis_client import redis_conn
    from models_trip import TripModel
    from models_itinerary import ItineraryModel, ItineraryDayModel, ItineraryActivityModel

    current_user, user_profile, user_prefs, is_authenticated = user_data

    req_trip_id = (req.trip_id or "active_trip").strip()
    target_trip = None
    candidates = [req_trip_id, f"trip_{req_trip_id}", req_trip_id.replace("trip_", "")]

    if req_trip_id and req_trip_id != "active_trip":
        target_trip = db.query(TripModel).filter(
            TripModel.id.in_(candidates),
            TripModel.user_id == current_user.id
        ).first()

    if not target_trip:
        target_trip = db.query(TripModel).filter(
            TripModel.user_id == current_user.id
        ).order_by(TripModel.created_at.desc()).first()

    if not target_trip:
        # Fallback to the latest trip overall
        target_trip = db.query(TripModel).order_by(TripModel.created_at.desc()).first()

    if not target_trip:
        raise HTTPException(status_code=404, detail="No active trip found. Please create a trip first.")

    target_trip_id = target_trip.id
    day_num = req.day_number or 1

    cost_val = 0
    if req.estimated_cost_inr is not None:
        cost_val = int(req.estimated_cost_inr)
    elif req.price:
        import re
        digits = re.findall(r'\d+', str(req.price))
        if digits:
            cost_val = int("".join(digits))

    loc_name = req.location_name or req.location or req.destination or "Local Spot"
    act_type = req.activity_type or req.tag or "SIGHTSEEING"

    new_activity_payload = {
        "id": req.item_id or f"act_{uuid.uuid4().hex[:12]}",
        "title": req.title,
        "location": loc_name,
        "location_name": loc_name,
        "tag": act_type,
        "activity_type": act_type,
        "price": f"₹{cost_val}" if cost_val > 0 else (str(req.price) if req.price else "Free Entry"),
        "estimated_cost_inr": cost_val,
        "time_slot": req.time_slot or req.scheduled_time or "Morning",
        "scheduled_time": req.scheduled_time or "10:00 AM",
        "is_confirmed": True
    }

    # 1. Commit to PostgreSQL Database
    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        itin = db.query(ItineraryModel).filter(ItineraryModel.trip_id == target_trip.id).first()
        if not itin:
            itin = ItineraryModel(
                id=f"itin_{uuid.uuid4().hex[:12]}",
                trip_id=target_trip.id,
                status="READY",
                created_at=now_iso,
                updated_at=now_iso
            )
            db.add(itin)
            db.flush()

        day_record = None
        if req.day_id:
            day_record = db.query(ItineraryDayModel).filter(ItineraryDayModel.id == req.day_id).first()

        if not day_record:
            day_record = db.query(ItineraryDayModel).filter(
                ItineraryDayModel.itinerary_id == itin.id,
                ItineraryDayModel.day_number == day_num
            ).first()

        if not day_record:
            day_record = ItineraryDayModel(
                id=req.day_id or f"day_{uuid.uuid4().hex[:12]}",
                itinerary_id=itin.id,
                day_number=day_num,
                date=f"Day {day_num}",
                title=f"Day {day_num} Highlights",
                summary=f"Curated schedule for Day {day_num}"
            )
            db.add(day_record)
            db.flush()

        day_num = day_record.day_number

        act_id = new_activity_payload["id"]
        existing_act = db.query(ItineraryActivityModel).filter(
            ItineraryActivityModel.day_id == day_record.id,
            ItineraryActivityModel.title == req.title
        ).first()

        if not existing_act:
            new_act = ItineraryActivityModel(
                id=act_id,
                day_id=day_record.id,
                time_slot=new_activity_payload["time_slot"],
                title=req.title,
                description=f"Curated spot: {req.title} at {loc_name}",
                activity_type=act_type,
                location_name=loc_name,
                estimated_cost_inr=cost_val,
                booking_required=False,
                is_confirmed=True
            )
            db.add(new_act)
            itin.status = "READY"
            itin.updated_at = now_iso
            db.commit()
            print(f"[DB ITINERARY ADD SUCCESS] Added '{req.title}' to DB trip '{target_trip.id}' Day {day_num} ({new_activity_payload['time_slot']})", flush=True)
    except Exception as db_err:
        db.rollback()
        print(f"[DB ITINERARY ADD WARN] {db_err}", flush=True)

    # 2. Commit to Redis Cache
    itinerary_key = f"trip:itinerary:{target_trip_id}"
    day_key = f"trip:{target_trip_id}:day:{day_num}"
    trip_key = f"trip:{target_trip_id}"
    item_dict = req.dict()
    item_dict["trip_id"] = target_trip_id
    item_dict["day_number"] = day_num
    if day_record:
        item_dict["day_id"] = day_record.id
    item_payload = json.dumps(item_dict)

    try:
        if redis_conn:
            redis_conn.rpush(itinerary_key, item_payload)
            redis_conn.rpush(day_key, item_payload)

            raw_trip_blob = redis_conn.get(trip_key)
            if raw_trip_blob:
                if isinstance(raw_trip_blob, bytes):
                    raw_trip_blob = raw_trip_blob.decode("utf-8")
                trip_blob = json.loads(raw_trip_blob)
                day_str = str(day_num)
                if "days" not in trip_blob:
                    trip_blob["days"] = {}
                if day_str not in trip_blob["days"]:
                    trip_blob["days"][day_str] = []
                trip_blob["days"][day_str].append(new_activity_payload)
                redis_conn.set(trip_key, json.dumps(trip_blob))

            print(f"[REDIS ITINERARY ADD SUCCESS] Pushed '{req.title}' to Redis key '{day_key}'", flush=True)
    except Exception as e:
        print(f"[REDIS ITINERARY WARN] {e}", flush=True)

    return {
        "status": "success",
        "message": f"Added {req.title} to Day {day_num} ({new_activity_payload['time_slot']})",
        "day_number": day_num,
        "day_id": day_record.id if day_record else None,
        "trip_id": target_trip_id,
        "activity": new_activity_payload
    }

@app.get("/api/trips/itinerary/{trip_id}")
def get_trip_itinerary(
    trip_id: str,
    current_user: AuthUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    trip_id = verify_trip_ownership(trip_id, current_user.id, db).id
    from redis_client import redis_conn
    grouped_days = {}
    
    if redis_conn:
        try:
            for day_idx in range(1, 11):
                day_key = f"trip:{trip_id}:day:{day_idx}"
                raw_items = redis_conn.lrange(day_key, 0, -1)
                if raw_items:
                    parsed_items = []
                    for item in raw_items:
                        if isinstance(item, bytes):
                            item = item.decode("utf-8")
                        parsed_items.append(json.loads(item))
                    grouped_days[str(day_idx)] = parsed_items
            
            if not grouped_days:
                main_key = f"trip:itinerary:{trip_id}"
                raw_items = redis_conn.lrange(main_key, 0, -1)
                if raw_items:
                    for item in raw_items:
                        if isinstance(item, bytes):
                            item = item.decode("utf-8")
                        parsed = json.loads(item)
                        d_num = str(parsed.get("day_number", 1))
                        if d_num not in grouped_days:
                            grouped_days[d_num] = []
                        grouped_days[d_num].append(parsed)
        except Exception as e:
            print(f"⚠️ [REDIS GET ITINERARY WARN] {e}", flush=True)
            
    return {
        "trip_id": trip_id,
        "days": grouped_days
    }

# ── DEDICATED ACTIVITY SWAP ENGINE ENDPOINTS ──

class SwapRecommendationRequest(BaseModel):
    trip_id: Optional[str] = "active_trip"
    destination: str
    activity_title: str
    category: Optional[str] = "Sights"
    day_number: Optional[int] = 1

@app.post("/api/trips/itinerary/swap-options", dependencies=[Depends(ai_trip_limiter)])
def get_swap_options(req: SwapRecommendationRequest):
    dest_clean = (req.destination or "Jaipur").strip().title()
    title_clean = (req.activity_title or "Activity").strip()
    cat_clean = req.category or "Sights"
    day_num = req.day_number or 1

    prompt = f"""
    You are an expert itinerary planner for {dest_clean}.
    The traveler wants to replace/swap the activity: "{title_clean}" (Category: {cat_clean}) on Day {day_num} of their trip to {dest_clean}.

    Suggest 3 distinct, authentic alternatives strictly located in {dest_clean} that fit into the same time window.
    DO NOT use user GPS or any location outside of {dest_clean}.

    Return strictly valid JSON:
    {{
      "alternatives": [
        {{
          "id": "alt_1",
          "title": "Specific landmark/activity name in {dest_clean}",
          "category": "{cat_clean}",
          "tag": "Must Visit | Cultural | Hidden Gem",
          "duration": "2 hours",
          "cost": 400,
          "location": "Exact area in {dest_clean}",
          "description": "1 crisp sentence why this is a great alternative to {title_clean}."
        }}
      ]
    }}
    """

    try:
        from ai_provider import complete_json
        parsed = json.loads(complete_json(prompt, temperature=0.3, timeout=12))
        if isinstance(parsed, dict) and "alternatives" in parsed:
            return parsed
    except Exception as e:
        print(f"[SWAP OPTIONS AI WARN] {e}", flush=True)

    # Explicit loud mock fallback options if every AI provider is unavailable
    return {
        "is_mock": True,
        "alternatives": [
            {
                "id": "mock_alt_1",
                "title": "MOCK ALTERNATIVE 1 • MOCK MOCK",
                "category": cat_clean,
                "tag": "MOCK",
                "duration": "MOCK",
                "cost": 0,
                "is_mock": True,
                "location": f"MOCK LOCATION, {dest_clean}",
                "description": "MOCK: Gemini swap-options service unavailable. Inspect backend logs."
            },
            {
                "id": "mock_alt_2",
                "title": "MOCK ALTERNATIVE 2 • MOCK MOCK",
                "category": cat_clean,
                "tag": "MOCK",
                "duration": "MOCK",
                "cost": 0,
                "is_mock": True,
                "location": f"MOCK LOCATION, {dest_clean}",
                "description": "MOCK: Gemini swap-options service unavailable. Inspect backend logs."
            }
        ]
    }


class ExecuteSwapRequest(BaseModel):
    trip_id: Optional[str] = "active_trip"
    day_number: Optional[int] = 1
    old_activity_id: str
    new_activity: dict

@app.post("/api/trips/itinerary/swap-execute", dependencies=[Depends(ai_trip_limiter)])
def execute_swap(
    req: ExecuteSwapRequest,
    current_user: AuthUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    from redis_client import redis_conn
    from models_trip import TripModel
    from models_itinerary import ItineraryModel, ItineraryDayModel, ItineraryActivityModel

    req_trip_id = (req.trip_id or "active_trip").strip()
    target_trip = None

    if req_trip_id and req_trip_id != "active_trip":
        target_trip = db.query(TripModel).filter(TripModel.id == req_trip_id, TripModel.user_id == current_user.id).first()

    if not target_trip:
        target_trip = db.query(TripModel).filter(TripModel.user_id == current_user.id).order_by(TripModel.created_at.desc()).first()

    if not target_trip:
        raise HTTPException(status_code=404, detail="No trip found for authenticated user")

    target_trip_id = target_trip.id
    day_num = req.day_number or 1

    new_act = req.new_activity or {}
    new_title = new_act.get("title", "Alternative Spot")
    new_loc = new_act.get("location", new_act.get("location_name", "City Center"))
    new_cost = int(new_act.get("cost", new_act.get("estimatedCost", 0)))
    new_desc = new_act.get("description", f"Authentic experience in {new_loc}")
    new_tag = new_act.get("tag", new_act.get("category", "Sights"))

    # 1. Update PostgreSQL Database
    if target_trip:
        try:
            itin = db.query(ItineraryModel).filter(ItineraryModel.trip_id == target_trip.id).first()
            if itin:
                day_record = db.query(ItineraryDayModel).filter(
                    ItineraryDayModel.itinerary_id == itin.id,
                    ItineraryDayModel.day_number == day_num
                ).first()

                if day_record:
                    act_record = db.query(ItineraryActivityModel).filter(
                        ItineraryActivityModel.day_id == day_record.id,
                        ItineraryActivityModel.id == req.old_activity_id
                    ).first()

                    if not act_record:
                        act_record = db.query(ItineraryActivityModel).filter(
                            ItineraryActivityModel.day_id == day_record.id
                        ).first()

                    if act_record:
                        act_record.title = new_title
                        act_record.location_name = new_loc
                        act_record.description = new_desc
                        act_record.estimated_cost_inr = new_cost
                        act_record.activity_type = new_tag
                        db.commit()
                        print(f"[DB SWAP SUCCESS] Swapped activity in trip '{target_trip.id}' Day {day_num} -> '{new_title}'", flush=True)
        except Exception as db_err:
            db.rollback()
            print(f"[DB SWAP WARN] {db_err}", flush=True)

    # 2. Update Redis Cache
    if redis_conn:
        try:
            day_key = f"trip:{target_trip_id}:day:{day_num}"
            raw_items = redis_conn.lrange(day_key, 0, -1)
            if raw_items:
                redis_conn.delete(day_key)
                for item in raw_items:
                    if isinstance(item, bytes):
                        item = item.decode("utf-8")
                    parsed = json.loads(item)
                    if parsed.get("id") == req.old_activity_id or parsed.get("item_id") == req.old_activity_id:
                        parsed["title"] = new_title
                        parsed["location"] = new_loc
                        parsed["cost"] = new_cost
                        parsed["description"] = new_desc
                    redis_conn.rpush(day_key, json.dumps(parsed))
            
            print(f"[REDIS SWAP SUCCESS] Updated Redis day_key '{day_key}'", flush=True)
        except Exception as red_err:
            print(f"[REDIS SWAP WARN] {red_err}", flush=True)

    return {
        "status": "success",
        "message": f"Activity swapped successfully to {new_title}",
        "updated_day": day_num,
        "trip_id": target_trip_id,
        "new_activity": new_act
    }

# ── TRIP DOMAIN ENDPOINTS ──

@app.get("/api/trips", dependencies=[Depends(general_limiter)])
def get_trips(current_user: AuthUser = Depends(get_user_or_guest), db: Session = Depends(get_db)):
    if not current_user or current_user.id.startswith("guest_"):
        return []
    db_trips = db.query(TripModel).filter(TripModel.user_id == current_user.id).order_by(TripModel.created_at.desc()).all()
    result = []
    for t in db_trips:
        result.append({
            "id": t.id,
            "userId": t.user_id,
            "title": t.title,
            "status": t.status,
            "itineraryStatus": t.itinerary_status,
            "startDate": t.start_date,
            "endDate": t.end_date,
            "totalDays": t.total_days,
            "destination": t.destination,
            "coverMedia": t.cover_media,
            "travelers": t.travelers,
            "preferencesSnapshot": t.preferences_snapshot,
            "budget": t.budget,
            "progress": t.progress,
            "createdAt": t.created_at,
            "updatedAt": t.updated_at
        })
    return result

import threading

# ── TOUR GUIDE CONCIERGE REST ENDPOINTS ──

class HistoryItem(BaseModel):
    role: str
    content: str

class TourGuideChatRequest(BaseModel):
    message: str
    mode: Optional[str] = "local"
    trip_id: Optional[str] = None
    destination_name: Optional[str] = None
    place_id: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    recent_history: Optional[List[HistoryItem]] = []

@app.post("/api/tour-guide/chat", dependencies=[Depends(ai_chat_limiter)])
@app.post("/api/chat", dependencies=[Depends(ai_chat_limiter)])
def chat_with_concierge(
    payload: TourGuideChatRequest,
    current_user: AuthUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    from tour_guide_service import process_concierge_message
    eff_lat = payload.lat if payload.lat is not None else payload.latitude
    eff_lng = payload.lng if payload.lng is not None else payload.longitude
    recent_hist_dicts = [h.dict() for h in (payload.recent_history or [])]
    return process_concierge_message(
        user_id=current_user.id,
        message=payload.message,
        mode=payload.mode or "local",
        trip_id=payload.trip_id,
        destination_name=payload.destination_name,
        lat=eff_lat if (payload.mode or "local") == "local" else None,
        lng=eff_lng if (payload.mode or "local") == "local" else None,
        recent_history=recent_hist_dicts,
        db=db
    )

@app.get("/api/tour-guide/history", dependencies=[Depends(general_limiter)])
@app.get("/api/chat/history", dependencies=[Depends(general_limiter)])
def get_tour_guide_history(
    trip_id: Optional[str] = None,
    limit: int = 100,
    current_user: AuthUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    from tour_guide_service import fetch_chat_history
    clean_trip_id = None
    if trip_id and str(trip_id).strip().lower() not in ("null", "undefined", "none", ""):
        clean_trip_id = str(trip_id).strip()
    return fetch_chat_history(user_id=current_user.id, trip_id=clean_trip_id, limit=limit, db=db)

@app.post("/trips", status_code=status.HTTP_201_CREATED, dependencies=[Depends(ai_limiter)])
@app.post("/api/trips", status_code=status.HTTP_201_CREATED, dependencies=[Depends(ai_limiter)])
def create_trip(
    trip_data: dict,
    request: Request,
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    token = extract_token(request, authorization)
    try:
        auth_user, user_profile, user_prefs = auth.get_session_user(db, token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    try:
        return create_trip_for_user(db, auth_user, user_profile, user_prefs, trip_data)
    except TripValidationError as err:
        raise HTTPException(status_code=400, detail=str(err))

class TripUpdateSchema(BaseModel):
    status: Optional[str] = None
    title: Optional[str] = None
    startDate: Optional[str] = None
    endDate: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    destination: Optional[Any] = None
    budget: Optional[Any] = None
    travelers: Optional[Any] = None
    itineraryStatus: Optional[str] = None
    itinerary_status: Optional[str] = None

    class Config:
        extra = "allow"

@app.patch("/trips/{trip_id}", dependencies=[Depends(general_limiter)])
@app.patch("/api/trips/{trip_id}", dependencies=[Depends(general_limiter)])
@app.put("/trips/{trip_id}", dependencies=[Depends(general_limiter)])
@app.put("/api/trips/{trip_id}", dependencies=[Depends(general_limiter)])
def update_trip_endpoint(
    trip_id: str,
    payload: TripUpdateSchema,
    current_user: AuthUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    trip = require_owned_trip(db, trip_id, current_user.id)

    if payload.status:
        trip.status = payload.status.upper()
    if payload.title:
        trip.title = payload.title
    if payload.start_date or payload.startDate:
        trip.start_date = payload.start_date or payload.startDate
    if payload.end_date or payload.endDate:
        trip.end_date = payload.end_date or payload.endDate
    if payload.itinerary_status or payload.itineraryStatus:
        trip.itinerary_status = payload.itinerary_status or payload.itineraryStatus
    if payload.destination:
        trip.destination = payload.destination if isinstance(payload.destination, dict) else {"name": str(payload.destination)}
    if payload.budget:
        trip.budget = payload.budget if isinstance(payload.budget, dict) else {"total": payload.budget}
    if payload.travelers:
        trip.travelers = payload.travelers if isinstance(payload.travelers, list) else [payload.travelers]

    now_iso = datetime.now(timezone.utc).isoformat()
    trip.updated_at = now_iso

    db.commit()
    db.refresh(trip)

    return {
        "status": "success",
        "trip_id": trip.id,
        "tripId": trip.id,
        "new_status": trip.status,
        "title": trip.title,
        "message": f"Trip updated to {trip.status}",
        "updatedAt": trip.updated_at
    }

@app.get("/trips/{trip_id}", dependencies=[Depends(general_limiter)])
@app.get("/api/trips/{trip_id}", dependencies=[Depends(general_limiter)])
def get_trip_by_id(
    trip_id: str,
    current_user: AuthUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    trip = require_owned_trip(db, trip_id, current_user.id)


    # Aggregate linked resources
    stays = db.query(TripStayModel).filter(TripStayModel.trip_id == trip.id).order_by(TripStayModel.created_at.desc()).all()
    transports = db.query(TripTransportModel).filter(TripTransportModel.trip_id == trip.id).order_by(TripTransportModel.created_at.desc()).all()
    expenses = db.query(TripExpenseModel).filter(TripExpenseModel.trip_id == trip.id).order_by(TripExpenseModel.created_at.desc()).all()

    itinerary_data = None
    itin = db.query(ItineraryModel).filter(ItineraryModel.trip_id == trip.id).first()
    if itin:
        days = db.query(ItineraryDayModel).filter(ItineraryDayModel.itinerary_id == itin.id).order_by(ItineraryDayModel.day_number.asc()).all()
        itinerary_data = {
            "id": itin.id,
            "tripId": itin.trip_id,
            "status": itin.status,
            "version": itin.version,
            "days": [
                {
                    "id": d.id,
                    "dayNumber": d.day_number,
                    "date": d.date,
                    "title": d.title,
                    "summary": d.summary,
                    "activities": [
                        {
                            "id": a.id,
                            "timeSlot": a.time_slot,
                            "title": a.title,
                            "description": a.description,
                            "activityType": a.activity_type,
                            "locationName": a.location_name,
                            "latitude": a.latitude,
                            "longitude": a.longitude,
                            "estimatedCostInr": a.estimated_cost_inr,
                            "isConfirmed": a.is_confirmed,
                            "isDone": bool(a.is_done)
                        }
                        for a in db.query(ItineraryActivityModel).filter(ItineraryActivityModel.day_id == d.id).all()
                    ]
                }
                for d in days
            ]
        }

    return {
        "id": trip.id,
        "tripId": trip.id,
        "userId": trip.user_id,
        "title": trip.title,
        "status": trip.status,
        "itinerary_status": trip.itinerary_status,
        "itineraryStatus": trip.itinerary_status,
        "startDate": trip.start_date,
        "endDate": trip.end_date,
        "totalDays": trip.total_days,
        "destination": trip.destination,
        "origin": serialize_trip(trip, db)["origin"],
        "travelers": trip.travelers,
        "adultsCount": sum(1 for t in (trip.travelers or []) if t.get("type") != "CHILD"),
        "childrenCount": sum(1 for t in (trip.travelers or []) if t.get("type") == "CHILD"),
        "coverMedia": trip.cover_media,
        "preferencesSnapshot": trip.preferences_snapshot,
        "budget": trip.budget,
        "progress": trip.progress,
        "createdAt": trip.created_at,
        "updatedAt": trip.updated_at,
        "stays": [
            {
                "id": s.id,
                "tripId": s.trip_id,
                "activityId": s.activity_id,
                "hotelName": s.hotel_name,
                "locationName": s.location_name,
                "checkInDate": s.check_in_date,
                "checkOutDate": s.check_out_date,
                "nights": s.nights,
                "pricePerNight": s.price_per_night,
                "totalPrice": s.total_price,
                "status": s.status,
                "confirmationCode": s.confirmation_code,
                "createdAt": s.created_at,
                "updatedAt": s.updated_at
            }
            for s in stays
        ],
        "transports": [
            {
                "id": t.id,
                "tripId": t.trip_id,
                "activityId": t.activity_id,
                "transportType": t.transport_type,
                "providerName": t.provider_name,
                "pickupLocation": t.pickup_location,
                "dropoffLocation": t.dropoff_location,
                "pickupTime": t.pickup_time,
                "estimatedFare": t.estimated_fare,
                "status": t.status,
                "bookingReference": t.booking_reference,
                "createdAt": t.created_at,
                "updatedAt": t.updated_at
            }
            for t in transports
        ],
        "expenses": [
            {
                "id": e.id,
                "tripId": e.trip_id,
                "activityId": e.activity_id,
                "title": e.title,
                "amount": e.amount,
                "category": e.category,
                "paidBy": e.paid_by,
                "isSplit": e.is_split,
                "createdAt": e.created_at
            }
            for e in expenses
        ],
        "itinerary": itinerary_data
    }

def build_trip_export_payload(trip_id: str, db: Session) -> dict:
    from models_trip import TripModel
    from models_itinerary import ItineraryModel, ItineraryDayModel, ItineraryActivityModel
    from models_package import TripStayModel, TripTransportModel, TripExpenseModel

    trip = db.query(TripModel).filter(TripModel.id == trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    dest_dict = trip.destination if isinstance(trip.destination, dict) else {}
    if not dest_dict:
        dest_dict = {"name": getattr(trip, "title", "Destination")}

    budget_dict = trip.budget if isinstance(trip.budget, dict) else {}
    travelers_list = trip.travelers if isinstance(trip.travelers, list) else []

    stays = db.query(TripStayModel).filter(TripStayModel.trip_id == trip.id).all()
    transports = db.query(TripTransportModel).filter(TripTransportModel.trip_id == trip.id).all()
    expenses = db.query(TripExpenseModel).filter(TripExpenseModel.trip_id == trip.id).all()

    itin = db.query(ItineraryModel).filter(ItineraryModel.trip_id == trip.id).first()
    days_data = []
    total_activities = 0
    total_est_cost = 0

    if itin:
        days = db.query(ItineraryDayModel).filter(ItineraryDayModel.itinerary_id == itin.id).order_by(ItineraryDayModel.day_number).all()
        for d in days:
            acts = db.query(ItineraryActivityModel).filter(ItineraryActivityModel.day_id == d.id).all()
            total_activities += len(acts)
            act_list = []
            for a in acts:
                cost = a.estimated_cost_inr or 0
                total_est_cost += cost
                act_list.append({
                    "id": a.id,
                    "timeSlot": a.time_slot,
                    "title": a.title,
                    "description": a.description,
                    "activityType": a.activity_type,
                    "locationName": a.location_name,
                    "latitude": a.latitude,
                    "longitude": a.longitude,
                    "estimatedCostInr": cost,
                    "isConfirmed": a.is_confirmed,
                    "isDone": bool(a.is_done),
                    "bookingRequired": a.booking_required,
                    "bookingReferenceId": a.booking_reference_id
                })
            days_data.append({
                "id": d.id,
                "dayNumber": d.day_number,
                "date": str(d.date) if d.date else None,
                "title": d.title,
                "summary": d.summary,
                "activities": act_list
            })

    total_spend_all = total_est_cost + sum(s.total_price or 0 for s in stays) + sum(t.estimated_fare or 0 for t in transports)

    return {
        "exportVersion": "1.0",
        "exportedAt": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "trip": {
            "id": trip.id,
            "title": trip.title or f"{dest_dict.get('name', 'Destination')} Tour Package",
            "status": trip.status,
            "destination": dest_dict,
            "dates": {
                "startDate": str(trip.start_date) if trip.start_date else None,
                "endDate": str(trip.end_date) if trip.end_date else None,
                "totalDays": trip.total_days or len(days_data)
            },
            "budget": {
                "level": budget_dict.get("level") or "STANDARD",
                "targetAmount": budget_dict.get("targetAmount") or budget_dict.get("target_amount") or 0,
                "currency": budget_dict.get("currency") or "INR"
            },
            "summary": {
                "totalDays": trip.total_days or len(days_data),
                "totalActivities": total_activities,
                "totalStays": len(stays),
                "totalTransports": len(transports),
                "totalEstimatedCostInr": total_spend_all
            },
            "stays": [
                {
                    "id": s.id,
                    "hotelName": s.hotel_name,
                    "locationName": s.location_name,
                    "checkInDate": str(s.check_in_date) if s.check_in_date else None,
                    "checkOutDate": str(s.check_out_date) if s.check_out_date else None,
                    "nights": s.nights,
                    "totalPrice": s.total_price,
                    "status": s.status,
                    "confirmationCode": s.confirmation_code
                }
                for s in stays
            ],
            "transports": [
                {
                    "id": t.id,
                    "transportType": t.transport_type,
                    "providerName": t.provider_name,
                    "pickupLocation": t.pickup_location,
                    "dropoffLocation": t.dropoff_location,
                    "pickupTime": str(t.pickup_time) if t.pickup_time else None,
                    "estimatedFare": t.estimated_fare,
                    "status": t.status,
                    "bookingReference": t.booking_reference
                }
                for t in transports
            ],
            "expenses": [
                {
                    "id": e.id,
                    "title": e.title,
                    "amount": e.amount,
                    "category": e.category,
                    "paidBy": e.paid_by
                }
                for e in expenses
            ],
            "days": days_data
        }
    }

def render_itinerary_print_template(data: dict) -> str:
    trip = data.get("trip", {})
    dest = trip.get("destination", {})
    dest_name = dest.get("name") or dest.get("city") or "Destination"
    dates = trip.get("dates", {})
    summary = trip.get("summary", {})
    days = trip.get("days", [])
    stays = trip.get("stays", [])
    transports = trip.get("transports", [])

    days_html = ""
    for day in days:
        acts_html = ""
        for act in day.get("activities", []):
            cost_str = f"₹{act.get('estimatedCostInr', 0)}" if act.get('estimatedCostInr') is not None else ""
            status_badge = '<span style="background: #E8F0EE; color: #355F58; padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 700;">✓ Confirmed</span>' if act.get("isConfirmed") else '<span style="background: #F1F5F9; color: #64748B; padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 600;">Planned</span>'
            acts_html += f"""
            <div style="display: flex; gap: 16px; padding: 12px 0; border-bottom: 1px dashed #E2E8F0;">
                <div style="min-width: 90px; font-weight: 700; color: #355F58; font-size: 13px;">{act.get('timeSlot', 'Flexible')}</div>
                <div style="flex: 1;">
                    <div style="display: flex; align-items: baseline; justify-content: space-between; gap: 8px;">
                        <h4 style="margin: 0; font-size: 15px; color: #1E293B; font-weight: 700;">{act.get('title', 'Activity')}</h4>
                        <div style="display: flex; align-items: center; gap: 8px;">
                            {f'<span style="font-weight: 700; color: #0F172A; font-size: 13px;">{cost_str}</span>' if cost_str else ''}
                            {status_badge}
                        </div>
                    </div>
                    {f'<p style="margin: 4px 0 0 0; font-size: 12px; color: #64748B;">📍 {act.get("locationName")}</p>' if act.get("locationName") else ''}
                    {f'<p style="margin: 6px 0 0 0; font-size: 13px; color: #475569; line-height: 1.4;">{act.get("description")}</p>' if act.get("description") else ''}
                </div>
            </div>
            """

        days_html += f"""
        <div class="day-section" style="margin-top: 24px; padding: 20px; background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 16px; break-inside: avoid; page-break-inside: avoid;">
            <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #F1F5F9; padding-bottom: 12px; margin-bottom: 12px;">
                <div>
                    <span style="background: #355F58; color: #FFFFFF; padding: 4px 12px; border-radius: 999px; font-size: 12px; font-weight: 800; text-transform: uppercase;">Day {day.get('dayNumber')}</span>
                    <span style="font-size: 13px; color: #64748B; margin-left: 8px; font-weight: 600;">{day.get('date', '')}</span>
                </div>
                <h3 style="margin: 0; font-size: 16px; color: #0F172A; font-weight: 800;">{day.get('title', '')}</h3>
            </div>
            {f'<p style="margin: 0 0 12px 0; font-size: 13px; color: #64748B; font-style: italic;">{day.get("summary")}</p>' if day.get("summary") else ''}
            <div>{acts_html if acts_html else '<p style="font-size: 13px; color: #94A3B8;">No activities scheduled.</p>'}</div>
        </div>
        """

    stays_html = ""
    if stays:
        for s in stays:
            stays_html += f"""
            <div style="padding: 12px 16px; background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 12px; margin-top: 8px;">
                <div style="display: flex; justify-content: space-between; font-weight: 700;">
                    <span style="color: #0F172A;">🏨 {s.get('hotelName', 'Hotel')}</span>
                    <span style="color: #355F58;">₹{s.get('totalPrice', 0)} ({s.get('nights', 1)} nights)</span>
                </div>
                <div style="font-size: 12px; color: #64748B; margin-top: 4px;">📍 {s.get('locationName', '')} · Check-in: {s.get('checkInDate')} to {s.get('checkOutDate')} · Conf Code: {s.get('confirmationCode', 'N/A')}</div>
            </div>
            """

    transports_html = ""
    if transports:
        for t in transports:
            transports_html += f"""
            <div style="padding: 12px 16px; background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 12px; margin-top: 8px;">
                <div style="display: flex; justify-content: space-between; font-weight: 700;">
                    <span style="color: #0F172A;">🚗 {t.get('providerName', 'Transport')} ({t.get('transportType', 'CAB')})</span>
                    <span style="color: #355F58;">₹{t.get('estimatedFare', 0)}</span>
                </div>
                <div style="font-size: 12px; color: #64748B; margin-top: 4px;">From: {t.get('pickupLocation', '')} ➔ To: {t.get('dropoffLocation', '')} · Pickup: {t.get('pickupTime', 'Scheduled')} · Ref: {t.get('bookingReference', 'N/A')}</div>
            </div>
            """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{trip.get('title', 'VoyageAI Itinerary')}</title>
<style>
  @page {{
    margin: 12mm 15mm;
    size: A4 portrait;
  }}
  * {{
    box-sizing: border-box;
    -webkit-print-color-adjust: exact !important;
    print-color-adjust: exact !important;
  }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    color: #1E293B;
    background: #F8FAFC;
    margin: 0;
    padding: 0;
  }}
  .container {{
    max-width: 820px;
    margin: 0 auto;
    padding: 24px;
    background: #FFFFFF;
    min-height: 100vh;
  }}
  .no-print-bar {{
    position: sticky;
    top: 0;
    z-index: 100;
    background: #0F172A;
    color: #FFFFFF;
    padding: 12px 24px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    box-shadow: 0 4px 12px rgba(0,0,0,0.15);
  }}
  .btn-print {{
    background: #355F58;
    color: #FFFFFF;
    border: none;
    padding: 8px 18px;
    border-radius: 999px;
    font-size: 13px;
    font-weight: 700;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    transition: background 0.2s;
  }}
  .btn-print:hover {{
    background: #2C504A;
  }}
  .btn-link {{
    color: #94A3B8;
    text-decoration: none;
    font-size: 13px;
    font-weight: 600;
  }}
  .btn-link:hover {{
    color: #FFFFFF;
  }}
  @media print {{
    .no-print, .no-print-bar {{
      display: none !important;
    }}
    body {{
      background: #FFFFFF !important;
    }}
    .container {{
      padding: 0 !important;
      max-width: 100% !important;
    }}
    .day-section {{
      border: 1px solid #CBD5E1 !important;
      break-inside: avoid !important;
      page-break-inside: avoid !important;
    }}
  }}
</style>
</head>
<body>

<div class="no-print-bar">
  <div style="display: flex; align-items: center; gap: 8px;">
    <span style="font-weight: 800; color: #E8F0EE; letter-spacing: 0.5px;">VoyageAI</span>
    <span style="color: #64748B;">|</span>
    <span style="font-size: 13px; color: #CBD5E1;">Trip Itinerary Export</span>
  </div>
  <div style="display: flex; align-items: center; gap: 16px;">
    <a href="/api/trips/{trip.get('id')}/export?format=json" class="btn-link" target="_blank">📥 Export JSON</a>
    <button onclick="window.print()" class="btn-print">🖨️ Print / Save as PDF</button>
  </div>
</div>

<div class="container">
  <!-- HEADER -->
  <div style="border-bottom: 2px solid #E2E8F0; padding-bottom: 20px;">
    <div style="display: flex; justify-content: space-between; align-items: flex-start;">
      <div>
        <span style="background: #E8F0EE; color: #355F58; padding: 4px 12px; border-radius: 999px; font-size: 12px; font-weight: 800; letter-spacing: 0.5px;">{dest_name.upper()}</span>
        <h1 style="margin: 8px 0 4px 0; font-size: 26px; color: #0F172A; font-weight: 900;">{trip.get('title', 'Tour Package')}</h1>
        <p style="margin: 0; color: #64748B; font-size: 14px; font-weight: 500;">📅 {dates.get('startDate')} to {dates.get('endDate')} · {dates.get('totalDays', len(days))} Days Planned</p>
      </div>
      <div style="text-align: right;">
        <span style="display: inline-block; background: #355F58; color: #FFFFFF; padding: 6px 14px; border-radius: 8px; font-size: 12px; font-weight: 800;">STATUS: {trip.get('status', 'CONFIRMED')}</span>
        <p style="margin: 6px 0 0 0; font-size: 11px; color: #94A3B8;">Trip ID: {trip.get('id', '')}</p>
      </div>
    </div>

    <!-- STATS ROW -->
    <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-top: 20px;">
      <div style="background: #F8FAFC; border: 1px solid #E2E8F0; padding: 12px; border-radius: 12px; text-align: center;">
        <div style="font-size: 11px; color: #64748B; font-weight: 700; text-transform: uppercase;">Duration</div>
        <div style="font-size: 18px; color: #0F172A; font-weight: 800; margin-top: 2px;">{dates.get('totalDays', len(days))} Days</div>
      </div>
      <div style="background: #F8FAFC; border: 1px solid #E2E8F0; padding: 12px; border-radius: 12px; text-align: center;">
        <div style="font-size: 11px; color: #64748B; font-weight: 700; text-transform: uppercase;">Activities</div>
        <div style="font-size: 18px; color: #0F172A; font-weight: 800; margin-top: 2px;">{summary.get('totalActivities', 0)} Spots</div>
      </div>
      <div style="background: #F8FAFC; border: 1px solid #E2E8F0; padding: 12px; border-radius: 12px; text-align: center;">
        <div style="font-size: 11px; color: #64748B; font-weight: 700; text-transform: uppercase;">Accommodations</div>
        <div style="font-size: 18px; color: #0F172A; font-weight: 800; margin-top: 2px;">{len(stays)} Confirmed</div>
      </div>
      <div style="background: #F8FAFC; border: 1px solid #E2E8F0; padding: 12px; border-radius: 12px; text-align: center;">
        <div style="font-size: 11px; color: #64748B; font-weight: 700; text-transform: uppercase;">Est. Spend</div>
        <div style="font-size: 18px; color: #355F58; font-weight: 800; margin-top: 2px;">₹{summary.get('totalEstimatedCostInr', 0)}</div>
      </div>
    </div>
  </div>

  <!-- BOOKINGS SECTION -->
  {f'<div style="margin-top: 20px;"><h3 style="margin: 0 0 8px 0; font-size: 15px; color: #0F172A; font-weight: 800; text-transform: uppercase; letter-spacing: 0.5px;">🏨 Accommodations</h3>{stays_html}</div>' if stays_html else ''}
  {f'<div style="margin-top: 20px;"><h3 style="margin: 0 0 8px 0; font-size: 15px; color: #0F172A; font-weight: 800; text-transform: uppercase; letter-spacing: 0.5px;">🚗 Rides & Transfers</h3>{transports_html}</div>' if transports_html else ''}

  <!-- DAY BY DAY ITINERARY -->
  <div style="margin-top: 24px;">
    <h2 style="margin: 0; font-size: 18px; color: #0F172A; font-weight: 900; text-transform: uppercase; letter-spacing: 0.5px;">📅 Day-by-Day Itinerary</h2>
    {days_html}
  </div>

  <!-- FOOTER -->
  <div style="margin-top: 40px; padding-top: 20px; border-top: 1px solid #E2E8F0; display: flex; justify-content: space-between; align-items: center; font-size: 12px; color: #94A3B8;">
    <div>Generated by <strong>VoyageAI Smart Concierge</strong> · {data.get('exportedAt')}</div>
    <div>Have a safe and wonderful trip! ✈️</div>
  </div>
</div>

<script>
  if (window.location.search.includes('autoprint=true')) {{
    window.addEventListener('load', () => window.print());
  }}
</script>
</body>
</html>"""

@app.get("/trips/{trip_id}/export", dependencies=[Depends(general_limiter)])
@app.get("/api/trips/{trip_id}/export", dependencies=[Depends(general_limiter)])
@app.get("/trips/{trip_id}/pdf", dependencies=[Depends(general_limiter)])
@app.get("/api/trips/{trip_id}/pdf", dependencies=[Depends(general_limiter)])
@app.get("/trips/{trip_id}/download", dependencies=[Depends(general_limiter)])
@app.get("/api/trips/{trip_id}/download", dependencies=[Depends(general_limiter)])
def export_trip_itinerary_endpoint(
    trip_id: str,
    request: Request,
    format: str = Query("json", pattern="^(json|html|pdf|print|html_print)$"),
    current_user: AuthUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    trip = require_owned_trip(db, trip_id, current_user.id)
    export_data = build_trip_export_payload(trip_id=trip.id, db=db)
    path = request.url.path.lower()

    is_html_or_pdf = (
        format.lower() in ["html", "pdf", "print", "html_print"]
        or path.endswith("/pdf")
    )

    if is_html_or_pdf:
        html_content = render_itinerary_print_template(export_data)
        return HTMLResponse(content=html_content, status_code=200)

    return export_data

@app.get("/api/trips/{trip_id}/itinerary", dependencies=[Depends(general_limiter)])
def get_itinerary(
    trip_id: str,
    current_user: AuthUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    from redis_client import redis_conn
    from models_trip import TripModel
    from models_itinerary import ItineraryModel, ItineraryDayModel, ItineraryActivityModel

    req_trip_id = (trip_id or "active_trip").strip()
    trip = None

    if req_trip_id != "active_trip":
        trip = verify_trip_ownership(req_trip_id, current_user.id, db)
    else:
        trip = db.query(TripModel).filter(TripModel.user_id == current_user.id).order_by(TripModel.created_at.desc()).first()

    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found or unauthorized access")

    target_trip_id = trip.id

    itin = db.query(ItineraryModel).filter(ItineraryModel.trip_id == target_trip_id).first() if target_trip_id else None
    days_data = []

    if itin:
        days_records = db.query(ItineraryDayModel).filter(ItineraryDayModel.itinerary_id == itin.id).order_by(ItineraryDayModel.day_number).all()
        for d in days_records:
            activities_records = db.query(ItineraryActivityModel).filter(ItineraryActivityModel.day_id == d.id).all()
            activities_data = []
            for a in activities_records:
                activities_data.append({
                    "id": a.id,
                    "timeSlot": a.time_slot,
                    "title": a.title,
                    "description": a.description,
                    "activityType": a.activity_type,
                    "locationName": a.location_name,
                    "latitude": a.latitude,
                    "longitude": a.longitude,
                    "estimatedCostInr": a.estimated_cost_inr,
                    "bookingRequired": a.booking_required,
                    "isConfirmed": a.is_confirmed,
                    "isDone": bool(a.is_done)
                })

            days_data.append({
                "id": d.id,
                "dayNumber": d.day_number,
                "date": d.date,
                "title": d.title,
                "summary": d.summary,
                "activities": activities_data
            })

    # Redis Fallback / Merge if DB days are empty or for standalone items
    if not days_data and redis_conn:
        try:
            redis_days_map = {}
            for day_idx in range(1, 11):
                day_key = f"trip:{target_trip_id}:day:{day_idx}"
                raw_items = redis_conn.lrange(day_key, 0, -1)
                if raw_items:
                    parsed_activities = []
                    for item in raw_items:
                        if isinstance(item, bytes):
                            item = item.decode("utf-8")
                        parsed = json.loads(item)
                        parsed_activities.append({
                            "id": parsed.get("item_id") or parsed.get("id"),
                            "timeSlot": parsed.get("time_slot") or "Morning",
                            "title": parsed.get("title"),
                            "description": f"Spot: {parsed.get('title')} at {parsed.get('location', '')}",
                            "activityType": parsed.get("tag") or "SIGHTSEEING",
                            "locationName": parsed.get("location"),
                            "estimatedCostInr": 500,
                            "bookingRequired": False,
                            "isConfirmed": True
                        })
                    redis_days_map[day_idx] = parsed_activities

            for d_num, acts in redis_days_map.items():
                days_data.append({
                    "id": f"redis_day_{d_num}",
                    "dayNumber": d_num,
                    "date": f"Day {d_num}",
                    "title": f"Day {d_num} Schedule",
                    "summary": f"Day {d_num} Planned Activities",
                    "activities": acts
                })
        except Exception as r_err:
            print(f"⚠️ [GET ITINERARY REDIS WARN] {r_err}", flush=True)

    status_val = (itin.status if itin else (trip.itinerary_status if trip else "READY"))
    return {
        "id": itin.id if itin else f"itin_{target_trip_id}",
        "tripId": target_trip_id,
        "version": itin.version if itin else 1,
        "status": status_val,
        "providerName": itin.provider_name if itin else "HYBRID_PROVIDER",
        "days": days_data
    }

@app.post("/api/trips/{trip_id}/itinerary/regenerate", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(ai_limiter)])
def regenerate_itinerary(
    trip_id: str,
    current_user: AuthUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    trip = verify_trip_ownership(trip_id, current_user.id, db)

    trip.itinerary_status = "GENERATING"
    db.commit()

    enqueue_itinerary_generation(trip_id)
    return {"status": "GENERATING", "tripId": trip_id}

@app.delete("/api/trips/{trip_id}", dependencies=[Depends(general_limiter)])
def delete_trip(trip_id: str, current_user: AuthUser = Depends(get_current_user), db: Session = Depends(get_db)):
    trip_id = verify_trip_ownership(trip_id, current_user.id, db).id
    itineraries = db.query(ItineraryModel).filter(ItineraryModel.trip_id == trip_id).all()
    for itin in itineraries:
        days = db.query(ItineraryDayModel).filter(ItineraryDayModel.itinerary_id == itin.id).all()
        for day in days:
            db.query(ItineraryActivityModel).filter(ItineraryActivityModel.day_id == day.id).delete()
        db.query(ItineraryDayModel).filter(ItineraryDayModel.itinerary_id == itin.id).delete()
    db.query(ItineraryModel).filter(ItineraryModel.trip_id == trip_id).delete()
    db.query(TripStayModel).filter(TripStayModel.trip_id == trip_id).delete()
    db.query(TripTransportModel).filter(TripTransportModel.trip_id == trip_id).delete()
    db.query(TripExpenseModel).filter(TripExpenseModel.trip_id == trip_id).delete()
    db.query(TripModel).filter(TripModel.id == trip_id, TripModel.user_id == current_user.id).delete()
    db.commit()
    log_event(f"🗑️ Deleted trip {trip_id} from PostgreSQL")
    return {"message": "Trip deleted successfully"}




# ── AI CONCIERGE & ACTIVITY SWAP MUTATION SCHEMAS & ENDPOINTS ──

from pydantic import BaseModel



class ActivityReplacementPayload(BaseModel):
    name: str
    description: Optional[str] = None
    timeSlot: Optional[str] = None
    locationName: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    estimatedCost: Optional[int] = 0
    activityType: Optional[str] = "SIGHTSEEING"

class ActivityPatchRequest(BaseModel):
    isConfirmed: Optional[bool] = None
    is_confirmed: Optional[bool] = None
    status: Optional[str] = None
    title: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    timeSlot: Optional[str] = None
    time_slot: Optional[str] = None
    startTime: Optional[str] = None
    locationName: Optional[str] = None
    location: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    estimatedCost: Optional[int] = None
    estimatedCostInr: Optional[int] = None
    activityType: Optional[str] = None
    bookingRequired: Optional[bool] = None
    bookingReferenceId: Optional[str] = None
    booking_reference_id: Optional[str] = None
    itineraryId: Optional[str] = None
    dayId: Optional[str] = None
    replacement: Optional[Dict[str, Any]] = None
    new_activity: Optional[Dict[str, Any]] = None

    class Config:
        extra = "allow"

class ActivitySwapRequest(BaseModel):
    itineraryId: Optional[str] = None
    dayId: Optional[str] = None
    replacement: Optional[ActivityReplacementPayload] = None

class UniversalSwapRequest(BaseModel):
    trip_id: Optional[str] = None
    tripId: Optional[str] = None
    activity_id: Optional[str] = None
    activityId: Optional[str] = None
    old_activity_id: Optional[str] = None
    day_id: Optional[str] = None
    dayId: Optional[str] = None
    day_number: Optional[int] = None
    itinerary_id: Optional[str] = None
    itineraryId: Optional[str] = None
    new_activity: Optional[Dict[str, Any]] = None
    replacement: Optional[Dict[str, Any]] = None

    class Config:
        extra = "allow"

class DayOptimizationRequest(BaseModel):
    goal: Optional[str] = "MINIMIZE_TRAVEL_TIME"

class RefinementExecutionRequest(BaseModel):
    actions: List[Dict[str, Any]]

@app.post("/api/ai/concierge", dependencies=[Depends(ai_limiter)])
def ai_concierge(
    req: ConciergeRequest,
    current_user: AuthUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    user_msg = req.message or req.query or ""
    if not user_msg or not user_msg.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")
    req.message = user_msg

    effective_user_id = current_user.id
    user_email_log = getattr(current_user, "email", None) or f"user:{effective_user_id}"

    log_frontend_payload(
        endpoint="POST /api/ai/concierge",
        payload=req,
        user_email=user_email_log,
        usage_summary={
            "message": "User query string sent from AI Concierge drawer.",
            "intent": f"Query intent ({req.intent}). Routes query to chat, swap, or search pipeline.",
            "tripId / dayId": "Context identifiers used to assemble trip context into prompt."
        }
    )

    from ai_provider import ai_provider_service

    effective_trip_id = req.tripId or req.trip_id
    effective_activity_id = req.activityId or req.activity_id
    effective_day_id = req.dayId or req.day_id
    effective_itinerary_id = req.itineraryId or req.itinerary_id

    # Build context if tripId is present
    trip_context = getattr(req, "tripContext", None) or getattr(req, "trip_context", None) or {}
    itinerary_summary = []
    trip = None
    if effective_trip_id:
        trip = find_owned_trip(db, effective_trip_id, current_user.id)
        if trip:
            destination_info = trip.destination if isinstance(trip.destination, dict) else {"name": str(trip.destination or "India")}
            if not trip_context:
                trip_context = {
                    "destination": destination_info,
                    "totalDays": trip.total_days,
                    "budgetLevel": (trip.budget or {}).get("level", "MODERATE") if isinstance(trip.budget, dict) else "MODERATE",
                    "startDate": trip.start_date,
                    "endDate": trip.end_date
                }

            itin = db.query(ItineraryModel).filter(ItineraryModel.trip_id == trip.id).first()
            if itin:
                effective_itinerary_id = effective_itinerary_id or itin.id
                days = db.query(ItineraryDayModel).filter(ItineraryDayModel.itinerary_id == itin.id).all()
                for d in days:
                    acts = db.query(ItineraryActivityModel).filter(ItineraryActivityModel.day_id == d.id).all()
                    itinerary_summary.append({
                        "dayNumber": d.day_number,
                        "date": d.date,
                        "activities": [
                            {
                                "id": a.id,
                                "timeSlot": a.time_slot,
                                "title": a.title,
                                "estimatedCostInr": a.estimated_cost_inr,
                                "locationName": a.location_name
                            } for a in acts
                        ]
                    })

    # Add physical user location POI context if latitude and longitude are supplied
    lat = req.latitude if req.latitude is not None else (req.lat if hasattr(req, "lat") else None)
    lng = req.longitude if req.longitude is not None else (req.lng if hasattr(req, "lng") else None)
    if lat is not None and lng is not None:
        try:
            from tour_guide_service import search_nearby_pois
            nearby = search_nearby_pois(float(lat), float(lng), 5000)
            if nearby:
                trip_context["nearbyPlaces"] = [
                    f"{p['name']} ({p.get('category', 'Place')}, {p.get('distanceMeters', 0)}m away)"
                    for p in nearby[:8]
                ]
                trip_context["userLocation"] = {"latitude": float(lat), "longitude": float(lng)}
        except Exception:
            pass

    is_swap_intent = req.intent == "SWAP_ACTIVITY" or "Recommend alternatives for activity:" in req.message or "swap" in req.message.lower()

    if is_swap_intent:
        itin = db.query(ItineraryModel).filter(ItineraryModel.trip_id == trip.id).first() if trip else None
        
        activity = None
        if effective_activity_id:
            activity = db.query(ItineraryActivityModel).filter(ItineraryActivityModel.id == effective_activity_id).first()

        if activity:
            day = db.query(ItineraryDayModel).filter(ItineraryDayModel.id == activity.day_id).first()
            current_activity_dict = {
                "id": activity.id,
                "title": activity.title,
                "description": activity.description,
                "timeSlot": activity.time_slot,
                "locationName": activity.location_name,
                "latitude": activity.latitude,
                "longitude": activity.longitude,
                "estimatedCostInr": activity.estimated_cost_inr,
                "date": day.date if day else "2026-10-15"
            }
            effective_day_id = effective_day_id or (day.id if day else None)
        else:
            act_name = "Selected Activity"
            if "activity:" in req.message:
                act_name = req.message.split("activity:")[-1].strip()
            elif "for " in req.message:
                act_name = req.message.split("for ")[-1].strip()

            dest_obj = trip.destination if trip and isinstance(trip.destination, dict) else {}
            dest_name = dest_obj.get("name") or "Trip Destination"
            dest_lat = dest_obj.get("latitude")
            dest_lng = dest_obj.get("longitude")
            current_activity_dict = {
                "id": effective_activity_id or "act_temp",
                "title": act_name,
                "description": f"Alternative options for {act_name}",
                "timeSlot": "10:00 AM",
                "locationName": dest_name,
                "latitude": dest_lat,
                "longitude": dest_lng,
                "estimatedCostInr": 500,
                "date": "2026-10-15"
            }

        recommendations = ai_provider_service.generate_swap_recommendations(current_activity_dict, trip_context)
        res_payload = {
            "type": "activity_swap_recommendations",
            "tripId": effective_trip_id,
            "itineraryId": effective_itinerary_id or (itin.id if itin else None),
            "dayId": effective_day_id,
            "activityId": effective_activity_id or current_activity_dict["id"],
            "currentActivity": current_activity_dict,
            "recommendations": recommendations,
            "reply": f"Found {len(recommendations)} tailored alternatives for {current_activity_dict['title']}."
        }
        return res_payload

    elif req.intent == "REFINE_ITINERARY":
        actions = ai_provider_service.generate_refinement_actions(req.message, {"context": trip_context, "days": itinerary_summary})
        return {
            "type": "refinement_actions",
            "tripId": effective_trip_id,
            "actions": actions,
            "reply": f"Prepared {len(actions)} optimization action(s) for your itinerary."
        }

    # Default to GENERAL_CHAT / CHAT
    messages_list = []
    if req.messages:
        for m in req.messages:
            r = m.get('role', 'user') if isinstance(m, dict) else (getattr(m, 'role', 'user') or 'user')
            t = m.get('text', '') if isinstance(m, dict) else (getattr(m, 'text', '') or '')
            messages_list.append({"role": str(r), "text": str(t)})
    else:
        messages_list = [{"role": "user", "text": req.message}]
    # Free-form chat goes through the same cost guard as the tour guide chat.
    from cost_guard import evaluate_cost_guards
    should_call_llm, _gate, deflection = evaluate_cost_guards(req.message)
    if not should_call_llm:
        return {
            "type": "chat_response",
            "reply": deflection,
            "actionType": None,
            "actionPayload": None,
        }
    chat_res = ai_provider_service.generate_chat_response(
        messages=messages_list,
        trip_context=trip_context
    )
    if isinstance(chat_res, dict):
        reply_str = chat_res.get("reply") or chat_res.get("text") or "How can I help with your journey?"
        action_type = chat_res.get("actionType")
        action_payload = chat_res.get("actionPayload")
    else:
        reply_str = str(chat_res)
        action_type = None
        action_payload = None

    res_payload = {
        "type": "chat_response",
        "reply": reply_str,
        "actionType": action_type,
        "actionPayload": action_payload
    }

    try:
        log_pipeline_5_steps(
            flow_name="AI Concierge Assistant Chat",
            user_sends=req,
            backend_received={
                "user": user_email_log,
                "message": req.message,
                "intent": req.intent,
                "tripId": effective_trip_id
            },
            given_to_ai={
                "input_data": {"userMessage": req.message, "tripContext": trip_context},
                "prompt": f"User: {req.message} | Context: {trip_context}"
            },
            ai_returned=chat_res,
            send_to_frontend=res_payload
        )
    except Exception:
        pass

    return res_payload

def process_activity_swap_mutation(
    trip_id: Optional[str],
    activity_id: Optional[str],
    rep_data: Dict[str, Any],
    db: Session,
    current_user: Optional[AuthUser] = None
) -> Dict[str, Any]:
    from redis_client import redis_conn
    from models_trip import TripModel
    from models_itinerary import ItineraryModel, ItineraryDayModel, ItineraryActivityModel
    from models_package import TripExpenseModel

    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")

    # 1. Resolve the activity, only within the user's own trips
    owned = find_owned_activity(db, activity_id, current_user.id)
    if not owned:
        raise HTTPException(status_code=404, detail="Activity not found to swap")
    activity, target_trip = owned
    if trip_id and trip_id != "active_trip" and target_trip.id not in trip_id_candidates(trip_id):
        raise HTTPException(status_code=404, detail="Activity not found to swap")

    day = db.query(ItineraryDayModel).filter(ItineraryDayModel.id == activity.day_id).first()

    # 3. Apply Fields from replacement payload
    new_title = rep_data.get("name") or rep_data.get("title") or activity.title
    new_desc = rep_data.get("description") or activity.description
    new_time = rep_data.get("timeSlot") or rep_data.get("time_slot") or rep_data.get("startTime") or activity.time_slot
    new_loc = rep_data.get("locationName") or rep_data.get("location") or activity.location_name
    new_lat = rep_data.get("latitude") if rep_data.get("latitude") is not None else activity.latitude
    new_lng = rep_data.get("longitude") if rep_data.get("longitude") is not None else activity.longitude
    raw_cost = rep_data.get("estimatedCost") or rep_data.get("estimatedCostInr") or rep_data.get("cost")
    new_cost = int(raw_cost) if raw_cost is not None else activity.estimated_cost_inr
    new_type = rep_data.get("activityType") or rep_data.get("category") or rep_data.get("tag") or activity.activity_type

    activity.title = new_title
    activity.description = new_desc
    activity.time_slot = new_time
    activity.location_name = new_loc
    if new_lat is not None:
        activity.latitude = float(new_lat)
    if new_lng is not None:
        activity.longitude = float(new_lng)
    activity.estimated_cost_inr = new_cost
    if new_type:
        activity.activity_type = new_type

    if "isConfirmed" in rep_data:
        activity.is_confirmed = bool(rep_data["isConfirmed"])
    elif "is_confirmed" in rep_data:
        activity.is_confirmed = bool(rep_data["is_confirmed"])
    elif "status" in rep_data and isinstance(rep_data["status"], str):
        activity.is_confirmed = rep_data["status"].upper() in ["COMPLETED", "CONFIRMED", "DONE", "TRUE"]

    # 4. Update linked expense
    if target_trip:
        linked_expense = db.query(TripExpenseModel).filter(
            TripExpenseModel.trip_id == target_trip.id,
            TripExpenseModel.activity_id == activity.id
        ).first()
        if linked_expense:
            linked_expense.title = f"Activity: {activity.title}"
            linked_expense.amount = float(activity.estimated_cost_inr)

    db.commit()
    db.refresh(activity)

    # 5. Flush Redis spotlight or trip cache if present
    if redis_conn and target_trip:
        try:
            day_num = day.day_number if day else 1
            day_key = f"trip:{target_trip.id}:day:{day_num}"
            redis_conn.delete(day_key)
            redis_conn.delete(f"trip:{target_trip.id}:summary")
        except Exception:
            pass

    log_event(f"🔄 Swapped activity {activity.id} -> New Title: '{activity.title}' (Cost: ₹{activity.estimated_cost_inr})")

    return {
        "status": "SUCCESS",
        "message": f"Activity swapped successfully with '{activity.title}'",
        "tripId": target_trip.id if target_trip else (trip_id or ""),
        "dayId": day.id if day else None,
        "updatedActivity": {
            "id": activity.id,
            "timeSlot": activity.time_slot,
            "title": activity.title,
            "description": activity.description,
            "activityType": activity.activity_type,
            "locationName": activity.location_name,
            "latitude": activity.latitude,
            "longitude": activity.longitude,
            "estimatedCostInr": activity.estimated_cost_inr,
            "isConfirmed": activity.is_confirmed
        }
    }

@app.post("/api/ai/concierge/apply-swap", dependencies=[Depends(ai_trip_limiter)])
@app.post("/api/ai/concierge/swap", dependencies=[Depends(ai_trip_limiter)])
@app.post("/api/trips/itinerary/swap", dependencies=[Depends(ai_trip_limiter)])
def apply_concierge_swap_endpoint(
    req: UniversalSwapRequest,
    current_user: AuthUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    effective_trip_id = req.trip_id or req.tripId
    effective_act_id = req.activity_id or req.activityId or req.old_activity_id
    rep = req.new_activity or req.replacement or {}
    return process_activity_swap_mutation(
        trip_id=effective_trip_id,
        activity_id=effective_act_id,
        rep_data=rep,
        db=db,
        current_user=current_user
    )

@app.patch("/api/trips/{trip_id}/itinerary/activities/{activity_id}", dependencies=[Depends(ai_limiter)])
@app.put("/api/trips/{trip_id}/itinerary/activities/{activity_id}", dependencies=[Depends(ai_limiter)])
@app.patch("/api/trips/{trip_id}/activities/{activity_id}", dependencies=[Depends(ai_limiter)])
@app.put("/api/trips/{trip_id}/activities/{activity_id}", dependencies=[Depends(ai_limiter)])
def patch_itinerary_activity(
    trip_id: str,
    activity_id: str,
    req: ActivityPatchRequest,
    current_user: AuthUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # 1. If replacement or new_activity is provided, route through swap mutation:
    if req.replacement or req.new_activity:
        rep = req.replacement or req.new_activity or {}
        if hasattr(rep, "dict"):
            rep = rep.dict()
        elif hasattr(rep, "model_dump"):
            rep = rep.model_dump()
        else:
            rep = dict(rep)

        if req.isConfirmed is not None and "isConfirmed" not in rep:
            rep["isConfirmed"] = req.isConfirmed
        return process_activity_swap_mutation(
            trip_id=trip_id,
            activity_id=activity_id,
            rep_data=rep,
            db=db,
            current_user=current_user
        )

    # 2. In-place field updates (status toggle, isConfirmed, title, etc.):
    from redis_client import redis_conn
    from models_itinerary import ItineraryActivityModel, ItineraryDayModel
    from models_package import TripExpenseModel

    activity, _trip = require_owned_activity(db, activity_id, current_user.id)

    day = db.query(ItineraryDayModel).filter(ItineraryDayModel.id == activity.day_id).first()

    # Update isConfirmed / status
    if req.isConfirmed is not None:
        activity.is_confirmed = bool(req.isConfirmed)
    elif req.is_confirmed is not None:
        activity.is_confirmed = bool(req.is_confirmed)
    elif req.status is not None:
        if req.status.upper() in ["COMPLETED", "CONFIRMED", "DONE", "TRUE"]:
            activity.is_confirmed = True
        elif req.status.upper() in ["PENDING", "PLANNED", "FALSE"]:
            activity.is_confirmed = False

    # Optional field edits
    if req.title or req.name:
        activity.title = req.title or req.name
    if req.description is not None:
        activity.description = req.description
    if req.timeSlot or req.time_slot or req.startTime:
        activity.time_slot = req.timeSlot or req.time_slot or req.startTime
    if req.locationName or req.location:
        activity.location_name = req.locationName or req.location
    if req.latitude is not None:
        activity.latitude = float(req.latitude)
    if req.longitude is not None:
        activity.longitude = float(req.longitude)
    if req.estimatedCost is not None:
        activity.estimated_cost_inr = int(req.estimatedCost)
    elif req.estimatedCostInr is not None:
        activity.estimated_cost_inr = int(req.estimatedCostInr)
    if req.activityType:
        activity.activity_type = req.activityType
    if req.bookingRequired is not None:
        activity.booking_required = bool(req.bookingRequired)
    if req.bookingReferenceId or req.booking_reference_id:
        activity.booking_reference_id = req.bookingReferenceId or req.booking_reference_id

    # Update linked expense if cost or title updated
    linked_expense = db.query(TripExpenseModel).filter(
        TripExpenseModel.trip_id == trip_id,
        TripExpenseModel.activity_id == activity.id
    ).first()
    if linked_expense:
        linked_expense.title = f"Activity: {activity.title}"
        linked_expense.amount = float(activity.estimated_cost_inr)

    db.commit()
    db.refresh(activity)

    # Invalidate Redis cache
    if redis_conn:
        try:
            day_num = day.day_number if day else 1
            redis_conn.delete(f"trip:{trip_id}:day:{day_num}")
            redis_conn.delete(f"trip:{trip_id}:summary")
        except Exception:
            pass

    return {
        "status": "SUCCESS",
        "message": f"Activity '{activity.title}' updated successfully",
        "tripId": trip_id,
        "dayId": day.id if day else None,
        "activityId": activity.id,
        "isConfirmed": activity.is_confirmed,
        "updatedActivity": {
            "id": activity.id,
            "timeSlot": activity.time_slot,
            "title": activity.title,
            "description": activity.description,
            "activityType": activity.activity_type,
            "locationName": activity.location_name,
            "latitude": activity.latitude,
            "longitude": activity.longitude,
            "estimatedCostInr": activity.estimated_cost_inr,
            "isConfirmed": activity.is_confirmed,
            "bookingRequired": activity.booking_required,
            "bookingReferenceId": activity.booking_reference_id
        }
    }

@app.post("/api/trips/{trip_id}/activities/{activity_id}/status", dependencies=[Depends(ai_limiter)])
@app.patch("/api/trips/{trip_id}/activities/{activity_id}/status", dependencies=[Depends(ai_limiter)])
@app.post("/api/trips/{trip_id}/activities/{activity_id}/toggle", dependencies=[Depends(ai_limiter)])
@app.post("/api/trips/{trip_id}/itinerary/activities/{activity_id}/status", dependencies=[Depends(ai_limiter)])
@app.patch("/api/trips/{trip_id}/itinerary/activities/{activity_id}/status", dependencies=[Depends(ai_limiter)])
@app.post("/api/trips/{trip_id}/itinerary/activities/{activity_id}/toggle", dependencies=[Depends(ai_limiter)])
def toggle_activity_status_endpoint(
    trip_id: str,
    activity_id: str,
    payload: Optional[Dict[str, Any]] = None,
    current_user: AuthUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    activity, _trip = require_owned_activity(db, activity_id, current_user.id)

    p = payload or {}
    if "isConfirmed" in p:
        activity.is_confirmed = bool(p["isConfirmed"])
    elif "is_confirmed" in p:
        activity.is_confirmed = bool(p["is_confirmed"])
    elif "status" in p and isinstance(p["status"], str):
        activity.is_confirmed = p["status"].upper() in ["COMPLETED", "CONFIRMED", "DONE", "TRUE"]
    else:
        # Toggle current state
        activity.is_confirmed = not activity.is_confirmed

    db.commit()
    db.refresh(activity)

    return {
        "status": "SUCCESS",
        "tripId": trip_id,
        "activityId": activity.id,
        "isConfirmed": activity.is_confirmed,
        "message": f"Activity status updated to {'CONFIRMED/COMPLETED' if activity.is_confirmed else 'PENDING'}"
    }

@app.post("/api/trips/{trip_id}/itinerary/days/{day_id}/optimize", dependencies=[Depends(ai_limiter)])
def optimize_day_flow_endpoint(
    trip_id: str,
    day_id: str,
    req: DayOptimizationRequest = DayOptimizationRequest(),
    current_user: AuthUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    trip_id = verify_trip_ownership(trip_id, current_user.id, db).id
    try:
        res = optimize_day_flow_service(db, trip_id, day_id, req.goal or "MINIMIZE_TRAVEL_TIME")
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/trips/{trip_id}/itinerary/optimize-budget", dependencies=[Depends(ai_limiter)])
def optimize_budget_endpoint(
    trip_id: str,
    current_user: AuthUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    trip_id = verify_trip_ownership(trip_id, current_user.id, db).id
    try:
        res = optimize_budget_service(db, trip_id)
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/trips/{trip_id}/itinerary/weather-replan", dependencies=[Depends(ai_limiter)])
def weather_replan_endpoint(
    trip_id: str,
    current_user: AuthUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    trip_id = verify_trip_ownership(trip_id, current_user.id, db).id
    try:
        res = weather_replan_service(db, trip_id)
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/trips/{trip_id}/itinerary/refine", dependencies=[Depends(ai_limiter)])
def execute_refinements_endpoint(
    trip_id: str,
    req: RefinementExecutionRequest,
    current_user: AuthUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    trip_id = verify_trip_ownership(trip_id, current_user.id, db).id
    try:
        res = execute_refinement_actions_service(db, trip_id, req.actions)
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

# ── PACKAGE DIMENSION ENDPOINTS (STAYS, TRANSPORTS, EXPENSES) ──


@app.post("/api/trips/{trip_id}/stays", status_code=status.HTTP_201_CREATED, dependencies=[Depends(general_limiter)])
def create_trip_stay(
    trip_id: str,
    stay_data: dict,
    current_user: AuthUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    trip_id = verify_trip_ownership(trip_id, current_user.id, db).id
    stay_id = f"stay_{uuid.uuid4().hex[:12]}"
    now = datetime.utcnow().isoformat() + "Z"

    status_val = stay_data.get("status", "SELECTED")
    if status_val not in ["RECOMMENDED", "SELECTED", "PENDING", "CONFIRMED", "CANCELLED"]:
        status_val = "SELECTED"

    new_stay = TripStayModel(
        id=stay_id,
        trip_id=trip_id,
        activity_id=stay_data.get("activityId"),
        hotel_name=stay_data.get("hotelName", "Hotel"),
        location_name=stay_data.get("locationName", "Central Location"),
        check_in_date=stay_data.get("checkInDate", "2026-10-15"),
        check_out_date=stay_data.get("checkOutDate", "2026-10-19"),
        nights=stay_data.get("nights", 4),
        price_per_night=stay_data.get("pricePerNight", 0),
        total_price=stay_data.get("totalPrice", 0),
        status=status_val,
        confirmation_code=stay_data.get("confirmationCode"),
        created_at=now,
        updated_at=now
    )
    db.add(new_stay)
    db.commit()
    log_event(f"🏨 Persisted stay for trip {trip_id}: {new_stay.hotel_name} (ID: {stay_id})")

    return {
        "id": new_stay.id,
        "tripId": new_stay.trip_id,
        "activityId": new_stay.activity_id,
        "hotelName": new_stay.hotel_name,
        "locationName": new_stay.location_name,
        "checkInDate": new_stay.check_in_date,
        "checkOutDate": new_stay.check_out_date,
        "nights": new_stay.nights,
        "pricePerNight": new_stay.price_per_night,
        "totalPrice": new_stay.total_price,
        "status": new_stay.status,
        "confirmationCode": new_stay.confirmation_code,
        "createdAt": new_stay.created_at,
        "updatedAt": new_stay.updated_at
    }

@app.get("/api/trips/{trip_id}/stays", dependencies=[Depends(general_limiter)])
def get_trip_stays(
    trip_id: str,
    current_user: AuthUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    trip_id = verify_trip_ownership(trip_id, current_user.id, db).id
    stays = db.query(TripStayModel).filter(TripStayModel.trip_id == trip_id).order_by(TripStayModel.created_at.desc()).all()
    return [
        {
            "id": s.id,
            "tripId": s.trip_id,
            "activityId": s.activity_id,
            "hotelName": s.hotel_name,
            "locationName": s.location_name,
            "checkInDate": s.check_in_date,
            "checkOutDate": s.check_out_date,
            "nights": s.nights,
            "pricePerNight": s.price_per_night,
            "totalPrice": s.total_price,
            "status": s.status,
            "confirmationCode": s.confirmation_code,
            "createdAt": s.created_at,
            "updatedAt": s.updated_at
        }
        for s in stays
    ]

@app.post("/api/trips/{trip_id}/transports", status_code=status.HTTP_201_CREATED, dependencies=[Depends(general_limiter)])
def create_trip_transport(
    trip_id: str,
    transport_data: dict,
    current_user: AuthUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    trip_id = verify_trip_ownership(trip_id, current_user.id, db).id
    transport_id = f"trsp_{uuid.uuid4().hex[:12]}"
    now = datetime.utcnow().isoformat() + "Z"

    status_val = transport_data.get("status", "SELECTED")
    if status_val not in ["RECOMMENDED", "SELECTED", "PENDING", "CONFIRMED", "CANCELLED"]:
        status_val = "SELECTED"

    new_transport = TripTransportModel(
        id=transport_id,
        trip_id=trip_id,
        activity_id=transport_data.get("activityId"),
        transport_type=transport_data.get("transportType", "CAB"),
        provider_name=transport_data.get("providerName", "VoyageAI Ride"),
        pickup_location=transport_data.get("pickupLocation", "Current Location"),
        dropoff_location=transport_data.get("dropoffLocation", "Destination"),
        pickup_time=transport_data.get("pickupTime", "Immediate"),
        estimated_fare=transport_data.get("estimatedFare", 0),
        status=status_val,
        booking_reference=transport_data.get("bookingReference"),
        created_at=now,
        updated_at=now
    )
    db.add(new_transport)
    db.commit()
    log_event(f"🚗 Persisted transport for trip {trip_id}: {new_transport.provider_name} (ID: {transport_id})")

    return {
        "id": new_transport.id,
        "tripId": new_transport.trip_id,
        "activityId": new_transport.activity_id,
        "transportType": new_transport.transport_type,
        "providerName": new_transport.provider_name,
        "pickupLocation": new_transport.pickup_location,
        "dropoffLocation": new_transport.dropoff_location,
        "pickupTime": new_transport.pickup_time,
        "estimatedFare": new_transport.estimated_fare,
        "status": new_transport.status,
        "bookingReference": new_transport.booking_reference,
        "createdAt": new_transport.created_at,
        "updatedAt": new_transport.updated_at
    }

@app.get("/api/trips/{trip_id}/transports", dependencies=[Depends(general_limiter)])
def get_trip_transports(
    trip_id: str,
    current_user: AuthUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    trip_id = verify_trip_ownership(trip_id, current_user.id, db).id
    transports = db.query(TripTransportModel).filter(TripTransportModel.trip_id == trip_id).order_by(TripTransportModel.created_at.desc()).all()
    return [
        {
            "id": t.id,
            "tripId": t.trip_id,
            "activityId": t.activity_id,
            "transportType": t.transport_type,
            "providerName": t.provider_name,
            "pickupLocation": t.pickup_location,
            "dropoffLocation": t.dropoff_location,
            "pickupTime": t.pickup_time,
            "estimatedFare": t.estimated_fare,
            "status": t.status,
            "bookingReference": t.booking_reference,
            "createdAt": t.created_at,
            "updatedAt": t.updated_at
        }
        for t in transports
    ]

@app.post("/api/trips/{trip_id}/expenses", status_code=status.HTTP_201_CREATED, dependencies=[Depends(general_limiter)])
def create_trip_expense(
    trip_id: str,
    expense_data: dict,
    current_user: AuthUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    trip_id = verify_trip_ownership(trip_id, current_user.id, db).id
    expense_id = f"exp_{uuid.uuid4().hex[:12]}"
    now = datetime.utcnow().isoformat() + "Z"

    category_val = expense_data.get("category", "Other")
    if category_val not in ["Transport", "Hotel", "Food", "Activities", "Shopping", "Other"]:
        category_val = "Other"

    paid_by_val = expense_data.get("paidBy")
    if not paid_by_val:
        from models_db import UserProfileModel
        prof = db.query(UserProfileModel).filter(UserProfileModel.user_id == current_user.id).first()
        if prof and prof.first_name:
            paid_by_val = f"{prof.first_name} {prof.last_name or ''}".strip()
        else:
            paid_by_val = getattr(current_user, "email", "Me") or "Me"

    new_expense = TripExpenseModel(
        id=expense_id,
        trip_id=trip_id,
        activity_id=expense_data.get("activityId"),
        title=expense_data.get("title", "Expense"),
        amount=float(expense_data.get("amount", 0.0)),
        category=category_val,
        paid_by=paid_by_val,
        is_split=bool(expense_data.get("isSplit", False)),
        created_at=now
    )
    db.add(new_expense)
    db.commit()
    log_event(f"💸 Persisted expense for trip {trip_id}: {new_expense.title} - ₹{new_expense.amount} (ID: {expense_id})")

    return {
        "id": new_expense.id,
        "tripId": new_expense.trip_id,
        "activityId": new_expense.activity_id,
        "title": new_expense.title,
        "amount": new_expense.amount,
        "category": new_expense.category,
        "paidBy": new_expense.paid_by,
        "isSplit": new_expense.is_split,
        "createdAt": new_expense.created_at
    }

@app.get("/api/trips/{trip_id}/expenses", dependencies=[Depends(general_limiter)])
def get_trip_expenses(
    trip_id: str,
    current_user: AuthUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    trip_id = verify_trip_ownership(trip_id, current_user.id, db).id
    expenses = db.query(TripExpenseModel).filter(TripExpenseModel.trip_id == trip_id).order_by(TripExpenseModel.created_at.desc()).all()
    return [
        {
            "id": e.id,
            "tripId": e.trip_id,
            "activityId": e.activity_id,
            "title": e.title,
            "amount": e.amount,
            "category": e.category,
            "paidBy": e.paid_by,
            "isSplit": e.is_split,
            "createdAt": e.created_at
        }
        for e in expenses
    ]

# ── TOUR GUIDE API ENDPOINTS ──

from tour_guide_service import (
    search_nearby_pois, rank_places, generate_tour_guide_response,
    get_or_create_session, add_message_to_session,
    should_refresh_nearby, check_proactive_alert, haversine_meters,
    resolve_active_place
)


class TourGuideVisitRequest(BaseModel):
    place_id: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None

@app.get("/api/tour-guide/nearby", dependencies=[Depends(osm_limiter)])
async def tour_guide_nearby(
    lat: float,
    lng: float,
    radius: int = 5000,
    current_user: AuthUser = Depends(get_user_or_guest),
    db: Session = Depends(get_db)
):
    """Discover nearby POIs within radius using Google Places Platform proxy with Redis caching."""
    radius = min(radius, 5000)

    user_id = current_user.id
    from models_db import UserPreferencesModel
    user_prefs_obj = db.query(UserPreferencesModel).filter(UserPreferencesModel.user_id == user_id).first()
    user_prefs = None
    if user_prefs_obj:
        user_prefs = {
            "activityInterests": user_prefs_obj.activity_interests or [],
            "travelStyles": user_prefs_obj.travel_styles or [],
        }

    log_event(f"TOUR GUIDE NEARBY | User: {user_id} | Center: ({lat:.4f}, {lng:.4f}) | Radius: {radius}m")

    # Primary & ONLY: Google Places Platform
    from services.google_maps_service import search_nearby_places
    raw_places = await search_nearby_places(lat, lng, radius)

    ranked = rank_places(raw_places, user_prefs, limit=10)

    # Update session
    session = get_or_create_session(user_id)
    session["nearby_places"] = ranked
    session["last_nearby_lat"] = lat
    session["last_nearby_lng"] = lng
    session["last_nearby_refresh"] = __import__("time").time()

    # Check proactive alert
    alert_place = check_proactive_alert(session, lat, lng, ranked)

    return {
        "places": ranked,
        "center": {"latitude": lat, "longitude": lng},
        "radius_m": radius,
        "count": len(ranked),
        "total_raw": len(raw_places),
        "proactive_alert": alert_place
    }



@app.post("/api/tour-guide/visit", dependencies=[Depends(general_limiter)])
def tour_guide_visit(
    req: TourGuideVisitRequest,
    current_user: AuthUser = Depends(get_user_or_guest),
    db: Session = Depends(get_db)
):
    """Set the current place focus for the tour guide session."""
    user_id = current_user.id
    session = get_or_create_session(user_id)
    session["current_place_id"] = req.place_id

    place_context = None
    for p in session.get("nearby_places", []):
        if p["id"] == req.place_id:
            place_context = p
            break

    log_event(f"TOUR GUIDE VISIT | User: {user_id} | Focused on: {place_context.get('name') if place_context else req.place_id}")

    return {
        "status": "focused",
        "place": place_context,
        "session_messages": len(session.get("messages", []))
    }

@app.get("/api/tour-guide/session", dependencies=[Depends(general_limiter)])
def tour_guide_session(
    current_user: AuthUser = Depends(get_user_or_guest),
    db: Session = Depends(get_db)
):
    """Get current tour guide session state."""
    user_id = current_user.id
    session = get_or_create_session(user_id)
    return {
        "currentPlaceId": session.get("current_place_id"),
        "messageCount": len(session.get("messages", [])),
        "nearbyCount": len(session.get("nearby_places", [])),
        "autoGuideEnabled": session.get("auto_guide_enabled", False),
        "lastNearbyRefresh": session.get("last_nearby_refresh", 0)
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True, access_log=True)
# Reload triggered
