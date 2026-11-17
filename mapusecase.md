# Google Maps Demo Key — full use plan for VoyageAI (mapusecase.md)

Status: plan only, 14 Nov 2026. Nothing here is built yet.
For: the coding agent working on `roshanisdebugging/voyageai`.

> **Rules for the coding agent**
> - Work on a local branch per phase (`maps-phase-N`).
> - **Do not push, open a PR or merge** until the owner says where.
> - Commit locally, stop after each phase, and report.
> - Never commit any key. Never print keys in logs.
> - Moves and new features only as described. Keep existing behaviour working when the demo key is missing or paused.

---

## 1. What the Maps Demo Key is (the facts that shape this plan)

- **Free, no billing account.** It's for prototyping and testing, not production. It follows the Maps Demo Project Terms of Service.
- **Daily limit per API.** When it's reached, that API **pauses until the next day**, with no charge. Google doesn't publish the numbers, and they can change.
  → Every feature in this plan needs a fallback (section 3).
- **Personal Google account only** (not Google Workspace).
- **Supported:**
  - **Maps JavaScript API:** 2D/3D maps with satellite and terrain, markers and events, map styling, the Places UI Kit (ready-made search and details components), drawing tools, the Place class.
  - **Web services:**
    - Places API (New);
    - Geocoding API **v4**;
    - Compute Routes (Routes API);
    - Weather API;
    - **Maps Grounding Lite** (tools for AI agents).
- **Not supported:** user-generated content (**photos and reviews**). Whether **ratings and opening hours** come back is not stated, so test it (Phase 0).
- **Anything not in the list** needs a billed key.

## 2. What the code uses today (checked on `main`, 14 Nov 2026)

| Where | What it calls | Problem |
| --- | --- | --- |
| `backend/services/google_maps_service.py` line 19 | `GOOGLE_MAPS_API_KEY` or `GOOGLE_MAP_DEMO_KEY` | OK |
| same file, ~line 150 (`reverse geocode`) | **Geocoding v3** `maps.googleapis.com/maps/api/geocode/json` | Not on the demo list; falls back to `searchNearby` (an extra call) |
| same file, ~line 177 | Places (New) `searchNearby`, 1 result, for the city name | OK, but it's only needed because v3 fails |
| same file, ~line 243 | Places (New) `searchNearby`, field mask includes `rating,userRatingCount` | Ratings may be empty on the demo key |
| same file, ~line 350 | Places (New) `autocomplete` | OK |
| same file, ~line 420 | Places (New) `places/{id}`, field mask `id,displayName,formattedAddress,location,addressComponents` | Thin: the details page needs more |
| `frontend/src/components/map/MapView.tsx` ~line 49–53 | Leaflet with tiles from `mt1.google.com/vt/...&key=VITE_GOOGLE_MAP_DEMO_KEY` | **Not an official API.** It's Google's internal tile server. The key isn't used there, and using these tiles breaks Google's terms. Must be replaced |
| `backend/weather_service.py` | Open-Meteo (free, not Google) | Fine; it stays as the fallback |
| Map card "Details" button | `navigateToExplore()` → `/explore` | Bug: should open a details page (Phase 3) |

## 3. Foundations (Phase 0, do first)

### 3.1 Keys and settings

| Variable | Where | Use |
| --- | --- | --- |
| `GOOGLE_MAPS_SERVER_KEY` | `backend/.env` | Server calls: Places, Geocoding v4, Routes, Weather, Grounding Lite. Can be the demo key |
| `VITE_GOOGLE_MAPS_BROWSER_KEY` | `frontend/.env` | Maps JavaScript map + Places UI Kit in the browser. Can be the demo key |
| `GOOGLE_MAPS_KEY_MODE` | backend | `demo` or `billed`. In `demo` mode, fallbacks are on and costs aren't logged |
| `VITE_MAP_ENGINE` | frontend | `google` (new) or `leaflet` (fallback, free tiles) |
| `GOOGLE_MAP_ID` / `VITE_GOOGLE_MAP_ID` | both | `DEMO_MAP_ID` while testing; your own Map ID later (styling, 3D) |

