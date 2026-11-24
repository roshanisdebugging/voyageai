"""
Browser check: /map with a Goa trip open. A place in Bihar gets no "Add to Itinerary" (Save only + a muted hint), a
Panaji place does. Takes the screenshots too.

Needs: the dev server (npm run dev, http://localhost:5173), Chrome, and `pip install playwright`. Not part of npm test.
The app's own API and WebSockets are faked (no account, no Places calls, nothing saved); the map is the real Google map.
    python tests/trip_area_check.py [--out DIR] [--base URL] [--label after]
"""
import argparse
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright

ap = argparse.ArgumentParser()
ap.add_argument("--out", default="", help="folder for screenshots")
ap.add_argument("--base", default="http://localhost:5173")
ap.add_argument("--label", default="after")
args = ap.parse_args()
OUT = Path(args.out) if args.out else None
if OUT:
    OUT.mkdir(parents=True, exist_ok=True)

GOA = {"name": "Goa", "region": "Goa", "country": "India", "latitude": 15.2993, "longitude": 74.1240}
SPOTS = {
    "bihar": (26.3537, 86.0718, "Madhubani, Bihar", [("Test Bihar Temple", "ChIJareacheckbihar01"), ("Test Bihar Museum", "ChIJareacheckbihar02")]),
    "panaji": (15.4989, 73.8278, "Panaji, Goa", [("Test Panaji Church", "ChIJareacheckgoa0001"), ("Test Panaji Museum", "ChIJareacheckgoa0002")]),
}
SESSION = {
    "authenticated": True,
    "authUser": {"id": "usr_area_check", "email": "area-check@example.com", "status": "ACTIVE", "emailVerified": True},
    "userProfile": {"userId": "usr_area_check", "fullName": "Area Check", "onboardingStatus": "COMPLETED", "onboardingStep": "COMPLETED"},
    "userPreferences": {"userId": "usr_area_check"},
}
today = date.today()
NOW = f"{today.isoformat()}T00:00:00+00:00"


def trip():
    return {"id": "trip_goa_check", "userId": "usr_area_check", "title": "Goa", "status": "UPCOMING", "itineraryStatus": "READY",
            "startDate": (today + timedelta(days=2)).isoformat(), "endDate": (today + timedelta(days=4)).isoformat(), "totalDays": 3,
            "destination": GOA, "origin": None, "coverMedia": {"url": "", "alt": "", "provider": "none"}, "travelers": [],
            "adultsCount": 1, "childrenCount": 0, "preferencesSnapshot": {}, "budget": {}, "progress": {},
            "tripStyle": [], "transportPreferences": [], "currency": "INR", "createdAt": NOW, "updatedAt": NOW}


# One place already in the itinerary although it is far from Goa: it must keep showing "Added to Day 2".
def itinerary(added):
    acts = [{"id": added[1], "timeSlot": "Morning", "title": added[0], "activityType": "SIGHTSEEING"}] if added else []
    return {"id": "itin_1", "tripId": "trip_goa_check", "version": 1, "status": "READY",
            "days": [{"id": f"day_{n}", "dayNumber": n, "date": f"Day {n}", "title": f"Day {n}", "activities": acts if n == 2 else []}
                     for n in (1, 2, 3)]}


results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail != "" and not ok else ""), flush=True)


