import os
import sys
import json
import time
import signal
import logging

# Ensure backend root is in module search path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import models_db
import models_trip
from redis_client import redis_conn
from database import SessionLocal
from itinerary_service import process_async_itinerary_generation
from task_queue import TASK_QUEUE_KEY, publish_trip_event

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("voyageai.worker")

running = True

def handle_shutdown(signum, frame):
    global running
    logger.info("Gracefully shutting down worker process...")
    running = False

try:
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)
except Exception:
    pass

def start_worker():
    logger.info(f"VoyageAI Background Task Worker listening on queue: {TASK_QUEUE_KEY}")
    print(f"[WORKER READY] Listening for jobs on '{TASK_QUEUE_KEY}' (Press Ctrl+C to stop)...", flush=True)

    while running:
        try:
            # Let Redis return from an idle poll before the client read times out.
            item = redis_conn.brpop(TASK_QUEUE_KEY, timeout=2)
            if not item:
                continue

            # item is a tuple: (queue_name, popped_value_string)
            _, raw_payload = item
            try:
                job = json.loads(raw_payload) if isinstance(raw_payload, str) else raw_payload
            except Exception as e:
                logger.warning(f"Malformed JSON payload: {raw_payload} | Error: {e}")
                continue

            if not isinstance(job, dict):
                logger.warning(f"Malformed job payload (not a dict): {raw_payload}")
                continue

            action = job.get("action")

            # 1. Background POI Discovery Task
            if action == "FETCH_POIS":
                lat = job.get("lat")
                lng = job.get("lng")
                radius_m = job.get("radius_m", 5000)
                category = job.get("category", "all")

                if lat is not None and lng is not None:
                    logger.info(f"Picked up POI fetch job for ({lat}, {lng}) category={category}")
                    print(f"\n[WORKER RUNNING] Fetching background POIs for ({lat}, {lng}) [{category}]", flush=True)
                    from tour_guide_service import fetch_and_cache_pois_task
                    fetch_and_cache_pois_task(float(lat), float(lng), int(radius_m), str(category))
                    print(f"[WORKER COMPLETED] POI fetch for ({lat}, {lng}) completed.\n", flush=True)
                else:
                    logger.warning(f"Malformed FETCH_POIS job (missing coords): {job}")

            # 2. Trip Itinerary Generation Tasks
            elif (action in ["GENERATE_ITINERARY", None]) and job.get("trip_id"):
                trip_id = job.get("trip_id")
                logger.info(f"Picked up job for trip_id: {trip_id}")
                print(f"\n[WORKER RUNNING] Processing AI Itinerary for trip: {trip_id}", flush=True)
                final_status = process_async_itinerary_generation(trip_id, SessionLocal)
                if final_status:
                    publish_trip_event(trip_id=trip_id, status=final_status, event_type="ITINERARY_READY")
                print(f"[WORKER COMPLETED] Trip {trip_id} generated and published.\n", flush=True)

            else:
                logger.warning(f"Malformed job payload received: {raw_payload}")

        except Exception as e:
            logger.error(f"[WORKER ERROR] Job failed: {e}")
            time.sleep(1)

if __name__ == "__main__":
    start_worker()
