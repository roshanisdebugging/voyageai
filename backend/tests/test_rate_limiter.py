import asyncio
import time
import ipaddress
from types import SimpleNamespace
from unittest.mock import MagicMock
from fastapi import HTTPException, Request

from rate_limiter import NetworkRateLimiter, UserRateLimiter, check_sliding_window_rate_limit, client_ip_from, redis_client

async def test_ipv6_normalization():
    print("\n--- TEST 1: IPv6 Subnet Hopping Prevention (/64 Normalization) ---")
    subnet_base = "2001:db8:abcd:12"
    ips_in_same_subnet = [
        f"{subnet_base}::1",
        f"{subnet_base}::2",
        f"{subnet_base}:ffff:ffff:ffff:ffff",
        f"{subnet_base}:dead:beef:cafe:1234",
    ]
    
    normalized_results = [NetworkRateLimiter._normalize_ip(ip) for ip in ips_in_same_subnet]
    print(f"Original IPv6 IPs: {ips_in_same_subnet}")
    print(f"Normalized Subnets: {normalized_results}")
    
    # All must map to the same base /64 subnet
    assert len(set(normalized_results)) == 1, "Failed: IPv6 addresses did not normalize to identical /64 subnet"
    assert normalized_results[0] == "2001:db8:abcd:12::", f"Unexpected normalized format: {normalized_results[0]}"
    
    # Test IPv4
    ipv4 = "198.51.100.42"
    assert NetworkRateLimiter._normalize_ip(ipv4) == ipv4, "Failed: IPv4 was altered"
    print("✅ TEST 1 PASSED: IPv6 subnet hopping prevented; IPv4 remains exact.")

def test_forwarded_for_spoofing():
    print("\n--- TEST 1b: X-Forwarded-For spoofing is ignored ---")
    import rate_limiter
    headers = {"x-forwarded-for": "1.2.3.4, 203.0.113.9"}
    original = rate_limiter.TRUSTED_PROXY_HOPS
    try:
        # No proxy (default): the header is client-controlled and ignored.
        rate_limiter.TRUSTED_PROXY_HOPS = 0
        assert client_ip_from(headers, "10.0.0.1") == "10.0.0.1"
        # One proxy: only the address that proxy appended (the last entry) is trusted.
        rate_limiter.TRUSTED_PROXY_HOPS = 1
        assert client_ip_from(headers, "10.0.0.1") == "203.0.113.9"
        assert client_ip_from({}, "10.0.0.1") == "10.0.0.1"
    finally:
        rate_limiter.TRUSTED_PROXY_HOPS = original
    print("✅ TEST 1b PASSED: forwarded addresses are only trusted behind a configured proxy.")

async def test_no_double_counting_and_lockout():
    print("\n--- TEST 2: Elimination of 429 Permanent Lockout (Double Counting) ---")
    test_key = "test:rl:lockout_verification"
    await redis_client.delete(test_key)
    
    limit = 3
    window = 4
    
    # 1. Send 3 allowed requests
    for i in range(limit):
        allowed = await check_sliding_window_rate_limit(test_key, limit=limit, window_seconds=window)
        assert allowed is True, f"Request {i+1} should have been allowed"
    print(f"Sent {limit} initial requests: all allowed.")
    
    # 2. Verify count in Redis is 3
    count_before = await redis_client.zcard(test_key)
    assert count_before == 3, f"Expected 3 entries in ZSET, got {count_before}"
    
    # 3. Hammer with 5 blocked requests
    blocked_count = 0
    retry_after_val = 0
    for i in range(5):
        try:
            await check_sliding_window_rate_limit(test_key, limit=limit, window_seconds=window)
        except HTTPException as exc:
            assert exc.status_code == 429
            blocked_count += 1
            retry_after_val = int(exc.headers.get("Retry-After", 0))
    print(f"Hammered with 5 blocked requests: all rejected with 429 (Retry-After: {retry_after_val}s).")
    assert blocked_count == 5
    
    # 4. Check ZSET size: MUST still be 3 (not 8)
    count_after = await redis_client.zcard(test_key)
    print(f"ZSET count after 5 blocked requests: {count_after} (Expected: 3, NOT 8)")
    assert count_after == 3, f"Double-counting bug detected! ZSET grew to {count_after}"
    
    # Clean up
    await redis_client.delete(test_key)
    print("✅ TEST 2 PASSED: Blocked requests are NOT added to Redis ZSET. Zero lockout extension.")

