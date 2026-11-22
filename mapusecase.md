# Google Maps Demo Key: plan for VoyageAI (mapusecase.md)

Updated 22 Nov 2026. Google only: no CARTO, OpenStreetMap, Nominatim, Overpass or other map provider, and no fallback to one.
When Google is unavailable, the app says so plainly ("Map search isn't available right now") and calls nothing else.

> **Rules for the coding agent:** one local branch per stage (`map-stageN`). Don't push, open a PR or merge until the owner says.
> Commit locally, stop after each stage, and report. Never commit or print a key.

## The key (facts that shape the plan)

- **Demo key** (`GOOGLE_MAP_DEMO_KEY` / `GOOGLE_MAPS_API_KEY` in `backend/.env`): free, prototype use only, personal Google account.
- **Supported:** Places API (New), Geocoding API **v4**, Compute Routes, Weather, Maps JavaScript API.
  **Not available:** user photos and reviews.
- **Probe, 22 Nov 2026** (`python -m scripts.probe_google_demo_key`):
  - Works: Places Autocomplete (New), Place Details (New) (`types`, `rating`, `regularOpeningHours` and `editorialSummary` do come back), Text Search (New), Geocoding v4 (and v4beta).
  - Refused: Geocoding v3 (`REQUEST_DENIED`, billing required).
- **Daily limits pause the API until midnight Pacific (13:30 IST).** Measured: **Place Details = 100 requests a day** (`GetPlaceRequest per day`).
  Today a search costs 1 autocomplete call plus up to 6 detail calls, so the key covers only about 15–20 new searches a day (cached searches are free).

## Stage 1: search (done on `map-stage1`)

- One search function, `places.search_places_detailed` (Google Autocomplete (New) + Place Details (New), unchanged flow). Voice look-ups, the map search box and trip destination search all use it.
- Landmark-first ranking. It uses autocomplete's `types`, so no extra call or field is needed.
  - Landmarks and real places (city, area, road, the address itself) rank first, and Google's order decides between them.
  - Stations, hotels and unknown establishments come after them; shops and services come last.
  - Results outside India are dropped.
- If the best result is a shop or unknown, or several landmarks fit and none clearly matches, it's ambiguous: voice asks a short choice of up to 3 ("A, B ya C?"). It never picks a shop by default and never invents a result.
- The voice agent sends the place's usual written name ("4 minar" becomes "Charminar"). Google's own results for "4 minar" don't include Charminar.
- Quota or paused key:
  - voice says "Map search abhi available nahi hai";
  - the app shows "Map search isn't available right now";
  - the API is skipped until Google's reset (60 s for a per-minute limit);
  - no retry, no other provider.
- Reverse geocoding moved from v3 to **v4** (`geocode.googleapis.com/v4/geocode/location/{lat},{lng}`, key in the header).
- Logs: the Google call count per search and per voice turn (`google_calls=N`). Never the query text or the key.

## Stage 2: Google map

- Replace the Leaflet map drawn from `mt1.google.com/vt` tiles. That is Google's internal tile server, not an API, and using it breaks Google's terms. Use the **Maps JavaScript API** (`<gmp-map>`, `VITE_GOOGLE_MAPS_BROWSER_KEY`, `DEMO_MAP_ID` while testing).
- Keep what the map does today: user location, category markers, search pin, the place card and its Details page, light/dark theme.
- If the Maps JavaScript key is paused or fails, show a plain "Map isn't available right now" panel. Lists and search results still work without the map.
- **Cut Place Details use before this stage goes to users** (the 100/day limit). For example, resolve coordinates only for the result the user picks. Or use one Text Search (New) call that returns `location` for every result. This changes the call count, so the owner decides.
- Restrict the browser key to HTTP referrers (localhost, the app's domain) and to the Maps JavaScript API.

## Stage 3: Routes (done on `map-stage3`)

- **Probe, 22 Nov 2026** (`python -m scripts.probe_routes`):
  - Compute Routes works for DRIVE, TWO_WHEELER and WALK.
  - Compute Route Matrix is refused (403 PERMISSION_DENIED), so the itinerary uses one call per leg.
  - Flyover info (`FLYOVER_INFO_ON_POLYLINE`) is accepted, but returned 0 flyovers for a Jaipur route. Not built.
- `POST /api/routes/compute` (login, 20 a minute per user) calls `computeRoutes` with these settings:
  - field mask `routes.duration,routes.distanceMeters,routes.polyline.encodedPolyline,routes.warnings`;
  - `TRAFFIC_UNAWARE` (WALK must send no routing preference);
  - `languageCode en-IN`. Without it, Google sent the warnings in Assamese.
- Warnings: Google gives no fixed wording. The app shows `routes.warnings` from the response, exactly as sent, for walk and bike.
- Map: the "Route" button sits on the selected-place sheet and calls only on a tap or a mode-chip change (Car, Bike, Walk).
  - The line is drawn with the Maps geometry library and the camera fits it.
  - On error, the sheet shows the straight-line distance, labelled "straight-line", and no line.
- Itinerary: "22 min by car" between activities, computed lazily, one leg at a time, at most 8 legs a day. That's about 3.75 calls per day the first time, 0 when cached.
- Voice: the `get_travel_time` tool answers in one sentence, for example "Hawa Mahal yahan se 6.8 km hai, car se 23 minute."
  - Origin: the app's location, else the open trip's destination. Stays have no coordinates.
- Quota: 503 "Route abhi available nahi hai", and Routes is skipped until Google's reset.
- **Caching conflict:** Service Specific Terms 19.3 allow caching only latitude/longitude from the Routes API, not distance, duration or polyline. The 30-minute cache is on (`ROUTES_CACHE_TTL_S=1800`). Set it to 0 before real users, unless Google confirms otherwise.

## Stage 4: clean-up

- Remove Leaflet, the `mt1.google.com` tile URL and `VITE_GOOGLE_MAP_DEMO_KEY` from the frontend once stage 2 is in.
- One key name per side, `GOOGLE_MAPS_SERVER_KEY` and `VITE_GOOGLE_MAPS_BROWSER_KEY`. Keep reading the old names for one release, and update the `.env.example` files.
- Remove `/api/places/autocomplete` if nothing calls it (nothing in the frontend does today). Remove code comments that still mention Overpass or Nominatim.
- Show "Google Maps" attribution wherever Places data appears outside a Google map.
- Before real users: a billed key with per-API daily caps, a restricted server key, and the call counts from the logs checked against the budget.

Weather stays on Open-Meteo (`weather_service.py`). It is not a map provider, and moving it to Google's Weather API is outside these four stages.
