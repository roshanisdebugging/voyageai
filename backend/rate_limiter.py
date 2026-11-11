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

async def check_sliding_window_rate_limit(
    redis_key: str, limit: int, window_seconds: int, fail_closed: bool = False
) -> bool:
    """
    Executes the atomic Lua sliding-window rate limit check against Redis.
    Raises HTTPException(429) if limit is exceeded, with Retry-After header.
    If Redis is unreachable: fail_closed=True rejects with 503 (use for login and
    paid AI calls); otherwise the request is allowed with a warning.
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
        if fail_closed:
            logger.error(f"[RATE LIMITER] Redis unavailable for '{redis_key}' ({e}). Rejecting request.")
            raise HTTPException(status_code=503, detail="Service temporarily unavailable. Please try again shortly.")
        logger.warning(f"[RATE LIMITER WARN] Redis unavailable for '{redis_key}' ({e}). Allowing request.")
        return True


# Number of trusted reverse proxies in front of the app. Default 0: the API is
# reached directly (localhost), so X-Forwarded-For is entirely client-controlled
# and ignored. Behind a proxy (nginx, a tunnel) set this to the number of proxies:
# each appends the address it saw, so the entry that many places from the right
# is the real client.
TRUSTED_PROXY_HOPS = int(os.getenv("TRUSTED_PROXY_HOPS", "0"))


def client_ip_from(headers, fallback_host: Optional[str]) -> str:
    forwarded_for = headers.get("x-forwarded-for")
    if forwarded_for and TRUSTED_PROXY_HOPS > 0:
        hops = [h.strip() for h in forwarded_for.split(",") if h.strip()]
        if len(hops) >= TRUSTED_PROXY_HOPS:
            return hops[-TRUSTED_PROXY_HOPS]
    return fallback_host or "127.0.0.1"


def normalize_ip(ip_str: str) -> str:
    """IPv4 stays exact; IPv6 is masked to its /64 network so one host can't rotate addresses."""
    try:
        ip = ipaddress.ip_address(ip_str.strip())
        if ip.version == 6:
            return str(ipaddress.ip_network(f"{ip}/64", strict=False).network_address)
        return str(ip)
    except ValueError:
        return ip_str.strip()


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
    def __init__(self, requests: int, window_seconds: int, key_prefix: str = "rl:net", fail_closed: bool = False):
        self.requests = requests
        self.window_seconds = window_seconds
        self.key_prefix = key_prefix
        self.fail_closed = fail_closed

    async def __call__(self, request: Request) -> bool:
        client_ip = self._extract_client_ip(request)
        redis_key = f"{self.key_prefix}:{normalize_ip(client_ip)}"
        return await check_sliding_window_rate_limit(
            redis_key, self.requests, self.window_seconds, fail_closed=self.fail_closed
        )

    @staticmethod
    def _extract_client_ip(request: Request) -> str:
        return client_ip_from(request.headers, request.client.host if request.client else None)

    @staticmethod
    def _normalize_ip(ip_str: str) -> str:
        return normalize_ip(ip_str)


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
    def __init__(
        self,
        requests: int,
        window_seconds: int,
        key_prefix: str = "rl:usr",
        allow_guest: bool = False,
        fail_closed: bool = False,
    ):
        self.requests = requests
        self.window_seconds = window_seconds
        self.key_prefix = key_prefix
        self.allow_guest = allow_guest
        self.fail_closed = fail_closed

    async def __call__(self, request: Request) -> bool:
        user_id = await self._resolve_user_id(request)
        if not user_id:
            raise HTTPException(status_code=401, detail="Authentication required")

        redis_key = f"{self.key_prefix}:{user_id}"
        return await check_sliding_window_rate_limit(
            redis_key, self.requests, self.window_seconds, fail_closed=self.fail_closed
        )

    async def _resolve_user_id(self, request: Request) -> Optional[str]:
        # The limiter only needs a user ID for its Redis key. It stores that ID on
        # request.state.rate_limit_user_id and never touches request.state.user,
        # which belongs to get_current_user and must always hold a full AuthUser.
        cached = getattr(request.state, "rate_limit_user_id", None)
        if cached:
            return cached

        user = getattr(request.state, "user", None)
        uid = getattr(user, "id", None)
        if uid and (getattr(user, "status", None) != "GUEST" or self.allow_guest):
            request.state.rate_limit_user_id = str(uid)
            return str(uid)

        # Session token from cookie, Authorization, or X-Auth-Token (never from the URL)
        token = request.cookies.get("voyageai_session")
        if not token:
            auth_hdr = request.headers.get("authorization") or request.headers.get("x-auth-token")
            if auth_hdr:
                clean_hdr = auth_hdr.strip()
                if clean_hdr.lower().startswith("bearer "):
                    token = clean_hdr[7:].strip()
                else:
                    token = clean_hdr

        if token:
            # Step 2: Check Redis Session Cache (Cache Hit: sub-millisecond return)
            session_cache_key = f"session_cache:{token}"
            try:
                cached_uid = await redis_client.get(session_cache_key)
                if cached_uid:
                    request.state.rate_limit_user_id = str(cached_uid)
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
                    request.state.rate_limit_user_id = user_id_str

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
            # Guests are limited per network address. A guest ID cookie or header is
            # chosen by the client and could be rotated to dodge the limit.
            client_ip = client_ip_from(request.headers, request.client.host if request.client else None)
            return f"guest:{normalize_ip(client_ip)}"

        return None


async def check_ws_rate_limit(bucket: str, subject: str, limit: int, window_seconds: int = 60) -> None:
    """Rate limit for WebSocket actions. Raises HTTPException(429/503) like the HTTP limiters."""
    await check_sliding_window_rate_limit(f"rl:ws:{bucket}:{subject}", limit, window_seconds, fail_closed=True)


# Backward compatibility aliases
RateLimiter = NetworkRateLimiter