async def test_user_limiter_auth_enforcement():
    print("\n--- TEST 3: UserRateLimiter Authentication Enforcement ---")
    limiter = UserRateLimiter(requests=5, window_seconds=60, key_prefix="test:rl:usr")
    
    # A. Unauthenticated request without state or cookies -> must raise 401
    mock_req_unauth = MagicMock(spec=Request)
    mock_req_unauth.state = SimpleNamespace(user=None)
    mock_req_unauth.cookies = {}
    mock_req_unauth.headers = {}
    mock_req_unauth.query_params = {}
    
    raised_401 = False
    try:
        await limiter(mock_req_unauth)
    except HTTPException as e:
        if e.status_code == 401:
            raised_401 = True
    assert raised_401, "Failed: Unauthenticated request did not raise HTTP 401"
    print("Unauthenticated request safely blocked with HTTP 401.")
    
    # B. Authenticated user request -> succeeds and keys by user_id
    mock_req_auth = MagicMock(spec=Request)
    mock_user = SimpleNamespace(id="usr_prod_secure_99", status="ACTIVE")
    mock_req_auth.state = SimpleNamespace(user=mock_user)
    
    test_key = "test:rl:usr:usr_prod_secure_99"
    await redis_client.delete(test_key)
    
    allowed = await limiter(mock_req_auth)
    assert allowed is True
    count = await redis_client.zcard(test_key)
    assert count == 1, f"Expected 1 request recorded for user key, got {count}"
    print(f"Authenticated request keyed on user ID: '{test_key}' (count={count}).")
    
    await redis_client.delete(test_key)
    print("✅ TEST 3 PASSED: UserRateLimiter enforces strict 401 authentication and user keys.")

async def test_session_cache_and_invalidation():
    print("\n--- TEST 4: Async Redis Session Cache & Invalidation ---")
    from rate_limiter import cache_user_session, invalidate_cached_session
    
    test_token = "voyage_tok_unittest_abc123"
    test_user_id = "usr_cached_456"
    
    # 1. Pre-warm session cache in Redis
    await cache_user_session(test_token, test_user_id, ttl=300)
    cached_val = await redis_client.get(f"session_cache:{test_token}")
    assert cached_val == test_user_id, f"Expected {test_user_id}, got {cached_val}"
    print(f"Pre-warmed session cache: session_cache:{test_token} -> {cached_val}")
    
    # 2. Test UserRateLimiter._resolve_user_id sub-millisecond cache hit
    limiter = UserRateLimiter(requests=10, window_seconds=60, key_prefix="test:rl:cache")
    mock_req = MagicMock(spec=Request)
    mock_req.state = SimpleNamespace(user=None)
    mock_req.cookies = {"voyageai_session": test_token}
    mock_req.headers = {}
    mock_req.query_params = {}
    
    resolved_id = await limiter._resolve_user_id(mock_req)
    assert resolved_id == test_user_id, f"Expected resolved ID {test_user_id}, got {resolved_id}"
    # The limiter must not overwrite request.state.user (get_current_user needs a full AuthUser there)
    assert mock_req.state.user is None
    assert mock_req.state.rate_limit_user_id == test_user_id
    print(f"UserRateLimiter successfully resolved user from Redis cache without DB query: {resolved_id}")
    
    # 3. Test Invalidation on Logout / Revocation
    await invalidate_cached_session(test_token)
    after_del = await redis_client.get(f"session_cache:{test_token}")
    assert after_del is None, f"Expected None after invalidation, got {after_del}"
    print(f"Session cache invalidated successfully: session_cache:{test_token} is None.")
    print("✅ TEST 4 PASSED: Redis cache-aside session resolution and invalidation working perfectly.")

async def main():
    try:
        await test_ipv6_normalization()
        test_forwarded_for_spoofing()
        await test_no_double_counting_and_lockout()
        await test_user_limiter_auth_enforcement()
        await test_session_cache_and_invalidation()
        print("\n=======================================================")
        print("🎉 ALL PRODUCTION RATE LIMITER TESTS PASSED SUCCESSFULLY!")
        print("=======================================================\n")
    finally:
        await redis_client.aclose()

if __name__ == "__main__":
    asyncio.run(main())

