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
  Since Stage 4 (1b), a named lookup is 1 Text Search call and Place Details is only used for a picked suggestion.

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

- Done: the old map library and Google's internal tile server URL are no longer used (that URL is not an API and broke Google's terms). Use the **Maps JavaScript API** (`<gmp-map>`, `VITE_GOOGLE_MAPS_BROWSER_KEY`, `DEMO_MAP_ID` while testing).
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
- Itinerary: "22 min by car from your location" on each activity card, from the device's current location (fix-origin-current; earlier this was between activities). Lazy, one at a time, at most 8 Google calls a day; reopening with the same origin (moved under 300 m) makes 0 calls in the same app session.
- Voice: the `get_travel_time` tool answers in one sentence, for example "Hawa Mahal yahan se 6.8 km hai, car se 23 minute."
  - Origin: the app's location, else the open trip's destination. Stays have no coordinates.
- Quota: 503 "Route abhi available nahi hai", and Routes is skipped until Google's reset.
- **Route caching is off** (`ROUTES_CACHE_TTL_S=0`, Stage 4). Service Specific Terms 19.3 allow caching only latitude/longitude from the Routes API, not distance, duration or polyline. The browser doesn't keep route results either. The setting remains for a billed key with Google's written OK.

## Stage 4: clean-up and safety (done on `map-stage4`, one commit per item)

1. **Key names:** `GOOGLE_MAPS_SERVER_KEY` (backend) and `VITE_GOOGLE_MAPS_BROWSER_KEY` (frontend).
   - The old names (`GOOGLE_MAPS_API_KEY`, `GOOGLE_MAP_DEMO_KEY`, `VITE_GOOGLE_MAP_DEMO_KEY`) are still read for one release, with a one-line warning naming the variable.
   - The Docker build arg, `docker-compose.yml`, the `.env.example` files, README and the `netlify.toml` notes are updated.
2. **Route caching off:** `ROUTES_CACHE_TTL_S=0` by default, and the browser no longer keeps route results either. Terms 19.3 allow caching only lat/lng from the Routes API.
3. **Removed:**
   - `/api/places/autocomplete` (nothing called it);
   - comments naming other providers;
   - dead imports in the map files.

   A repo-wide grep for other map providers finds only line 3 of this file.
4. **Attribution:** "Google Maps" is shown wherever Google Maps content appears outside a Google map:
   - map search suggestions (pinned to the box), trip destination search, manual location search;
   - the place details page, Food, Saved places, Home "Near you", emergency places;
   - map cards when the map itself is unavailable;
   - voice route notes.

   At phone size nothing covers Google's logo or copyright on the map.
5. **Key safety:** `python -m scripts.check_keys` (no network, never prints a key), plus the checklist below.
6. **Stage 1b, fewer Place Details calls:**
   - A named lookup is ONE Places Text Search (New) call.
   - Typing uses autocomplete only (3+ characters).
   - Place Details is called only for the suggestion the user picks.
   - Eval, 20 queries, uncached: 19/20 at about 6 calls per search before, **20/20 at 1 call** after. Text Search knows "4 minar" means Charminar.
   - 5 queries now ask a short choice where Google's #1 was right ("Sri Harmandir Sahib" for "Golden Temple"). A possible follow-up is to trust Text Search's #1 landmark.

**Caches holding Google data (reported, not changed).** Only place IDs (indefinitely) and lat/lng (up to 30 days) are allowed by Places 14.3, Geocoding 6.3 and Routes 19.3. Everything marked "outside" needs a decision before real users:

| Cache | Where | TTL | Holds | Terms |
|---|---|---|---|---|
| `places:textsearch:v1:*` | Redis + memory | 1 h | name, address, lat/lng, types | outside (name/address) |
| `places:autocomplete:v2:*` | Redis + memory | 1 h | place ID, name, address text, types | outside (name/address) |
| `places:detail:v2:basic/full:*` | Redis + memory | 24 h | name, address, lat/lng; full: hours, phone, website, summary | outside |
| `places:nearby:*` | Redis + memory | 2 h | name, address, lat/lng, rating, type, summary | outside |
| `geo:reverse:*` | Redis + memory | 24 h (1 h fallback) | formatted address, city, state | outside: 6.3.2 allows this only per user, not as a shared cache that replaces calls |
| `routes:v1:*` | Redis + memory | 0 (off) | distance, duration, polyline | OK while 0 |
| `saved_places:{user}` (saved-places list) | Redis | 10 min | the user's saved places (Google name, address, rating) | outside (copy of the DB rows below) |
| `cache:spotlight:*` (highlights) | Redis | 48 h | AI-written highlights | not Google |
| Browser memo `places:suggest/resolve/search`, Food `places:nearby` | memory | 10 min / 5 min | as above | outside (short) |
| DB `saved_places` | Postgres | permanent | name, address, coordinates, rating | outside (beyond place ID) |
| DB `trips.destination_json`, `cities` | Postgres | permanent | place name, lat/lng (and place ID) | lat/lng beyond 30 days is outside |

## Before real users (checklist)

- [ ] Two keys, never the same one: `VITE_GOOGLE_MAPS_BROWSER_KEY` (frontend) and `GOOGLE_MAPS_SERVER_KEY` (backend). `python -m scripts.check_keys --strict` passes.
- [ ] **Browser key:** restricted by HTTP referrer (localhost for dev, the Netlify domain) and to the **Maps JavaScript API** only.
- [ ] **Server key:** restricted to the server's IP address and to **Places API (New)**, **Geocoding API** and **Routes API** only.
- [ ] A daily cap per API in Google Cloud Console (Quotas), and a budget alert.
- [ ] Add billing only after the caps and the alert are in place.
- [ ] `ROUTES_CACHE_TTL_S=0`, and the Places/Geocoding caches reviewed against the Service Specific Terms (see Stage 4).
- [ ] The call counts in the logs (`google_calls=`, `[ROUTES]`) checked against the budget.

Weather stays on Open-Meteo (`weather_service.py`). It is not a map provider, and moving it to Google's Weather API is outside these four stages.