- Keep reading the old names (`GOOGLE_MAPS_API_KEY`, `GOOGLE_MAP_DEMO_KEY`, `VITE_GOOGLE_MAP_DEMO_KEY`) as fallbacks, so nothing breaks.
- Update `.env.example` files with the new names and a one-line comment each.
- **Restrict keys in Google Cloud Console:**
  - browser key: HTTP referrers (localhost, your domain), Maps JavaScript API only;
  - server key: only the APIs in this plan.
- The browser key is visible to anyone, so restrict it.

### 3.2 One Google client on the backend

New `backend/services/google_client.py`. All Google web-service calls go through it:
- **Headers:** `X-Goog-Api-Key` and `X-Goog-FieldMask` (always a field mask; never `*`).
- **Timeouts:** 4 s (6 s for Routes).
- **Quota and pause detection:**
  - On HTTP 429, or 403 with `RESOURCE_EXHAUSTED` or a quota/billing reason, mark that API **paused until midnight Pacific time** (when Google resets) in Redis: `gmaps:paused:{api}`.
  - While paused, skip the call and use the fallback straight away.
- **Counters:** `gmaps:count:{api}:{yyyy-mm-dd}` in Redis, so you can see daily use per API. Log the API name, status and ms, never the user's text.
- **Cache:** Redis via the existing helpers, TTLs in section 3.4.
- Existing functions in `google_maps_service.py` are rewired to it. Their outputs don't change.

### 3.3 Fallbacks (the app must never break when the demo key pauses)

