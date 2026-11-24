import json
import logging
from redis_client import redis_conn

logger = logging.getLogger(__name__)

TASK_QUEUE_KEY = "voyageai:tasks:itinerary"
TRIP_EVENTS_CHANNEL = "voyageai:events:trip"

def enqueue_itinerary_generation(trip_id: str) -> bool:
    """Pushes an itinerary generation job onto the Redis queue."""
    try:
        payload = json.dumps({"action": "GENERATE_ITINERARY", "trip_id": trip_id})
        redis_conn.lpush(TASK_QUEUE_KEY, payload)
        logger.info(f"[TASK ENQUEUED] Trip ID: {trip_id}")
        print(f">>> [TASK QUEUE] Enqueued itinerary generation for {trip_id}", flush=True)
        return True
    except Exception as e:
        logger.error(f"[TASK QUEUE ERROR] Failed to enqueue task: {e}")
        print(f"[TASK QUEUE ERROR] Failed to enqueue task: {e}", flush=True)
        return False

def publish_trip_event(trip_id: str, status: str, event_type: str = "ITINERARY_READY"):
    """Publishes a completion event to Redis Pub/Sub.
    ITINERARY_READY is also sent with status "FAILED"; the name is kept for compatibility (clients read `status`)."""
    try:
        payload = json.dumps({
            "event": event_type,
            "trip_id": trip_id,
            "status": status
        })
        redis_conn.publish(TRIP_EVENTS_CHANNEL, payload)
        logger.info(f"[EVENT PUBLISHED] {event_type} for {trip_id}")
        print(f">>> [PUB/SUB EVENT] Published {event_type} for {trip_id}", flush=True)
    except Exception as e:
        logger.warning(f"[EVENT PUBLISH WARN] Failed to publish event: {e}")
        print(f"[EVENT PUBLISH WARN] Failed to publish event: {e}", flush=True)

def enqueue_poi_fetch(lat: float, lng: float, radius_m: int = 5000, category: str = "all") -> bool:
    """Pushes a POI discovery job onto the Redis queue for worker execution."""
    try:
        payload = json.dumps({
            "action": "FETCH_POIS",
            "lat": lat,
            "lng": lng,
            "radius_m": radius_m,
            "category": category
        })
        redis_conn.lpush(TASK_QUEUE_KEY, payload)
        logger.info(f"[TASK ENQUEUED] POI Fetch ({lat}, {lng}) category={category}")
        print(f">>> [TASK QUEUE] Enqueued POI fetch for ({lat}, {lng}) cat={category}", flush=True)
        return True
    except Exception as e:
        logger.error(f"[TASK QUEUE ERROR] Failed to enqueue POI task: {e}")
        print(f"[TASK QUEUE ERROR] Failed to enqueue POI task: {e}", flush=True)
        return False
