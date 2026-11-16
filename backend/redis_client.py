import os
import redis
from redis.backoff import NoBackoff
from redis.retry import Retry

# Read from .env if available, otherwise default to local port 6379
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

# decode_responses=True automatically converts bytes to Python strings
redis_conn = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    db=0,
    decode_responses=True,
    socket_connect_timeout=2,
    socket_timeout=5,
    retry=Retry(NoBackoff(), 0),
    protocol=2
)


def get_redis():
    """Dependency / accessor for Redis"""
    return redis_conn