| Feature | Fallback |
| --- | --- |
| Map (Google engine) | Leaflet with free tiles (CARTO Voyager / Dark Matter, OpenStreetMap attribution). The same markers and data |
| Place search / nearby | Existing OSM search (`/api/places/search`) |
| Place details | The card data the user already saw + "More details unavailable" |
| Road distance/time (Routes) | Straight-line distance (`calculateDistance`, already built) |
| Weather (Google) | Open-Meteo (`weather_service.py`, already built) |
| Geocoding v4 | `searchNearby` (today's code path), then "Current location" |
| Grounding Lite (voice) | The tools from `voicefirst.md` without grounding |

### 3.4 Caching and Google's terms

- Place IDs can be stored indefinitely. Coordinates can be cached for a limited time (up to 30 days).
- Other Places content (names, hours, ratings, summaries) should only be cached **briefly**. **Check Google Maps Platform's Service Specific Terms before choosing TTLs.**
- Suggested short TTLs:
  - details 6 h;
  - nearby 30 min;
  - autocomplete 10 min;
  - weather current 15 min, daily forecast 3 h;
  - routes 30 min (keyed by rounded origin/destination + mode + hour);
  - geocode 24 h.
- **Attribution:** wherever Google Places data shows outside a Google map, show "Google Maps" attribution as Google's guidelines require. On a Google map it's built in.

### 3.5 Phase 0 test script

`backend/scripts/check_google_demo.py` calls each API once for Jaipur (Hawa Mahal) and prints OK / paused / error, ms, and which fields came back:
- Places `searchNearby` and `places/{id}`: **test whether `rating`, `userRatingCount`, `regularOpeningHours`, `editorialSummary` and `websiteUri` return values on the demo key**;
- Geocoding v4 reverse;
- Routes;
- Weather current and daily;
- Grounding Lite `tools/list`.

**Phase 0 done when:**
- [ ] The script shows which APIs and fields work on the owner's key; pasted into the Phase 0 report.
- [ ] `google_client.py` in place, with pause detection, counters and caching.
- [ ] All existing tests still pass.

---

## 4. Phase 1: compliance fixes (small, do immediately)

1. **Map tiles:** remove the `mt1.google.com/vt` tiles from `MapView.tsx`.
   - Until Phase 2 lands, use CARTO (Voyager for light, Dark Matter for dark), with the OpenStreetMap + CARTO attribution.
   - This is also the permanent `leaflet` fallback engine.
2. **Geocoding v4** for "where am I":
   - `GET https://geocode.googleapis.com/v4/geocode/location/{lat},{lng}`, header `X-Goog-Api-Key`.
   - Map `results[0]` address components to city/state/country as today.
   - Remove the `searchNearby` fallback step only once v4 is confirmed working.
3. **Empty ratings:** every card that shows a rating hides the whole rating row when it's missing or 0. Never show "0 ★" or "(0)".
4. **Attribution:** add "Places data © Google" under lists of Google places (Explore, Food, map cards), as the guidelines require.

**Phase 1 done when:**
- [ ] No request goes to `mt*.google.com/vt` (check the browser Network tab).
- [ ] The city name comes from Geocoding v4 in one call.
- [ ] No "0 ★" anywhere.
- [ ] Build and lint pass.

---

## 5. Phase 2: the map page, the rich version (biggest visual win)

Move `MapView.tsx` from Leaflet to **Google Maps JavaScript (`<gmp-map>`)** behind `VITE_MAP_ENGINE=google`. Keep the Leaflet engine (with CARTO tiles) for `leaflet` and for when the demo key pauses.

**Structure**
- `frontend/src/components/map/engines/GoogleMapEngine.tsx` and `LeafletMapEngine.tsx` share **one props interface**: center, markers, selected marker, user location, focus target, route polyline, theme.
- `MapView.tsx` keeps all logic: data loading, cards, search, add to itinerary, `mapFocusTarget`, Step 0e search. It only swaps the engine.
- Load Maps JS with the **dynamic import loader** (`importLibrary`), since the Places UI Kit needs it.
- Libraries: `maps`, `marker`, `places`, `routes` (only if used client-side), `maps3d` (for 3D).

**Features**

| Feature | How | Fallback |
| --- | --- | --- |
| Google base map in the app's theme | `<gmp-map map-id={GOOGLE_MAP_ID}>`. While on `DEMO_MAP_ID`, use the light/dark colour scheme; with your own Map ID later, add cloud styling matching the brand green (#1F5A3F) | Leaflet + CARTO |
| **Category markers** | `AdvancedMarkerElement` with a `PinElement` per category: temple (saffron, 🛕), food (orange), sights (green), stays (blue), the user (pulsing dot). Selected marker grows and bounces | Leaflet markers |
| **Marker clustering** | `@googlemaps/markerclusterer` when there are more than 30 markers | Leaflet cluster |
| **Tap a marker → compact details** | `<gmp-place-details-compact>` inside the existing bottom card, for Google place IDs. Our own card for mock places | Our card |
| **Satellite / terrain toggle** | Map type control (2D) | Hidden on Leaflet |
| **3D landmark view** | "View in 3D" on landmark cards → a `<gmp-map-3d>` sheet centred on the place, tilt 60, slow orbit. Great for Hawa Mahal / Amber Fort demos | Hidden |
| **Route to a place** | "Route" on a card → Routes (section 7) → draw the polyline, show "6.8 km · 22 min by car / 31 min by 2-wheeler" with a mode switch | Straight line + "X km away" |
| **Search** (Step 0e) | Keep the existing backend search (India only), or swap in Google's autocomplete element restricted to India | OSM search |
| **Directions in Google Maps** | "Open in Google Maps" link using the place's `googleMapsUri` or `https://www.google.com/maps/search/?api=1&query=lat,lng&query_place_id=ID` | Same link |

**Mobile:**
- the map fills the screen above the bottom nav;
- cards in a horizontal carousel as today;
- gestures `greedy` on the map page;
- 3D only on devices with WebGL2 (check, and otherwise hide the button).

**Phase 2 done when:**
- [ ] With `VITE_MAP_ENGINE=google`, the map, markers, user location, search, focus from voice/Explore, and Add to itinerary all work as before.
- [ ] Clustering, satellite toggle, route card and 3D view work on desktop Chrome and on a phone.
- [ ] Forcing the "paused" state (or a wrong key) switches to Leaflet + CARTO without errors.
- [ ] Lighthouse mobile performance not worse than before by more than 10 points.

---

## 6. Phase 3: place details page (fixes the "Details opens Explore" bug)

Route `/details/:placeId` (not `/trip/details`, which already exists for the itinerary).

- **Top:**
  - when the map engine is Google and the ID is a Google place ID: **`<gmp-place-details>`** with `<gmp-place-standard-content>`, styled with the UI Kit's CSS properties (fonts, brand green);
  - otherwise: our own header built from route state + our backend.
- **Our backend details** (`get_place_details`): extend the field mask to:
  - `id, displayName, formattedAddress, location, primaryTypeDisplayName, editorialSummary`;
  - `regularOpeningHours`, `currentOpeningHours.openNow`;
  - `nationalPhoneNumber, websiteUri, googleMapsUri`;
  - `rating, userRatingCount`, if Phase 0 shows they work.

  Clean keys out: `name, address, lat, lng, type, summary, open_now, hours[], phone, website, maps_url, rating, rating_count`.
- **Sections:**
  - name, type chip, distance;
  - **Open now / Closed** + today's hours (expandable week);
  - summary;
  - **weather at the place right now** (Weather current conditions, section 8);
  - **travel time from you** (Routes: car / 2-wheeler / walk);
  - a small static map or a `<gmp-map>` with one marker;
  - **3D view** button for landmarks.
- **Actions** (reuse existing code):
  - Add to itinerary (the same day picker);
  - Save / unsave;
  - audio guide speaker;
  - Open in Google Maps;
  - Call;
  - Website.
- **States:** skeleton while loading; card data only if the fetch fails or is paused; "Place not found" + back for bad IDs.
- **Map card's Details button:** `navigate('/details/' + encodeURIComponent(id), { state: { place } })`.

**Phase 3 done when:**
- [ ] Details opens the page.
- [ ] Back returns to the map in the same place.
- [ ] Reloading the URL works.
- [ ] Mock places don't error.
- [ ] Each section hides cleanly when its data is missing.

---

## 7. Phase 4: real travel times (Routes API)

Backend `services/routes_service.py`:
- `POST https://routes.googleapis.com/directions/v2:computeRoutes`.
- Field mask: `routes.distanceMeters,routes.duration,routes.polyline.encodedPolyline,routes.localizedValues`.
- Modes: `DRIVE`, `TWO_WHEELER` (good for India: bikes and autos), `WALK`. `TRANSIT` only if Phase 0 shows it works.
- `routingPreference` without live traffic (live traffic counts as a "Pro" option in Grounding Lite pricing; keep it off).
- `languageCode: "en-IN"`, `regionCode: "IN"`.
- Cache 30 min, keyed by origin/destination rounded to ~100 m + mode.
- Endpoint for the app: `GET /api/routes/eta?from=lat,lng&to=lat,lng&mode=DRIVE` (login required, rate-limited with the `places` bucket).

Where it shows up:

| Screen | What the user sees |
| --- | --- |
| Map card + details page | "6.8 km · 22 min by car · 18 min by 2-wheeler"; the route line on the map |
| **Itinerary day timeline** | Between two activities: a chip "🚗 15 min · 5.2 km". Computed once when the day loads; refreshed when the order changes |
| **Optimize day** (Step 6) | `optimize_day_flow_service` uses real durations instead of straight-line guesses, where available. Behind a flag first, compare results |
| Ride page | Estimated duration for the ride options shown today |
| Voice (Step 3) | "Amber Fort tak kitna time lagega?" → "Car se 25 minute, 11 km." |

**Phase 4 done when:**
- [ ] Map, details page and itinerary show real times.
- [ ] With Routes paused, the app shows straight-line distances, without errors.
- [ ] Request count per itinerary day is ≤ number of activities − 1.

---

## 8. Phase 5: weather that looks good (Weather API)

Backend `services/google_weather_service.py`; Open-Meteo stays as the fallback.

| Call | Endpoint (`https://weather.googleapis.com`) | Use |
| --- | --- | --- |
| Current | `GET /v1/currentConditions:lookup?location.latitude=..&location.longitude=..` | Home "right now" card, details page, map top-left chip |
| Hourly | `GET /v1/forecast/hours:lookup` (up to 240 h) | Today's itinerary: rain chance per time slot |
| Daily | `GET /v1/forecast/days:lookup` (up to 10 days) | Itinerary day headers: icon, high/low, rain chance, sunrise/sunset |
| Alerts | `GET /v1/publicAlerts:lookup` (only if Phase 0 shows it works on the demo key) | Red banner on the trip: "Heavy rain warning in Jaipur tomorrow" |

- **Icons:** use Google's `weatherCondition.iconBaseUri` + `.svg` (or `_dark.svg` in dark mode). They look much better than text.
- **Units:** metric. Language: `en` (Hindi labels from our own map of condition types where needed).

Where it shows up:
- **Home:** a "Right now in Jaipur" card: temperature, feels like, icon, UV, rain chance next 3 h.
- **Itinerary:**
  - each day header gets weather; days beyond 10 show "Forecast available from {date}";
  - outdoor activities on rainy slots get a small ☔ badge.
- **Weather replan** (Step 6): `weather_replan_service` reads Google hourly data first, Open-Meteo second. The voice reply can be exact: "Kal 2 se 5 baje baarish ka 80% chance hai."
- **Packing tip** on the trip page: "Umbrella le jaiye: 3 din mein se 2 din baarish."

**Phase 5 done when:**
- [ ] Day headers, home card and details page show Google weather with icons.
- [ ] With Weather paused, Open-Meteo data shows instead, without errors.
- [ ] Weather replan uses the same source as the screen.

---

## 9. Phase 6: smarter Explore and Food (Places API New)

- **Explore by category:** `searchNearby` with `includedTypes`:
  - sights: `tourist_attraction, museum, historical_landmark, hindu_temple, park`;
  - food: `restaurant, cafe, bakery`, plus a veg filter by keyword through Text Search when the user picks "Veg";
  - stays: `lodging`.
- **Text Search** (`POST https://places.googleapis.com/v1/places:searchText`) for "best thali in Jaipur" style queries from the search box and from voice, with `locationBias` near the trip.
- **"Open now" filter:** `currentOpeningHours.openNow` in the field mask (if Phase 0 shows it works); a chip on cards: "Open · closes 9 PM".
- **Editorial summary** as the card's one-line description (Google's own text, not user content).
- **Ranking:** keep `rank_places`, plus distance (from Routes when cheap, else straight line).
- No photos (not on the demo key). Keep the category illustration or icon style.

