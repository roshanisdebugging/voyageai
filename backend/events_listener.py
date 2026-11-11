import os
import json
import asyncio
import logging
import redis.asyncio as aioredis
from task_queue import TRIP_EVENTS_CHANNEL

logger = logging.getLogger(__name__)

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = os.getenv("REDIS_PORT", "6379")
REDIS_URL = os.getenv("REDIS_URL", f"redis://{REDIS_HOST}:{REDIS_PORT}/0")

RECONNECT_DELAY_SECONDS = 5


async def _listen_once(broadcast_callback):
    r = aioredis.from_url(REDIS_URL, decode_responses=True, protocol=2)
    pubsub = r.pubsub()
    try:
        await pubsub.subscribe(TRIP_EVENTS_CHANNEL)
        print(f"[REDIS PUBSUB] Subscribed to channel '{TRIP_EVENTS_CHANNEL}'", flush=True)
        async for message in pubsub.listen():
            if not message or message.get("type") != "message":
                continue
            try:
                event_payload = json.loads(message.get("data"))
                trip_id = event_payload.get("trip_id")
                if not trip_id:
                    continue
                await broadcast_callback(trip_id, {
                    "type": event_payload.get("event", "ITINERARY_READY"),
                    "tripId": trip_id,
                    "status": event_payload.get("status"),
                })
            except Exception as parse_err:
                logger.error(f"[PUBSUB ERROR] Failed to process incoming event: {parse_err}")
    finally:
        try:
            await pubsub.unsubscribe(TRIP_EVENTS_CHANNEL)
            await r.aclose()
        except Exception:
            pass


async def start_redis_events_listener(broadcast_callback):
    """
    Subscribes to Redis Pub/Sub events published by worker.py and forwards them
    to broadcast_callback. Reconnects if Redis is down or the connection drops.
    """
    while True:
        try:
            await _listen_once(broadcast_callback)
        except asyncio.CancelledError:
            print("[REDIS PUBSUB] Listener stopped.", flush=True)
            raise
        except Exception as err:
            print(f"[REDIS PUBSUB] Connection lost ({err}). Retrying in {RECONNECT_DELAY_SECONDS}s...", flush=True)
        await asyncio.sleep(RECONNECT_DELAY_SECONDS)
