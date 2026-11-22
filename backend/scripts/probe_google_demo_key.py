"""
Probe the Google Maps key once per API and report which calls the key accepts.

    python -m scripts.probe_google_demo_key

Uses GOOGLE_MAPS_API_KEY or GOOGLE_MAP_DEMO_KEY from backend/.env. Makes 7 Google requests in total
(one per endpoint below). Prints endpoint, HTTP status and Google's error status/message only:
never the key, and the key is also scrubbed from anything Google echoes back.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
KEY = os.getenv("GOOGLE_MAPS_API_KEY") or os.getenv("GOOGLE_MAP_DEMO_KEY") or ""

# Charminar, Hyderabad
LAT, LNG = 17.3616, 78.4747


def _scrub(text: str) -> str:
    return text.replace(KEY, "<key>") if KEY else text


def _google_error(res: requests.Response) -> str:
    try:
        body = res.json()
    except ValueError:
        return "(not JSON)"
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):  # Places (New), Geocoding v4
            return _scrub(f"{err.get('status')}: {str(err.get('message'))[:200]}")
        if isinstance(err, str):
            return _scrub(err[:200])
        if "status" in body and body.get("status") != "OK":  # Geocoding v3
            return _scrub(f"{body.get('status')}: {str(body.get('error_message') or '')[:200]}")
    return ""


def _report(name: str, url: str, res: requests.Response, extra: str = "") -> bool:
    ok = res.status_code == 200 and not _google_error(res)
    print(f"{'OK  ' if ok else 'FAIL'} {name}")
    print(f"     endpoint: {url}")
    print(f"     HTTP {res.status_code}  {_google_error(res) or ''}")
    if extra:
        print(f"     {extra}")
    return ok


def main() -> int:
    if not KEY:
        print("No GOOGLE_MAPS_API_KEY / GOOGLE_MAP_DEMO_KEY in backend/.env")
        return 1
    base_headers = {"Content-Type": "application/json", "X-Goog-Api-Key": KEY}
    results = {}
    place_id = None

    url = "https://places.googleapis.com/v1/places:autocomplete"
    res = requests.post(url, headers=base_headers, json={"input": "Charminar", "includedRegionCodes": ["in"]}, timeout=8)
    extra = ""
    if res.status_code == 200:
        sugg = [s.get("placePrediction") or {} for s in res.json().get("suggestions", [])]
        if sugg:
            place_id = sugg[0].get("placeId")
            extra = f"{len(sugg)} suggestions; first has types={sugg[0].get('types')}"
    results["Places Autocomplete (New)"] = _report("Places Autocomplete (New)", url, res, extra)

    url = f"https://places.googleapis.com/v1/places/{place_id or 'ChIJ8YT_x2SZyzsRDnZgeTW7z5A'}"
    mask = "id,displayName,formattedAddress,location,addressComponents,types,primaryType"
    res = requests.get(url.replace(place_id or "", place_id or ""), headers={**base_headers, "X-Goog-FieldMask": mask}, timeout=8)
    extra = ""
    if res.status_code == 200:
        d = res.json()
        extra = f"field mask with types,primaryType accepted: primaryType={d.get('primaryType')} types={d.get('types')}"
    results["Place Details (New)"] = _report("Place Details (New)", "https://places.googleapis.com/v1/places/{place_id}", res, extra)

    # Same, with rating/hours, to see whether the demo key returns them.
    mask2 = "id,rating,userRatingCount,regularOpeningHours.openNow,editorialSummary"
    res = requests.get(url, headers={**base_headers, "X-Goog-FieldMask": mask2}, timeout=8)
    extra = ""
    if res.status_code == 200:
        d = res.json()
        extra = "returned fields: " + ", ".join(sorted(k for k in d.keys()))
    results["Place Details (New), rating/hours"] = _report("Place Details (New), rating/hours fields",
                                                           "https://places.googleapis.com/v1/places/{place_id}", res, extra)

    url = "https://places.googleapis.com/v1/places:searchText"
    res = requests.post(url, headers={**base_headers, "X-Goog-FieldMask": "places.id,places.displayName,places.primaryType"},
                        json={"textQuery": "Charminar", "regionCode": "in", "pageSize": 3}, timeout=8)
    extra = ""
    if res.status_code == 200:
        extra = f"{len(res.json().get('places', []))} places"
    results["Text Search (New)"] = _report("Text Search (New)", url, res, extra)

    url = "https://maps.googleapis.com/maps/api/geocode/json"
    res = requests.get(url, params={"latlng": f"{LAT},{LNG}", "key": KEY}, timeout=8)
    extra = ""
    if res.status_code == 200 and res.json().get("results"):
        extra = f"{len(res.json()['results'])} results"
    results["Geocoding v3 (reverse)"] = _report("Geocoding v3 (reverse, current URL)", url + "?latlng=..&key=..", res, extra)

    for version in ("v4", "v4beta"):
        url = f"https://geocode.googleapis.com/{version}/geocode/location/{LAT},{LNG}"
        res = requests.get(url, headers={"X-Goog-Api-Key": KEY,
                                         "X-Goog-FieldMask": "results.formattedAddress,results.addressComponents"}, timeout=8)
        extra = ""
        if res.status_code == 200:
            extra = f"{len(res.json().get('results', []))} results"
        results[f"Geocoding {version} (reverse)"] = _report(f"Geocoding {version} (reverse)", url.replace(f"{LAT},{LNG}", "{lat},{lng}"), res, extra)

    print()
    print("Summary: " + ", ".join(f"{k}: {'works' if v else 'rejected'}" for k, v in results.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