**Phase 6 done when:**
- [ ] Explore tabs (Sights / Food / Stays) load from Places (New).
- [ ] Open-now and veg filters work.
- [ ] Text search works.
- [ ] OSM fallback when paused.

---

## 10. Phase 7: voice agent + Maps Grounding Lite (ties into `voicefirst.md`)

Grounding Lite is Google's toolset made for AI agents:
- **MCP endpoint:** `https://mapstools.googleapis.com/mcp`. Auth: API key in `X-Goog-Api-Key`; the demo key works for testing.
- **Tools:** `search_places` (with AI summaries and Maps links), `lookup_weather`, `compute_routes` (distance and duration), `resolve_names` (names → place IDs), `resolve_maps_urls`.
- **Resolution REST methods**, no charge: `POST https://mapstools.googleapis.com/v1:resolveNames` and `v1:resolveMapsUrls`.

Uses, mapped to `voicefirst.md` steps:

| Use | Step | How |
| --- | --- | --- |
| **Fix garbled place names** ("Badaanasi", "वारा नसी" → Varanasi) | 1c | After the alias list, call `resolveNames` with the transcript's place text, biased to India. Take the top result if confident; otherwise the agent asks "Varanasi, sahi hai?" |
| "Kitna time lagega Amber Fort tak?" | 3 | The agent's `answer_question` (or a direct tool) calls `compute_routes` |
| "Kal Jaipur ka mausam?" | 3, 6 | `lookup_weather` |
| "Paas mein accha veg khana?" | 3 | `search_places` (≤ 5 results, to stay in the cheaper tier), spoken summary + results shown on the map |
| Weather replan wording | 6 | `lookup_weather` for the exact rain window |

