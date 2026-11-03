import os
import time
import uuid
import logging
import ipaddress
from typing import Optional, Any
from fastapi import Request, HTTPException
import redis.asyncio as aioredis

logger = logging.getLogger("voyageai.rate_limiter")

# ----------------------------------------------------------------------------
# Redis Connection Configuration
# ----------------------------------------------------------------------------
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_URL = os.getenv("REDIS_URL", f"redis://{REDIS_HOST}:{REDIS_PORT}/0")

# protocol=2 is required for maximum compatibility with Redis 3.x/4.x/5.x (RESP2 protocol)
redis_client = aioredis.from_url(
    REDIS_URL,
    decode_responses=True,
    protocol=2,
    socket_timeout=2.0,
    socket_connect_timeout=2.0
)

# ----------------------------------------------------------------------------
# Atomic Redis Lua Sliding Window Script
# Eliminates the permanent 429 lockout / double-counting bug by writing to
# ZSET ONLY when the request is below the threshold.
# ----------------------------------------------------------------------------
SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4] or tostring(now)
local clear_before = now - window

-- 1. Remove expired timestamps outside the rolling window
redis.call('ZREMRANGEBYSCORE', key, 0, clear_before)

-- 2. Check current active count
local current_requests = redis.call('ZCARD', key)

-- 3. If within limit, record timestamp and set TTL
if current_requests < limit then
    redis.call('ZADD', key, now, member)
    redis.call('EXPIRE', key, window + 1)
    return {1, limit - current_requests - 1, 0} -- {allowed (1), remaining, retry_after (0)}
else
    -- Calculate retry-after based on oldest entry in window
    local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    local retry_after = window
    if #oldest > 0 then
        retry_after = math.max(1, math.ceil(tonumber(oldest[2]) + window - now))
    end
    return {0, 0, retry_after} -- {blocked (0), remaining (0), retry_after}