def open_map(browser, spot, *, with_trip=True, added=None, reject=False):
    lat, lng, label, names = SPOTS[spot]
    places = [{"id": pid, "name": n, "category": "tourist_attraction", "latitude": lat + 0.002 * i, "longitude": lng + 0.002 * i,
               "distance_meters": 200 + 150 * i, "address": label, "rating": 4.4} for i, (n, pid) in enumerate(names)]
    trips = [trip()] if with_trip else []

    def api(route):
        req = route.request
        cors = {"Access-Control-Allow-Origin": args.base, "Access-Control-Allow-Credentials": "true",
                "Access-Control-Allow-Headers": req.headers.get("access-control-request-headers", "*"),
                "Access-Control-Allow-Methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS"}
        if req.method == "OPTIONS":
            return route.fulfill(status=204, headers=cors)
        path = re.sub(r"^https?://[^/]+", "", req.url).split("?")[0]
        body, status = {"detail": "not in this check"}, 404
        if path == "/api/auth/me":
            body, status = SESSION, 200
        elif path == "/api/places/nearby":
            body, status = places, 200
        elif path == "/api/location/reverse":
            body, status = {"display_name": label, "city": label.split(",")[0], "state": label.split(", ")[1]}, 200
        elif path == "/api/trips":
            body, status = trips, 200
        elif path == "/api/saved-places":
            body, status = [], 200
        elif path == "/api/trips/itinerary/add" and reject:
            body, status = {"detail": "Yeh jagah aapke Goa trip ke area ke bahar hai.", "error_code": "place_outside_trip_area"}, 422
        route.fulfill(status=status, headers={**cors, "Content-Type": "application/json"}, body=json.dumps(body))

    def fake_ws(ws):
        def on_message(msg):
            try:
                frame = json.loads(msg)
            except Exception:
                return
            rid, action = frame.get("id") or frame.get("requestId"), frame.get("action")
            data = {"trips:list": trips, "places:saved": [], "trips:get_itinerary": itinerary(added)}.get(action)
            if rid:
                ws.send(json.dumps({"id": rid, "requestId": rid, "action": action, "status": "success" if data is not None else "error",
                                    "data": data, "error": None if data is not None else "not in this check"}))
        ws.on_message(on_message)

    ctx = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True,
                              geolocation={"latitude": lat, "longitude": lng, "accuracy": 20}, permissions=["geolocation"])
    page = ctx.new_page()
    page.route(re.compile(r"^https?://[^/]+/api/"), api)
    page.route_web_socket(re.compile(r"/ws/"), fake_ws)
    page.goto(f"{args.base}/map", wait_until="domcontentloaded")
    page.wait_for_selector(".map-places-overlay [role=button]", timeout=30000)
    page.wait_for_timeout(5000)
    return ctx, page, page.locator(".map-places-overlay [role=button]").filter(has_text=names[0][0]).first


def shot(page, name):
    if OUT:
        page.screenshot(path=str(OUT / f"{args.label}-{name}.png"))


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=False)

    ctx, page, card = open_map(browser, "bihar")
    shot(page, "goa-trip-bihar-place")
    t = card.inner_text()
    check("Goa trip, Bihar place: no Add to Itinerary", "Add to Itinerary" not in t, t)
    check("Goa trip, Bihar place: Save place shown", "Save place" in t, t)
    check("Goa trip, Bihar place: muted hint", "Outside your Goa trip area" in t, t)
    ctx.close()

    ctx, page, card = open_map(browser, "panaji")
    shot(page, "goa-trip-panaji-place")
    t = card.inner_text()
    check("Goa trip, Panaji place: Add to Itinerary shown", "Add to Itinerary" in t, t)
    check("Goa trip, Panaji place: no hint", "Outside your" not in t, t)
    ctx.close()

    ctx, page, card = open_map(browser, "bihar", added=SPOTS["bihar"][3][0])
    shot(page, "goa-trip-bihar-place-already-added")
    t = card.inner_text()
    check("already in the itinerary, outside the area: still Added to Day 2", "Added to Day 2" in t and "Add to Itinerary" not in t, t)
    ctx.close()

    ctx, page, card = open_map(browser, "bihar", with_trip=False)
    shot(page, "no-trip-bihar-place")
    t = card.inner_text()
    check("no trip open: Save place, no Add, no hint", "Save place" in t and "Add to Itinerary" not in t and "Outside your" not in t, t)
    ctx.close()

    # The server's refusal is shown (it would come from a stale card).
    ctx, page, card = open_map(browser, "panaji", reject=True)
    add = card.get_by_text("Add to Itinerary")
    if add.count():
        add.click()
        page.get_by_role("button", name=re.compile("Add to Day")).click()
        page.wait_for_timeout(1200)
        shot(page, "server-refused")
        check("server says place_outside_trip_area: message shown, not marked added",
              page.get_by_text("Yeh jagah aapke Goa trip ke area ke bahar hai.").count() == 1 and "Added to Day" not in card.inner_text())
    ctx.close()
    browser.close()

print(f"\n{sum(results)}/{len(results)} passed", flush=True)
sys.exit(0 if all(results) else 1)