**How to call it from our backend:**
- Call the Grounding Lite REST/MCP endpoints **from our backend tools** (`voice/tools/maps_grounding.py`) with the server key. Don't hand Groq a remote MCP server.
- Our agent keeps its own tool list. The backend decides, and every result goes through our usual checks.

**Required by Google** (build these, or don't use Grounding Lite):
- **Sources on screen:** Google Maps sources must appear right after the content they support, viewable in one tap. Each place needs Google Maps attribution and a link to its `googleMapsLinks.placeUrl` (and `reviewsUrl` if a summary includes review insights).
  → For voice: after a spoken answer from grounded data, the app shows a small **source card** with the place names and "View on Google Maps" links.
- **Voice interfaces need:**
  - that companion UI showing sources;
  - a disclosure that AI answers may include Google Maps information;
  - **a persistent disclosure in settings** (More → About voice).
- **The LLM must not train on the input data.** Confirm Groq's terms (they state they don't train on customer data) before turning this on. Gemini (tour guide) via the API is also fine; confirm for your account type.

**Phase 7 done when:**
- [ ] Step 1c's place-name test set: resolution rate with `resolveNames` reported (target ≥ 80%).
- [ ] Voice questions about time, weather and nearby places give grounded answers with a source card.
- [ ] Settings shows the disclosure.
- [ ] Turning Grounding Lite off (`VOICE_MAPS_GROUNDING=false`) falls back cleanly.

