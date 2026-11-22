"""
Probe the Google Routes API with the real key (map stage 3). Never prints the key.

    python -m scripts.probe_routes

Calls (7 Google requests in total):
- computeRoutes once each for DRIVE, TWO_WHEELER and WALK (Hawa Mahal -> Amer Fort, Jaipur),
  field mask routes.duration,routes.distanceMeters,routes.polyline.encodedPolyline (+ routes.warnings);
- computeRouteMatrix once (2 origins x 2 destinations, DRIVE);
- computeRoutes DRIVE with extraComputations FLYOVER_INFO_ON_POLYLINE (TRAFFIC_UNAWARE, then TRAFFIC_AWARE if refused).
Prints the endpoint, HTTP status and Google's error status/message for each.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
KEY = os.getenv("GOOGLE_MAPS_API_KEY") or os.getenv("GOOGLE_MAP_DEMO_KEY") or ""

ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
MATRIX_URL = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
FIELD_MASK = "routes.duration,routes.distanceMeters,routes.polyline.encodedPolyline"
HAWA_MAHAL = (26.9239, 75.8267)
AMER_FORT = (26.9855, 75.8513)
JAIPUR_JN = (26.9196, 75.7878)
ALBERT_HALL = (26.9116, 75.8195)


def wp(lat, lng):
    return {"location": {"latLng": {"latitude": lat, "longitude": lng}}}


def _scrub(text):
    return text.replace(KEY, "<key>") if KEY else text


def _error(res):
    try:
        body = res.json()
    except ValueError:
        return "(not JSON)"
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(body, list) and body and isinstance(body[0], dict):
        err = body[0].get("error")
    if isinstance(err, dict):
        return _scrub(f"{err.get('status')}: {str(err.get('message'))[:220]}")
    return ""


def post(url, mask, body):
    t = time.perf_counter()
    res = requests.post(url, json=body, timeout=10, headers={
        "Content-Type": "application/json", "X-Goog-Api-Key": KEY, "X-Goog-FieldMask": mask})
    return res, int((time.perf_counter() - t) * 1000)


def main() -> int:
    if not KEY:
        print("No Google key in backend/.env")
        return 1
    summary = {}
    for mode in ("DRIVE", "TWO_WHEELER", "WALK"):
        body = {"origin": wp(*HAWA_MAHAL), "destination": wp(*AMER_FORT), "travelMode": mode}
        if mode != "WALK":
            body["routingPreference"] = "TRAFFIC_UNAWARE"
        res, ms = post(ROUTES_URL, FIELD_MASK + ",routes.warnings", body)
        ok = res.status_code == 200 and bool((res.json() or {}).get("routes"))
        extra = ""
        if ok:
            r = res.json()["routes"][0]
            extra = (f"distance {r.get('distanceMeters')} m, duration {r.get('duration')}, polyline "
                     f"{len((r.get('polyline') or {}).get('encodedPolyline') or '')} chars, warnings {r.get('warnings')}")
        summary[f"computeRoutes {mode}"] = ok
        print(f"{'OK  ' if ok else 'FAIL'} computeRoutes {mode}  HTTP {res.status_code} {_error(res)}  {ms} ms")
        print(f"     {extra or res.text[:200] if not ok else extra}")

    body = {"origins": [{"waypoint": wp(*HAWA_MAHAL)}, {"waypoint": wp(*JAIPUR_JN)}],
            "destinations": [{"waypoint": wp(*AMER_FORT)}, {"waypoint": wp(*ALBERT_HALL)}],
            "travelMode": "DRIVE", "routingPreference": "TRAFFIC_UNAWARE"}
    res, ms = post(MATRIX_URL, "originIndex,destinationIndex,duration,distanceMeters,status,condition", body)
    ok = res.status_code == 200 and isinstance(res.json(), list) and len(res.json()) == 4
    summary["computeRouteMatrix"] = ok
    print(f"{'OK  ' if ok else 'FAIL'} computeRouteMatrix (2x2 DRIVE)  HTTP {res.status_code} {_error(res)}  {ms} ms")
    if ok:
        for e in res.json():
            print(f"     {e.get('originIndex')}->{e.get('destinationIndex')}: {e.get('distanceMeters')} m, {e.get('duration')}, {e.get('condition')}")

    for pref in ("TRAFFIC_UNAWARE", "TRAFFIC_AWARE"):
        body = {"origin": wp(*JAIPUR_JN), "destination": wp(*AMER_FORT), "travelMode": "DRIVE",
                "routingPreference": pref, "extraComputations": ["FLYOVER_INFO_ON_POLYLINE"]}
        res, ms = post(ROUTES_URL, FIELD_MASK + ",routes.polylineDetails.flyoverInfo", body)
        ok = res.status_code == 200 and bool((res.json() or {}).get("routes"))
        info = ""
        if ok:
            fly = ((res.json()["routes"][0].get("polylineDetails") or {}).get("flyoverInfo")) or []
            info = f"flyoverInfo entries: {len(fly)}"
        summary[f"flyover info ({pref})"] = ok
        print(f"{'OK  ' if ok else 'FAIL'} computeRoutes DRIVE + FLYOVER_INFO_ON_POLYLINE ({pref})  HTTP {res.status_code} {_error(res)}  {ms} ms  {info}")
        if ok:
            break

    print("\nSummary: " + ", ".join(f"{k}: {'works' if v else 'rejected'}" for k, v in summary.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