end
"""

_script_executor = redis_client.register_script(SLIDING_WINDOW_LUA)

async def check_sliding_window_rate_limit(redis_key: str, limit: int, window_seconds: int) -> bool:
    """
    Executes the atomic Lua sliding-window rate limit check against Redis.
    Raises HTTPException(429) if limit is exceeded, with Retry-After header.
    Fails open with a warning log if Redis is unreachable or times out.
    """
    now = time.time()
    unique_member = f"{now}:{uuid.uuid4().hex[:8]}"

    try:
        result = await _script_executor(
            keys=[redis_key],
            args=[now, window_seconds, limit, unique_member]
        )
        allowed = int(result[0])
        retry_after = int(result[2])

        if allowed == 0:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded. Please slow down.",
                headers={"Retry-After": str(retry_after)}
            )

        return True

    except HTTPException:
        raise
    except Exception as e:
        logger.warning(
            f"[RATE LIMITER WARN] Redis rate limit check failed for '{redis_key}' ({e}). "
            "Failing open to avoid service disruption."
        )
        return True


# ----------------------------------------------------------------------------
# 1. NetworkRateLimiter: IP / Subnet Rate Limiter
# ----------------------------------------------------------------------------
class NetworkRateLimiter:
    """
    Public and authentication endpoint rate limiter.
    Extracts client IP from proxy headers (X-Forwarded-For, X-Real-IP) or socket.
    Normalizes:
      - IPv4: kept as /32 (exact address)
      - IPv6: masked to /64 base network prefix to stop IPv6 subnet hopping
    """
    def __init__(self, requests: int, window_seconds: int, key_prefix: str = "rl:net"):
        self.requests = requests
        self.window_seconds = window_seconds
        self.key_prefix = key_prefix

    async def __call__(self, request: Request) -> bool:
        client_ip = self._extract_client_ip(request)
        normalized_net = self._normalize_ip(client_ip)
        redis_key = f"{self.key_prefix}:{normalized_net}"
        return await check_sliding_window_rate_limit(redis_key, self.requests, self.window_seconds)

    @staticmethod
    def _extract_client_ip(request: Request) -> str:
        forwarded_for = request.headers.get("x-forwarded-for") or request.headers.get("X-Forwarded-For")
        if forwarded_for:
            client_ip = forwarded_for.split(",")[0].strip()
            if client_ip:
                return client_ip

        real_ip = request.headers.get("x-real-ip") or request.headers.get("X-Real-IP")
        if real_ip and real_ip.strip():
            return real_ip.strip()

        if request.client and request.client.host:
            return request.client.host

        return "127.0.0.1"

    @staticmethod
    def _normalize_ip(ip_str: str) -> str:
        try:
            ip = ipaddress.ip_address(ip_str.strip())
            if ip.version == 6:
                # Mask IPv6 to /64 base network address
                net = ipaddress.ip_network(f"{ip}/64", strict=False)
                return str(net.network_address)
            return str(ip)
        except ValueError:
            return ip_str.strip()


# ----------------------------------------------------------------------------
# 2. UserRateLimiter: Authenticated User Rate Limiter with Redis Session Cache
# ----------------------------------------------------------------------------
SESSION_CACHE_TTL = int(os.getenv("SESSION_CACHE_TTL", "3600"))

async def cache_user_session(token: str, user_id: str, ttl: int = SESSION_CACHE_TTL) -> None:
    """Pre-warm or update user session cache in Redis."""
    if not token or not user_id:
        return
    try:
        await redis_client.set(f"session_cache:{token}", str(user_id), ex=ttl)
    except Exception as e:
        logger.warning(f"[SESSION CACHE WARN] Failed to pre-warm session cache: {e}")

async def invalidate_cached_session(token: str) -> None:
    """Invalidate user session cache in Redis upon logout or session revocation."""
    if not token:
        return
    try:
        await redis_client.delete(f"session_cache:{token}")
    except Exception as e:
        logger.warning(f"[SESSION CACHE WARN] Failed to invalidate session cache: {e}")

class UserRateLimiter:
    """
    Authenticated user rate limiter for heavy compute and paid external APIs.
    - Resolves user from request.state.user, or async Redis session cache, or database.
    - Eliminates synchronous SessionLocal() DB bottleneck via cache-aside.
    - If unauthenticated, raises HTTPException(401, detail="Authentication required").
    - Constructs key: {key_prefix}:{user.id}.
    - Immune to IP rotation, VPNs, or IPv6 pool hopping.
    """
    def __init__(self, requests: int, window_seconds: int, key_prefix: str = "rl:usr", allow_guest: bool = False):
        self.requests = requests
        self.window_seconds = window_seconds
        self.key_prefix = key_prefix
        self.allow_guest = allow_guest

    async def __call__(self, request: Request) -> bool:
        user_id = await self._resolve_user_id(request)
        if not user_id:
            raise HTTPException(status_code=401, detail="Authentication required")

        redis_key = f"{self.key_prefix}:{user_id}"
        return await check_sliding_window_rate_limit(redis_key, self.requests, self.window_seconds)

    async def _resolve_user_id(self, request: Request) -> Optional[str]:
        # Step 1: Check if user was already resolved and attached to request.state
        user = getattr(request.state, "user", None)
        if user is not None:
            status = getattr(user, "status", None) or (user.get("status") if isinstance(user, dict) else None)
            uid = getattr(user, "id", None) or (user.get("id") if isinstance(user, dict) else None)
            if uid and (status != "GUEST" or self.allow_guest):
                return str(uid)

        # Extract session token from cookie, Authorization, or X-Auth-Token
        token = request.cookies.get("voyageai_session")
        if not token:
            auth_hdr = request.headers.get("authorization") or request.headers.get("x-auth-token")
            if auth_hdr:
                clean_hdr = auth_hdr.strip()
                if clean_hdr.lower().startswith("bearer "):
                    token = clean_hdr[7:].strip()
                else:
                    token = clean_hdr

        if not token and hasattr(request, "query_params"):
            token = request.query_params.get("token") or request.query_params.get("session_token")

        if token:
            # Step 2: Check Redis Session Cache (Cache Hit: sub-millisecond return)
            session_cache_key = f"session_cache:{token}"
            try:
                cached_uid = await redis_client.get(session_cache_key)
                if cached_uid:
                    # Attach minimal user representation to avoid re-resolving in downstream dependencies
                    request.state.user = {"id": str(cached_uid), "status": "ACTIVE"}
                    return str(cached_uid)
            except Exception as cache_read_err:
                logger.warning(f"[SESSION CACHE WARN] Redis read failed for {session_cache_key} ({cache_read_err}), falling back to DB.")

            # Step 3: Cache Miss -> Fallback to Database once, then populate cache
            try:
                from database import SessionLocal
                import auth
                with SessionLocal() as db:
                    auth_user, _, _ = auth.get_session_user(db, token)
                    request.state.user = auth_user
                    user_id_str = str(auth_user.id)

                    # Populate cache in Redis with TTL matching session lifetime
                    try:
                        await redis_client.set(session_cache_key, user_id_str, ex=SESSION_CACHE_TTL)
                    except Exception as cache_write_err:
                        logger.warning(f"[SESSION CACHE WARN] Redis write failed for {session_cache_key} ({cache_write_err}).")

                    return user_id_str
            except Exception:
                pass

        # Step 4: If guest sessions are explicitly permitted, extract guest_session_id
        if self.allow_guest:
            guest_id = request.cookies.get("guest_session_id") or request.headers.get("x-guest-id") or (
                request.query_params.get("guest_id") if hasattr(request, "query_params") else None
            )
            if guest_id and str(guest_id).strip():
                return str(guest_id).strip()

        return None


# Backward compatibility aliases
RateLimiter = NetworkRateLimiter