---

## 11. Phase 8: from demo to production (before real users)

- Create a **billed key** (same project or a new one). Set `GOOGLE_MAPS_KEY_MODE=billed`. Keep the same code.
- **Cost controls:**
  - set budget alerts in Google Cloud;
  - set per-API quotas per day;
  - keep field masks minimal;
  - keep the caches;
  - use Text Search / nearby with ≤ 10 results;
  - keep Grounding Lite searches at ≤ 5 places;
  - no live traffic.
- Keep the fallbacks: billed quotas can still run out.
- Remove `DEMO_MAP_ID`; create your own Map ID with cloud styling (brand colours, hide clutter POIs) and the 3D-capable vector map.
- Re-run `check_google_demo.py` (rename to `check_google_maps.py`) against the billed key.

---

## 12. Order, effort and what each phase looks like to users

| Phase | Effort (rough) | Visible result | Needs |
| --- | --- | --- | --- |
| 0. Foundations | 0.5–1 day | Nothing visible; safety net | — |
| 1. Compliance fixes | 0.5 day | Legal map tiles, correct city name, no "0 ★" | 0 |
| 2. Rich map | 2–3 days | Google map, category pins, clusters, satellite, routes, **3D landmarks** | 0, 1 |
| 3. Details page | 1 day | Real details page instead of Explore | 0 (2 for the UI Kit header) |
| 4. Travel times | 1 day | "22 min by car" everywhere, timeline chips | 0 |
| 5. Weather | 1 day | Weather icons on days, home card, alerts | 0 |
| 6. Explore/Food | 1 day | Category tabs, open now, veg, text search | 0 |
| 7. Voice grounding | 1–2 days | Exact spoken answers with sources; better place names | 0, `voicefirst.md` steps 1c/3 |
| 8. Production | 0.5 day | — | all |

**Suggested order:** 0 → 1 → 3 → 2 → 4 → 5 → 6 → 7 → 8. Phase 3 comes before 2 because it fixes a visible bug; its UI Kit header can be added once Phase 2 is in.

**For the hackathon demo, the biggest wow:**
- the 3D view of Hawa Mahal from the map card;
- real travel-time chips in the itinerary;
- weather icons on each day;
- the voice answer "Car se 25 minute" with a Google Maps source card.

## 13. Tests for every phase

- **Backend** (`backend/tests/test_maps_*.py`, Google simulated with `respx` or mocks):
  - field masks sent;
  - response mapping;
  - cache hit/miss;
  - **paused detection → fallback**;
  - counters;
  - bad inputs (place ID format, coordinates out of range);
  - no key → fallback;
  - no user text in logs.
- **Frontend:**
  - build + lint;
  - engine switch (`google` / `leaflet`);
  - paused-key behaviour (force with a wrong key);
  - 393 px and 1440 px screenshots per phase in the report.
- **Live:** `check_google_demo.py` before and after each phase. Report daily call counts from `gmaps:count:*` after a day of testing, to learn the demo key's real limits.

## Sources

- [Maps Demo Key (Google for Developers)](https://developers.google.com/maps/demo-key?hl=en)
- [Maps Demo Key overview](https://mapsplatform.google.com/maps-demo-key/)
- [Maps Grounding Lite](https://developers.google.com/maps/ai/grounding-lite)
- [Geocoding API v4 overview](https://developers.google.com/maps/documentation/geocoding/geocoding-v4-overview)
- [Reverse geocoding (v4)](https://developers.google.com/maps/documentation/geocoding/reverse-geocoding)
- [Weather API reference](https://developers.google.com/maps/documentation/weather/reference/rest)
- [Weather daily forecast](https://developers.google.com/maps/documentation/weather/daily-forecast)
- [Places UI Kit: Place Details elements](https://developers.google.com/maps/documentation/javascript/places-ui-kit/place-details)
- [Adopt Places UI Kit](https://developers.google.com/maps/documentation/javascript/adopt-places-ui-kit)