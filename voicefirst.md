# Voice-First VoyageAI — Plan v2

Nov 12, 2026

> **Instructions for whoever builds this (human or AI):**
>
> 1. Build **Step 0 only** (0a → 0b → 0c → 0d → 0e). Tick each box in section 3 as it's finished.
> 2. **Stop when Step 0 is complete.** Mark Step 0 as **DONE** here, with the date. Do not start any voice work.
> 3. Voice work (steps 1–7) starts only when the owner says **"start on voice"**. At that point, read this file, `voicefirst.md` in the repo root, first, and follow it from step 1.
>
> **Step 0 status:** DONE — 13 Nov 2026 (0a–0d on 12 Nov, 0e on 13 Nov; branch `step0-finish`). Tested with scripts and live against the real server, Neon database and Groq. One thing still needs the owner: a click-through of the screens in the browser (see "Step 0 notes").

## Summary

VoyageAI gets a mic button. The user speaks, the server collects what it needs, and the app jumps to an editable review page. Nothing is saved until the user taps Proceed or says "haan".

Voice work starts only after **Step 0** is done. Step 0 fixes security holes in the WebSocket actions, the hard-coded budget and the missing starting city. It also builds the non-voice features voice depends on, and moves AI calls from Gemini to Groq.

Status (14 Nov 2026):
- Step 0 is done.
- Voice steps 1 and 1b are done.
- Step 2 is built and on `main`, waiting for the owner's test.
- Steps 1c and 3–7 are planned in detail below (section 8).

The plan was first agreed on 12 Nov 2026.

## 1. What we are building

One small floating mic button, visible on every page after login. There is no separate Voice mode and no toggle. Tapping works exactly as today.

- **Tap to start, tap to stop.** Up to 30 seconds per recording. Tapping while the app is speaking stops the reply and starts listening.
- **Example:** "Delhi se Jaipur jaana hai 3 din ke liye, budget 20 hazaar."
- **The server collects first, then jumps.** It asks by voice for anything missing. When everything is in, the app opens the final page already filled.
- **The final page is the safety check.** It shows every detail (city, dates, travellers, budget). Everything on it is editable. The user taps Proceed or says "haan".
- **Small actions just happen,** with an Undo toast: save/unsave a place, mark an activity done, change a filter. Undo is by tap only.
- **Big actions ask first:** create trip, add expense, swap activity, regenerate itinerary, and later weather replan, optimize day and optimize budget.
- **Voice never deletes a trip.** It opens the trip and says the user must delete it themselves, at their own risk.
- **Replies are a short spoken summary;** details stay on screen. The spoken text and the audio arrive together. The app shows no captions and not what it heard, only a listening/speaking animation.
- **Language:** the reply matches the user's language (Hindi, English or Hinglish).
- **Off-topic requests** ("tell me a joke") are declined calmly.
- **Platform:** mobile web app.

## 2. What exists today (checked against the repo)

Updated 12 Nov 2026 after Step 0. The table first described the 6 Nov code; rows marked *(Step 0)* changed since.

| Piece | Where | State | Use for voice |
| --- | --- | --- | --- |
| Text-to-speech, Sarvam `bulbul:v3`, Redis cache, default voice `ritu` | `backend/tts_service.py` | Exists | Speak every reply |
| Play base64 audio | `frontend/src/hooks/useAudioGuide.ts` | Exists | Play replies |
| One WebSocket, ~40 actions | `frontend/src/services/wsClient.ts`, `process_ws_action` in `backend/main.py` | Exists | Unchanged; voice uses its own `/ws/voice` |
| Trip creation | `backend/trip_lifecycle.py` `create_trip_for_user`, used by WebSocket and REST | Exists *(Step 0)* | The agent's `create_trip` calls it |
| Ownership check | `backend/ownership.py`; every WebSocket trip action checked before it runs | Exists *(Step 0)* | Every agent tool goes through it |
| Rate limits | `rate_limiter.py`; `WS_RATE_LIMITS` in `main.py` for WebSocket actions | Exists *(Step 0)* | Add a `voice` bucket |
| Budget | `budget: {level, targetAmount}`; amount is what the user gave, level worked out from it | Exists *(Step 0)* | Agent collects the amount |
| Travellers | `adultsCount` / `childrenCount` on create; travellers saved as `ADULT` / `CHILD` | Exists *(Step 0)* | Agent asks adults and children |
| Itinerary download | `/api/trips/{id}/pdf` and Print/PDF in `ItineraryView.tsx` | Exists, owner only *(Step 0)* | "Ready" notice links here |
| Saved places | REST `/api/user/saved-places` | Exists | Small action with Undo |
| Mark activity done | WebSocket `trips:set_activity_done`, button on each activity, Undo toast | Exists *(Step 0)* | `mark_activity_done` tool |
| Tour guide chat | `tour_guide_service.py`, Gemini with Google Search grounding | Exists | Stays on Gemini |
| Other AI calls | `ai_provider.py` (`AI_PROVIDER=groq`), `complete_json()`, `cost_guard.py` | Groq first, Gemini backup *(Step 0)* | Agent uses Groq too |
| Cost guard | `backend/cost_guard.py` | Exists | Not used for voice: the agent declines off-topic requests itself |
| Place search, geocoding | `places.py`, `services/google_maps_service.py` | Exists | "Jaipur" to a real place |
| Starting city | `cities` table (`models_place.py`), `trips.origin_city_id`; looked up, created if missing | Exists *(Step 0)* | Agent fills `origin` |
| Trip review page | Step 6 of `TripCreationWizard.tsx`; opens pre-filled from `navigate('/trips/new', { state: { prefill } })` | Exists *(Step 0)* | The voice "jump" target |
| Undo toast | `frontend/src/components/common/UndoToast.tsx` (`useToast().showToast({ message, undo })`) | Exists *(Step 0)* | Small voice actions use it |
| Itinerary-ready notice | `frontend/src/components/trip/ItineraryReadyNotice.tsx` | Exists *(Step 0)* | Spoken version in voice |
| Weather | `backend/weather_service.py` (Open-Meteo, real forecast, 16 days ahead) | Exists *(Step 0)* | `weather_replan` tool |

Missing for voice: speech-to-text, mic recording, the agent, and a way for the server to tell the app which page to open.

## 3. Step 0: everything before voice

Everything that isn't voice-specific is done first, in order 0a, 0b, 0c, 0d. Security comes first because those holes are live now.

### 0a. Security

13 WebSocket trip actions have no login check and no ownership check. Anyone connected can read or change any trip by its ID. `regenerate_itinerary` and the optimize actions also spend paid AI calls.

- [x] Login and ownership check on: `get_itinerary`, `get_stays`, `add_stay`, `get_transports`, `add_transport`, `get_expenses`, `add_expense`, `weather_replan`, `optimize_day`, `optimize_budget`, `refine`, `regenerate_itinerary`, `swap_activity`
- [x] Fix `trips:delete`: today it deletes the itinerary, stays, transports and expenses of any trip ID; only the trip row is checked
- [x] Ownership check on the download endpoint `/api/trips/{id}/pdf`, which today accepts guests
- [x] Rate limits on WebSocket actions, strictest on the ones that cost AI money
- [x] Keep one `verify_trip_ownership()` (it is defined twice)
- [x] Remove the dead second `ai:concierge` handler (~line 1681), which never runs

Done when: another user's trip ID is refused on every action.

### 0b. Data

- [x] Save the budget amount the user gives (₹30k, ₹45k, ₹60k…); remove both hard-coded 30000s
- [x] Work out the budget level automatically from amount ÷ days ÷ people, so existing itinerary prompts keep working; the user never sees the level
- [x] Add `origin` (starting city) to trips as a real place; if the city is not in the table, create it
- [x] One shared trip-creation function used by both the WebSocket and REST paths

Done when: a trip created with ₹45,000 and "from Delhi" reads back with both.

### 0c. Screens and features (tap users benefit too)

- [x] Trip review page: every detail shown and editable on the same page, with a Proceed button
- [x] Trip wizard accepts pre-filled values
- [x] Travellers entered as adults and children
- [x] Mark activity done, with Undo
- [x] Undo toast for small actions (save/unsave place, mark done, filters)
- [x] In-app "itinerary ready" notification: "Your itinerary is ready to download. Shall I take you to the page?"
- [x] Itinerary generation suggests transport (train, flight, bus) from the starting city; the AI chooses based on budget
- [x] Check weather replan, optimize day and optimize budget work end to end by tap

Done when: all of the above work by tapping, with no voice.

### 0d. AI provider switch

- [x] Move all AI calls from Gemini to Groq (e.g. `gpt-oss-120b`) through one provider setting in `ai_provider.py`
- [x] Tour guide chat stays on Gemini, for Google Search grounding and Maps-checked places
- [x] Keep Gemini as a backup if Groq fails or hits its limit

Known limit: Groq's free tier allows about 8,000 tokens per minute for the whole account, roughly one itinerary per minute across all users. That's accepted for testing; itinerary generation will need the paid tier first.

### Step 0 notes (12 Nov 2026)

**How each item was built**

- **0a:**
  - Most of it was already on `main` from the 12 Nov security commit.
  - Step 0 added `trips:set_activity_done` to the checked actions.
  - A test confirms that all 14 trip actions refuse another user's trip and require login.
- **Budget level:** worked out as amount ÷ days ÷ people.
  - A child counts as half a person.
  - Per person per day: under ₹2,500 → BUDGET; under ₹6,000 → MODERATE; under ₹12,000 → PREMIUM; above that → LUXURY.
  - Example: ₹45,000 for 3 days, 2 adults and 2 children → ₹5,000 → MODERATE.
  - A trip created with no amount keeps the level it was given. Budget optimize then asks the user to add an amount instead of inventing ₹30,000.
- **Starting city:**
  - Stored once in the new `cities` table and reused by every trip that starts there.
  - India only, like destinations.
- **Transport suggestions:**
  - Asked for in the itinerary prompt when a starting city is known, using the real budget and the group size.
  - Saved as transport with status `RECOMMENDED`, and shown under "Getting there" on the itinerary page.
  - The itinerary cache key now includes the starting city.
- **Weather replan:**
  - Used to run on a made-up "Monsoon Heavy Downpour" forecast. It now uses a real Open-Meteo forecast.
  - For trips more than 16 days away, it says the forecast isn't available yet.
  - With no bad weather, it says so and changes nothing.
- **Groq:**
  - `AI_PROVIDER=groq` is now the default: Groq first (`GROQ_MODEL`, default `openai/gpt-oss-120b`), with Gemini as the backup on any error or rate limit. Mock data is never used as a backup.
  - The cost guard follows the same Groq-then-Gemini order and still fails closed.
  - Swap options and destination highlights now go through `complete_json()`.

**Tested**

- **`step0_test.py` (27 checks):**
  - Two users.
  - Budget, level, starting city (reused, not duplicated), adults and children.
  - Transport suggestion saved; mark done and undo.
  - Another user refused on all 14 trip actions.
  - Optimize day and budget work.
  - Weather says "not yet" for far-off trips.
  - Groq → Gemini fallback with simulated responses.
  - Cost guard fails closed.
- **Earlier ownership test:** 21/21.
- **Rate-limiter tests:** pass.
- **Weather:** a live forecast call for Jaipur works.
- **Frontend:** builds with no type errors.

**Tested live on 13 Nov 2026** (real server on :80, worker, Neon, Groq key added)

- **Groq:** JSON calls answer in under a second. The provider chain is Groq → Gemini. The cost guard lets travel and emergency questions through and blocks off-topic ones ("write a python script" → `OFF_TOPIC`).
- **Real Postgres:** startup logged `[DATABASE INIT] Neon schema sync complete`. Neon has the `cities` table, `trips.origin_city_id` (linked to `cities`) and `itinerary_activities.is_done`.
- **Whole flow over the real WebSocket (26/26):**
  - Two throwaway accounts were used and deleted afterwards.
  - Jaipur from New Delhi, 2 adults + 2 children, ₹45,000 → MODERATE.
  - Same request ID → no duplicate trip.
  - Itinerary generated by Groq and `ITINERARY_READY` pushed to the owner only, in 11 seconds.
  - 3 days, 12 activities.
  - Transport suggested from Delhi: Shatabdi 2nd AC ~₹3,800 and an outstation cab ~₹14,000.
  - Mark done and Undo.
  - The other user refused on every trip action.
  - Weather replan with a real forecast ("No bad weather expected").
  - Optimize day; optimize budget against ₹45,000; delete.

**Finished on 13 Nov 2026 (were "not changed")**

- **Food sheet save button:** now saves on the server (the same saved places as Explore and Saved places), with an Undo toast. `toggleSavePlace` was removed from `AppContext`.
- **Food sheet refetch loop:** with location off, the nearby-food request used to re-run on every render. Fixed.
- **Demo Goa trip:** `AppContext.activeTrip` no longer starts from it. Screens only read `id`, `title` and `destination`, which come from the real trip. The home page never showed a demo budget; the earlier note was wrong.

**Not tested yet (needs the owner)**

- The screens in a browser: wizard and review page, mark done + Undo, save/unsave + Undo (including the food sheet), the ready notice, "Getting there", the `/trip` empty state, Past trips, and map search.

### 0e. Fixes found after Step 0 (added 13 Nov 2026)

These two were found while using the app after Step 0. They are fixed before any voice work.

#### Past trips shown as current on /trip

**What happens:** `/trip` opened an old Mumbai trip whose dates had already passed.

**Cause:** creating a trip with past dates is already blocked (wizard + `trip_lifecycle._parse_dates`). Old trips are never closed, though:
- `status` stays `PLANNING` forever; nothing sets `COMPLETED` when the end date passes.
- `tripRepository.selectCurrentTripId()` restores the last-viewed trip from local storage, else picks the first `ACTIVE`/`PLANNING` trip. It never looks at dates.

**Fix:**

- [x] Backend: a trip whose `end_date` is before today becomes `COMPLETED`. Work it out whenever trips are read (`trips:list`, `/api/trips`, trip get) and save it, so no scheduled job is needed. Use the Asia/Kolkata date for "today".
- [x] Frontend: `selectCurrentTripId()` never auto-selects a `COMPLETED` trip, including the last-viewed one from local storage. Order: an ongoing trip (today between start and end), then the nearest upcoming trip by start date.
- [x] `/trip` with no ongoing or upcoming trip: an empty state with a **Plan a trip** button and a link to **Past trips**.
- [x] My trips page: a **Past trips** section listing completed trips, newest first. They can be opened and viewed, but are never opened automatically.

Done when: a trip that ended yesterday never opens by itself on `/trip`, appears under Past trips, and `/trip` shows the empty state when it was the only trip.

#### Search on the map

**What exists:**
- `MapView.tsx` (Leaflet + Google tiles) shows the current location and nearby places.
- It can already fly to a place and show its distance through `mapFocusTarget` + `calculateDistance()` (straight line).
- The backend already has place search (`places:search` on the WebSocket; `autocomplete_places` in the Google Maps service).

**What's missing:** a search box.

**Fix:**

- [x] A search bar at the top of the map, with suggestions while typing (debounced, ~300 ms), using the existing backend search.
- [x] Results limited to **India only**; not biased towards the trip's destination.
- [x] With no search, the map shows the current location (as today).
- [x] Choosing a result flies the map there, drops a pin, and shows **"X km from you"**: straight-line distance from the current location. If location access is off, show the place without a distance and say "Turn on location to see distance".
- [x] Clearing the search returns the map to the current location.

Done when: searching "Hawa Mahal" from Delhi flies to Jaipur, pins it and shows about "240 km from you"; a search for a place outside India returns no results.

**Decided:** straight-line distance for now. Road distance and travel time (Google Routes API, a paid call per search) come later.

#### 0e notes (13 Nov 2026)

**Past trips**
- `trip_lifecycle.close_finished_trips()` sets open trips (`PLANNING`, `UPCOMING`, `ACTIVE`, `CONFIRMED`) whose end date is before today (India date, `today_ist()`) to `COMPLETED`, and saves it.
  - Cancelled and archived trips are left alone.
  - It runs on `trips:list`, `GET /api/trips` and `GET /api/trips/{id}`.
  - Trip creation's "no past dates" check uses the same India date.
- `tripRepository.selectCurrentTripId()` order:
  1. The last-viewed trip, only if it's still current.
  2. An ongoing trip.
  3. The nearest upcoming trip by start date.
  4. Otherwise nothing.
  A trip whose end date has passed counts as past even before the server closes it. The tour guide page used to fall back to "the first trip in the list"; it now skips past trips too.
- `/trip` with no current trip shows **No current trip**, with **Plan a trip** and **Past trips (n)**. It shows a loading line while trips load.
- My trips: the "Completed" tab is now **Past trips**, newest first (latest end date at the top). Opening one is still possible by tapping **View Trip Details**.

**Map search**
- The search bar sits between the back button and the recenter button.
  - Suggestions appear after 300 ms, via `places:search`, which is India-only on the server (`includedRegionCodes: ["in"]`, no trip bias).
  - The app also filters with `isInIndia()`, the same rule the trip wizard uses.
  - Enter picks the first suggestion; Esc clears.
- Choosing a place flies there, drops a pin and shows a card: "X km from you (straight line)" from the GPS location only, never from the trip destination. With location off, it says "Turn on location to see distance".
- Clearing removes the pin and flies back to the current location (or all of India).
- The map now always opens. Before, with no location and no trip, it showed only "Locating…". If GPS answered after the page opened, the map never started. Now it starts over India and moves to the location when it arrives.

**Tested**
- `step0e_test.py` (13 checks, SQLite):
  - A trip that ended yesterday → `COMPLETED` on REST list, WS list and REST get, saved in the DB.
  - A trip ending today stays open; cancelled stays cancelled.
  - "Today" is the India date (23:30 UTC = next day in India).
- Trip selection, 13 checks on the real `tripRepository.ts`:
  - A trip that ended yesterday is never selected, even as last viewed.
  - Ongoing beats upcoming; nearest upcoming wins.
  - The only trip being past → nothing selected (so `/trip` shows the empty state).
- Map search against the live server:
  - "Hawa Mahal" → Hawa Mahal, Jaipur, **232 km** from Delhi.
  - "Eiffel Tower Paris" → no results.
  - Note: "Times Square New York" returns Indian shops with "New York" in their name, such as "New York Burrito Company". They are real places in India, so they are shown.
- Earlier tests still pass: Step 0 27/27, ownership 21/21, rate limiter all pass. Frontend builds.

**Also fixed while doing 0e**
- `POST /api/trips/itinerary/add` accepted guests. When the caller had no trip of their own, it fell back to *the newest trip of any user* and added the activity there.
  - It now needs login and only uses the caller's own trips.
  - Tested: guest → 401; a user with no trips → 404 and nothing written; another user's trip ID → 404; the owner → 200.

**Seen but not changed**
- The worker logged `Job failed: Timeout reading from socket` twice in its first two minutes on 13 Nov, then ran jobs normally. It looks like a Redis connection timeout while idle, and it's reported as a failed job even when no job was taken. Worth a look before production.
- The food sheet still fills in made-up details when a place has none: rating 4.5, "10:00 AM – 11:00 PM" and "Vegetarian Friendly". Because of that, the **Pure Veg** filter shows every place.

## 4. How one voice turn works

The backend decides and the app only shows. All rules (login, ownership, limits, validation) stay on the server.

*(Updated 14 Nov 2026 to match what was built in steps 1–2. The first version described MediaRecorder and a `voice:turn` action on `/ws/app`; that design was replaced.)*

1. **Open.**
   - The first mic tap opens a separate socket, **`/ws/voice`**.
   - Login comes from the session cookie, or an `auth` message within 5 s.
   - Foreign origins are refused.
   - `/ws/app` is untouched, so a voice turn never blocks other app requests.
2. **Start.** The app sends `{"type":"start","conversation_id","screen","trip_id"}`. The server answers `{"type":"recording","turn_id"}`.
3. **Stream.**
   - The mic runs with echo cancellation and noise suppression.
   - An AudioWorklet (`frontend/public/pcm-worklet.js`) converts it to **16 kHz, 16-bit, mono PCM**.
   - It sends ~100 ms binary frames while the user speaks. There's no VAD and no base64.
   - The mic needs HTTPS.
4. **Stop.** The second tap, or 30 s, sends `{"type":"stop"}`. The server caps each recording at 30 s (960 KB).
5. **Speech to text.** The PCM gets a WAV header and goes to Groq Whisper (`voice/stt.py`, provider swappable). The audio is thrown away after the call. The `transcript` message goes out at once (for the test panel).
6. **Agent.** A Groq model with tools (`voice/agent.py`) reads:
   - the transcript;
   - the conversation memory (Redis, last 10 turns);
   - the current screen and the open trip.

   It calls a tool, asks a question, or declines.
7. **Backend checks.** Every tool call goes through the backend before anything happens:
   - page names through `voice/pages.py`;
   - trips and activities through `ownership.py`.

   Small actions run now. Big ones become a **pending action** waiting for "haan" or a tap on Confirm (step 4 onwards).
8. **Spoken reply.** Sarvam TTS (`voice/tts.py`), voice `ritu`, no caching of the user's words.
9. **Reply to the app** in one message: `{"type":"reply", reply_text, reply_audio_base64, mime, ui_actions, action, llm_ms, tts_ms}`. Later steps add `pending_confirmation`.
10. **App.**
    - Runs the `ui_actions` first: change page, open the filled review page, show the Confirm card or the Undo toast, refresh data.
    - Then shows the speaking animation and plays the audio.
    - Tapping the mic during playback interrupts it (barge-in).

During trip creation, most turns send no `ui_actions`. The server keeps a **draft trip** in Redis and fills it turn by turn. Only the final turn sends one action: "open the filled review page". If the user leaves midway, the draft and the conversation are thrown away.

For testing, a **developer-only transcript view** shows what was heard. It is visible only to the developer account, shown live and never saved.

## 5. The agent and its tools

The agent is a Groq model with function calling. It never touches the database. It can only call the tools below, and each tool runs as the logged-in user through the ownership check.

| Tool | Group | Behaviour | Voice step |
| --- | --- | --- | --- |
| `navigate(page, day?)`: Home, My trips, Trip, Itinerary (day), Map, Food, Rides, Expenses, Explore, Guide, Saved places, More, Plan trip | Look and move | Runs now | 2 (built) |
| `list_my_trips()`, `open_trip(trip)` | Look and move | Runs now | 3 |
| `search_places(query)` | Look and move | Runs now (shows the place on the map) | 3 |
| `answer_question(question)` | Look and move | Runs now; answered by the tour guide (Gemini with Google Search), short for voice | 3 |
| `update_trip_draft(fields)` | Collect | Fills the server draft; jumps to the review page when complete | 4 |
| `create_trip(...)` | Big | Waits for Proceed or "haan" | 4 |
| `save_place`, `unsave_place`, `mark_activity_done`, `set_filter` | Small | Runs now, Undo toast | 5 |
| `add_expense(trip, title, amount, category)` | Big | Asks first | 5 |
| `swap_activity(activity, replacement)` | Big | Asks first | 5 |
| `regenerate_itinerary(trip)` | Big | Asks first (costs an AI call) | 5 |
| `delete_trip` | Not a tool | Opens the trip; says the user must delete it themselves, at their own risk | 5 |
| `weather_replan`, `optimize_day`, `optimize_budget` | Big | Ask first | 6 |
| `add_stay`, `add_transport`, `refine` | Big | Ask first | Later |

**How confirmation works (enforced on the server):**

1. The agent calls a big tool. The server does **not** run it. It saves a pending action in Redis (expires after 5 minutes) and replies with a summary.
2. The user says "haan"/"yes" or taps Proceed/Confirm. Only then does the confirm handler run the real function.
3. "No", a new topic or the 5-minute expiry cancels it.

The agent cannot skip step 2: the real function is only ever called from the confirm handler.

**When a request is unclear,** the agent asks. Example: two Goa trips gets "the March one or the December one?". A place name that could mean more than one place gets the same treatment.

## 6. Create-trip conversation

The user stays where they are while the agent asks. The app jumps once, to the filled review page, after the date has been said back and confirmed.

| Who | Says | On screen |
| --- | --- | --- |
| User | "Delhi se Jaipur jaana hai 3 din ke liye, budget 20 hazaar" | Listening animation |
| App | "Jaipur for 3 days. Kab se jaana hai, aur kitne adults aur kitne bachche?" | Speaking animation |
| User | "Agle Friday se, 2 adults aur 2 bachche" | Listening animation |
| App | "14 November, Friday se, sahi hai?" | Speaking animation |
| User | "Haan" | Listening animation |
| App | "Done, details check karke Proceed dabaiye." | Jumps to the filled, editable review page |
| User | Taps Proceed or says "haan" | Trip created, itinerary starts generating |
| App (later) | In-app notice: "Your itinerary is ready to download. Shall I take you to the page?" | On "haan", opens the download page |

**Required before the jump:** destination, start date (said back and confirmed), number of days or end date, adults and children, budget amount.

**Optional:** starting city, travel style. If the starting city is given, itinerary generation suggests transport that fits the budget. Anything missing comes from the user's saved preferences.

## 7. Voice changes by area

Only voice-specific work is listed here; everything else is in Step 0.

*(Updated 14 Nov 2026: what exists after steps 1–2, and which step adds the rest.)*

**Backend: `backend/voice/`**

| File | Job | Added in |
| --- | --- | --- |
| `ws.py` | `/ws/voice`: login, origin check, 30 s cap, rate limit (15/min, 100/day), message routing | 1 |
| `stt.py` | Speech to text, Groq Whisper; provider chosen by `VOICE_STT_PROVIDER` | 1 (Wispr Flow in 1c) |
| `pipeline.py` | One turn as stages: STT → agent → TTS; `after_turn` for the test-only store | 1, grows every step |
| `messages.py` | All message shapes and user-facing error texts | 1, grows every step |
| `debug_store.py` | Test-only saving (`testing.md`) | 1 |
| `tts.py` | Sarvam replies, `use_cache=False` | 1b |
| `agent.py` | The mind: system prompt, tools, memory, checks | 2, grows every step |
| `pages.py` | Page name → route, confirm sentences | 2 |
| `tools/` | One file per tool group: the backend checks and actions behind each tool | 3 |
| `pending.py` | Pending big actions in Redis (5 min), confirm and cancel | 4 |
| `draft.py` | The trip draft in Redis, required fields, read-back | 4 |
| `context.py` | Facts about the open trip (days, activities, expenses) for the prompt | 5 |

**Shared trip actions** (step 5): the add-expense, swap and mark-done logic moves out of `main.py` into `backend/trip_actions.py`. Taps (`/ws/app`) and voice then use the same functions.

**Frontend: `frontend/src/voice/`**

| File | Job | Added in |
| --- | --- | --- |
| `MicButton.tsx` | Floating mic after login; idle, recording, waiting, speaking; barge-in | 1, 1b |
| `useVoiceRecorder.ts` + `public/pcm-worklet.js` | Mic → 16 kHz PCM frames | 1 |
| `voiceSocket.ts` | `/ws/voice` client | 1 |
| `replyPlayer.ts` | iPhone-safe reply playback | 1b |
| `uiActions.ts` | Runs `ui_actions` from an allowlist | 2, grows every step |
| `ConfirmCard.tsx` | Confirm / Cancel card for pending actions | 4 |
| `TestTranscriptPanel.tsx` | Developer-only panel (`VITE_VOICE_TEST_TRANSCRIPT=true`) | 1, removed in 7 |

**Removed from the first plan:**
- the Normal/Voice toggle;
- captions for users;
- `voice:turn` on `/ws/app`;
- MediaRecorder.

## 8. Build order

Each step works and can be tested on its own. We review after every step before starting the next.

| Step | Delivers | Done when |
| --- | --- | --- |
| 0a. Security | Login and ownership checks on all WebSocket trip actions and the download; WebSocket rate limits | Another user's trip ID is refused everywhere |
| 0b. Data | Real budget amount, level worked out from it; `origin`; one trip-creation function | ₹45,000 and "from Delhi" read back correctly |
| 0c. Screens | Editable review page, adults/children, mark done, Undo, ready notice, transport suggestions | All work by tap |
| 0d. AI switch | Groq everywhere except tour guide chat; Gemini as backup | Itinerary, swap and optimize work on Groq |
| 0e. Fixes | Past trips closed automatically, /trip empty state, Past trips section; map search (India only) with straight-line distance | Ended trips never open by themselves; "Hawa Mahal" search pins it with distance |
| 1. Voice pipeline (test phase) | Dedicated `/ws/voice` pipeline: tap mic, PCM streamed to the backend, Groq Whisper transcribes, transcript shown in a temporary test panel. Nothing stored. See "Step 1 in detail" | Hindi, English and Hinglish transcripts appear on screen; nothing saved anywhere |
| 1b. Spoken reply | Sarvam speaks a short reply on top of the step 1 pipeline. **Built 13 Nov 2026**, see "Step 1b notes" | Reply audio plays after each turn |
| 2. Navigation | "Open my itinerary", "food dikhao". **Built 13 Nov 2026, waiting for owner test** (eval 91%), see "Step 2 notes" | Every page reachable by voice |
| 1c. Hearing better | Fix the speech-to-text problems found in testing; Wispr Flow as a provider (hackathon). Can run any time. See "Step 1c in detail" | Saved clips re-scored; place names and language detection better than Groq alone |
| 3. Questions and look-ups | Travel questions answered briefly; find a place on the map; list and open trips; step 2's eval misses fixed. See "Step 3 in detail" | Spoken answers are short and correct; "Hawa Mahal dikhao" pins it on the map; "Goa wali trip kholo" opens it |
| 4. Create trip | Collect details, read the date back, jump to the filled review page, Proceed. Adds pending actions and the Confirm card. See "Step 4 in detail" | Nothing created without Proceed or "haan"; edits on the review page are what gets saved |
| 5. More actions | Small actions with Undo; expense, swap and regenerate with confirmation; delete redirects; shared trip actions. See "Step 5 in detail" | Each behaves as decided; other users' trips untouchable |
| 6. Smart actions | Weather replan, optimize day, optimize budget by voice. See "Step 6 in detail" | Work on the user's own trip only, after confirmation, and say what changed |
| 7. Polish | Speed, errors, voice choice, phone testing, test panel off. See "Step 7 in detail" | Second tap → reply heard in ≤ 3 s on a phone; ready for real users |
| Later | Add stay, add transport, refine trip by voice | Not scheduled |

**Order:** 3 → 4 → 5 → 6 → 7. Step 1c can run in parallel at any time; the hackathon needs Wispr Flow, so do it before the demo.

**Rules for every step** (same as steps 1 and 2):
- Work on a local branch named `voice-stepN`.
- Do not push, open a PR or merge until the owner says where.
- Every new tool goes through the backend checks and the ownership check. The LLM never touches data itself.
- Logs carry action names, timings and error codes, never the user's words.
- New `ui_actions` types are added to the frontend allowlist in `uiActions.ts`; anything unknown is ignored.
- Each step ends with: unit tests (Groq and Sarvam simulated), an eval script with real Groq (run once per change), the owner's own test by voice, and a "Step N notes" section here.

### Step 1 in detail: the voice pipeline (first testing phase)

**Goal:** speak into the app and see what Groq Whisper heard, on screen. The pipeline built here is the one every later step adds to (agent, tools, spoken reply). Nothing is stored: no audio, no transcript.

**Flow**

1. Tap the mic: the app opens `/ws/voice` (if not already open) and sends `{"type":"start","conversation_id":"…","screen":"/current/path"}`.
2. While speaking: ~100 ms chunks of 16 kHz, 16-bit, mono PCM go up as **binary** frames.
3. Second tap, or 30 s: the app sends `{"type":"stop"}` and stops the mic tracks.
4. The backend adds a WAV header, calls Groq Whisper, and **throws the audio away** right after the call.
5. The backend replies `{"type":"transcript","turn_id":"…","text":"…","language":"hi","duration_ms":4200,"latency_ms":640}`, or `{"type":"error","code":"…","message":"…"}`.
6. The app shows the transcript in the **test panel**.

**Backend: a dedicated `backend/voice/` package**

| File | Job | Later steps |
| --- | --- | --- |
| `voice/ws.py` | `/ws/voice` endpoint, mounted in `main.py`. Checks the login token against `sessions` on connect and closes if invalid. Reads `websocket.receive()`: text means control, bytes means audio. Caps each recording at 30 s / 960 KB. Rate limit bucket `voice`: 15 per minute, 100 per day per user. One recording at a time per connection. | Unchanged |
| `voice/stt.py` | Speech-to-text interface plus `GroqWhisperSTT`: PCM to WAV (`wave` module), `whisper-large-v3-turbo`, `response_format=verbose_json`, language on auto, optional romanized Hinglish `prompt`. Returns text, language, duration and latency. Provider chosen by `VOICE_STT_PROVIDER`. | Sarvam/xAI providers can be added |
| `voice/pipeline.py` | `run_turn(pcm, ctx)`: runs the stages of one turn in order. Step 1 has a single stage, STT. | Agent, tools and TTS are added as stages |
| `voice/messages.py` | Message shapes (`start`, `stop`, `transcript`, `error`) in one place | Extended |

**Frontend: a dedicated `frontend/src/voice/` folder**, separate from `wsClient`

| File | Job | Later steps |
| --- | --- | --- |
| `frontend/public/pcm-worklet.js` | Converts 44.1/48 kHz float audio to 16 kHz Int16; posts a chunk every 1,600 samples | Unchanged |
| `frontend/src/voice/voiceSocket.ts` | Opens `/ws/voice` with the login token; sends `start`, binary chunks and `stop`; receives replies; reconnects on drop | Unchanged |
| `frontend/src/voice/useVoiceRecorder.ts` | Mic permission (echo cancellation and noise suppression on), AudioContext created inside the tap, 30 s countdown, stops tracks on stop | Unchanged |
| `frontend/src/voice/MicButton.tsx` | Floating button on every page after login; idle, recording (red + countdown) and waiting states | Gains the speaking animation |
| `frontend/src/voice/TestTranscriptPanel.tsx` | **Temporary, test phase only.** Small panel listing each transcript with language, clip length and Groq latency. Shown only when `VITE_VOICE_TEST_TRANSCRIPT=true`. Kept in React state only: gone on reload, never saved. | Removed (or flag off) when testing ends |

**Not stored anywhere**

- Audio exists only in memory until the Groq call returns.
- The transcript is sent once to the app and kept only in the panel's memory.
- Server logs keep the turn ID, clip length, latency and status. No words, no audio.
- **Only exception:** the test-only saving in `testing.md`. It saves to **local Postgres** and `test_audio_folder/`, and only when `VOICE_DEBUG_STORE=true`. It's off by default and never set on the cloud server.

**Settings**

```
# backend/.env
GROQ_API_KEY=...
VOICE_STT_PROVIDER=groq
VOICE_STT_MODEL=whisper-large-v3-turbo

# frontend/.env
VITE_VOICE_TEST_TRANSCRIPT=true
```

**Errors the app should show in the panel**

- Mic permission denied.
- Socket closed or login expired.
- Recording too short (under 0.3 s).
- Groq error or rate limit ("Try again in a minute").

**Done when**

- [ ] Logged in, the mic button appears on every page; logged out, it doesn't.
- [ ] Hindi, English and Hinglish sentences show correct transcripts in the panel, on Android Chrome and iPhone Safari (over HTTPS).
- [x] A 40-second recording is cut at 30 s. *(Server cut and the app's 30 s timer are both built; the server side is tested.)*
- [ ] Each error listed above shows a clear message.
- [x] Nothing is written to the database or disk; logs contain no words. *(With `VOICE_DEBUG_STORE=false`.)*
- [x] Other app requests on `/ws/app` keep working while a voice turn is running.
- [ ] Transcription time (Groq latency) noted for ~20 clips, to plan the ~3-second target.

#### Step 1 notes (13 Nov 2026, branch `step0-finish`)

**Status: built and tested by script. Not yet tried in a browser or on a phone.** The four open boxes above need the owner: the mic button, real Hindi/Hinglish speech on Android and iPhone over HTTPS, the error messages on screen, and about 20 clips.

**What was built**
- **Backend `backend/voice/`:**
  - `messages.py`: message shapes and user-facing error texts.
  - `stt.py`: `GroqWhisperSTT` with verbose_json, the language as a code (`hi`/`en`) and a romanized Hinglish spelling hint (`VOICE_STT_PROMPT`).
  - `pipeline.py`: `run_turn` (STT stage) and `after_turn` (the last stage, the test-only store).
  - `debug_store.py`: from `testing.md`.
  - `ws.py`: `/ws/voice`, mounted in `main.py` with `mount_voice(app, origin_allowed=is_allowed_origin)`.
- **Frontend:**
  - `frontend/public/pcm-worklet.js`
  - `frontend/src/voice/voiceSocket.ts`
  - `frontend/src/voice/useVoiceRecorder.ts`
  - `frontend/src/voice/MicButton.tsx`: mounted in `App.tsx`; logged-in users only; stacked above the AI button.
  - `frontend/src/voice/TestTranscriptPanel.tsx`: also shows the clip length, Groq time and the round trip from stop to transcript.

**Small additions to the plan**
- **Login on `/ws/voice`:** the session cookie, or a first message `{"type":"auth","token":"…"}` within 5 s (the app always sends it). Tokens are never put in the URL.
- A browser `Origin` that isn't in `ALLOWED_ORIGINS` is refused (close 4403). Otherwise another website could use the login cookie.
- The server confirms `start` with `{"type":"recording","turn_id"}` and sends `{"type":"ready"}` after login.
- **When the 30 s cut is reached,** the server transcribes right away and marks the transcript `truncated: true`. The app's late `stop` is then ignored.
- **The login is checked again on every `start`,** so logging out elsewhere stops voice too.
- **Rate limits** are checked on `start`: 15 a minute and 100 a day per user. They fail closed: if Redis is down, voice says "unavailable".

**Tested**
- `voice_step1_test.py`: 31 checks, with SQLite plus a throwaway local Postgres DB and simulated Groq.
  - Login: cookie, auth message, bad token, no login, foreign origin.
  - Transcript fields; under 0.3 s → `too_short`; stop without start; 40 s cut at 30 s and transcribed once.
  - `busy` while transcribing, while `/ws/app` still answers in 0.01 s.
  - A Groq failure gives a clear message.
  - The 16th recording in a minute → `rate_limited`.
  - Store off: nothing saved.
  - Store on: real IDs, timings, turn order, a failed row plus its WAV, WAV format, `session_full.wav` length, `voice_sessions` on both `end_session` and socket close.
  - A non-local `VOICE_DEBUG_DATABASE_URL` is refused.
- **Live, through the running server with Groq** (two clips made with Windows' English voice; Windows has no Hindi voice):
  - English: "I want to go from Delhi to Jaipur for 3 days. My budget is 20,000 rupees." Groq 810 ms.
  - Romanized Hinglish: "Mujhe Delhi se Jaipur jaana hai, 3 din ke liye, budget b's hazaar hai." Groq 782 ms. "bees" came out as "b's" because the English voice mispronounced it.
  - **Stop → transcript on screen ≈ 0.8 s** for a 6.7 s clip.
  - The test-only store saved both rows, both WAVs and the merged file. The test data was then removed.
- The frontend builds and lint is clean. Earlier backend tests still pass: 27/27, 21/21, 13/13.

**Settings now in the owner's local `.env` files**
- `backend/.env`: `VOICE_STT_PROVIDER=groq`, `VOICE_STT_MODEL=whisper-large-v3-turbo`, and `VOICE_DEBUG_STORE=true` with the local `voice_test` URL.
- `frontend/.env` (was the root `.env` before the frontend/ move): `VITE_VOICE_TEST_TRANSCRIPT=true`.
- Restart `npm run dev` so Vite picks up the new variable.

**Phones need HTTPS** for the mic. `localhost` works on the laptop, but a phone on the LAN needs an HTTPS URL. That is the same "change the backend URL" checklist as before.

#### Step 1b notes (13 Nov 2026, branch `voice-step1b`)

**Status: DONE on desktop Chrome (13 Nov 2026).** Built and tested by script, live with real Groq and Sarvam, and in Chrome with a recorded clip fed in as the microphone. Not yet tried on a phone (Android Chrome, iPhone Safari over HTTPS) or listened to by a person.

**What it does:** after each recording the app speaks an echo: `"Aapne kaha: " + transcript`. If nothing was heard, it says "Mujhe kuch sunai nahi diya, phir se boliye." Step 2 replaces the echo with the agent's answer.

**How it's built**
- **Backend:**
  - `voice/tts.py` calls Sarvam bulbul:v3 through `tts_service.synthesize_speech_sarvam` and returns WAV at 22,050 Hz.
  - Language: `hi`/`ur` → `hi-IN`, `en` → `en-IN`, anything else → `hi-IN`.
  - Settings: `VOICE_TTS_SPEAKER` (default `ritu`) and `VOICE_TTS_ENABLED` (default true).
- **Message order:**
  - The `transcript` message still goes out as soon as speech-to-text finishes.
  - Then `{"type":"reply", turn_id, reply_text, reply_audio_base64 | null, mime, tts_ms}`.
  - If TTS fails: a `reply` with no audio, then the error `tts_failed` ("Couldn't play the reply."). The socket stays open.
- **Privacy:**
  - `synthesize_speech_sarvam` got `use_cache=False`, which voice uses. Otherwise the user's words would be cached in Redis under `audio:text:*`.
  - Its error log no longer prints Sarvam's response body, which can echo the text.
  - The voice logs record `tts_ms` and status only.
- **Test-only store:** `voice_speeches` gets `reply_text` and `tts_time_ms`, added to existing tables with `ALTER TABLE … ADD COLUMN IF NOT EXISTS` at startup. The reply audio is never saved.
- **Frontend:**
  - `frontend/src/voice/replyPlayer.ts` uses one playback AudioContext. It's created and resumed inside the mic tap, before any `await`, and unlocked with a silent buffer, so iPhone Safari lets the reply play seconds later.
  - Replies are played with `decodeAudioData` and an `AudioBufferSourceNode`.
  - The mic has a new `speaking` state: green with a sound wave, labelled "Speaking. Tap to interrupt."
  - **Barge-in:** tapping while it speaks stops the reply and starts recording. Starting a recording always stops playback, and so do logout and unmount.
  - The reply timer now covers speech-to-text plus TTS: 30 s with no `reply` means an error.
  - The test panel shows the reply text, "TTS … ms" and "total … ms" (second tap → sound starts).

**Tested**
- `backend/tests/test_voice_step1b.py`, **23/23**, with Groq and Sarvam simulated:
  - language mapping, the echo and the empty-transcript reply
  - message order and shape
  - the Sarvam request: `hi-IN`/`en-IN`, `ritu`, `bulbul:v3`
  - TTS failure: a reply with no audio plus `tts_failed`, and the next turn still works
  - `VOICE_TTS_ENABLED=false` and `VOICE_TTS_SPEAKER`
  - **no `audio:text:*` keys written**, while other callers still cache
  - the test-only store adds the new columns to an old table and saves `reply_text`/`tts_time_ms`
- All other backend tests still pass:
  - the rate limiter
  - `test_step0` 27/27
  - `test_ownership` 21/21
  - `test_step0e` 13/13
  - `test_voice_step1` 31/31, now run with `VOICE_TTS_ENABLED=false`

  `test_step0` now ignores the local itinerary cache, because a real cached itinerary had replaced the mock one it expects.
- **Live through the running server** (real Groq + Sarvam, 8 clips made with Windows' English voices, 4 English and 4 romanized Hinglish):
  - Every clip got reply audio: 22,050 Hz WAV, 2.8–3.9 s long.
  - **Average Groq speech-to-text 745 ms, Sarvam TTS 1,310 ms, second tap → reply received 2,081 ms.**
  - **No new `audio:text:*` keys in Redis.**
  - The test-only store saved `reply_text` and `tts_time_ms` on all 8 rows.
- **Chrome** (desktop 1440 px and 393 px, a clip fed in as the mic): **14/14**.
  - The reply plays: the mic shows the speaking state and the wave, then goes back to idle.
  - The panel shows the reply, TTS ms and total.
  - Barge-in stops the reply and starts recording.
  - **Second tap → sound started: 2.3–3.3 s** (TTS 1.7–2.3 s in those runs).
- Frontend build passes and lint has no errors.

**Problems found**
- **Romanized Hinglish is detected as English.** Groq Whisper labelled all four Hinglish clips `en`, so the reply was spoken with the `en-IN` voice. That includes the Hindi words and the "Aapne kaha" prefix, which likely sounds anglicised.
  - Real Hindi speech should come back as `hi` (Devanagari), but this wasn't tested: Windows has no Hindi voice.
  - To decide before step 2:
    - always reply in `hi-IN` for Hinglish, or
    - have the agent (step 2) write its reply in Devanagari, which Sarvam's `hi-IN` voice pronounces natively.
- **Speed:** Sarvam takes about 1.3 s per short reply, so second tap → sound is about 2.1–3.3 s, at the edge of the ~3 s target. Step 2 adds the agent call on top. Options to look at: a shorter echo, Sarvam streaming, or starting TTS while the agent is still answering.
- **The test clips aren't real speech.** The Windows voices mangle Hinglish, for example "Kanakahan Acha Milaga" for "Khana kahan acha milega". Real accuracy and how natural the voice sounds need the owner's own voice and ears.

**Still needs the owner**
- Phones over HTTPS: Android Chrome and iPhone Safari. The iPhone autoplay unlock is built but not tested on a real iPhone.
- Hindi, Hinglish and English said by a person: does the ritu voice sound natural?
- Remove `SARVAM_API_KEY` and restart the backend. The transcript should still show, the panel should say "Couldn't play the reply.", and the next recording should still work. This is covered by the test with a simulated failure, not tried live.
- About 10 of your own clips for the timing table.

#### Step 2 notes (13 Nov 2026, local branch `voice-step2`, not pushed)

**Status: built, waiting for the owner's test. Not done.** The step 1b echo is replaced by the agent. Each turn: mic → `/ws/voice` → Groq Whisper (transcript) → the agent decides → the backend checks the decision → the app navigates → Sarvam speaks a short reply.

**How it's built**
- `backend/groq_client.py`: `groq_chat_tools()` sends `tools` and `tool_choice`, accepts `finish_reason` "stop" or "tool_calls", and returns `{content, tool_calls: [{name, arguments}]}`.
  - Bad argument JSON raises `GroqError`.
  - Errors carry the status code only, never the response body.
  - `groq_chat()` is unchanged.
- `backend/voice/pages.py`: the only map from page names to routes.
  - `NEEDS_TRIP = {trip, itinerary}`; `day` is only for the itinerary, 1–30.
  - `resolve()` returns the route or `unknown_page` / `no_trip` / `bad_day`.
  - Confirm sentences for every page, in Hinglish and English.
- `backend/voice/agent.py`: one Groq call per turn, with the system prompt as specified and one tool, `navigate`. The decision is checked with `pages.resolve`:
  - **OK:** the confirm sentence plus `ui_actions: [{type: navigate, to}]`. There's no second LLM call.
  - **`no_trip`:** "Abhi koi trip khuli nahi hai…" and a jump to `/trips`.
  - **Unknown page or bad day:** "Kaunsa page kholun?"
  - **No tool called:** the model's text, trimmed to 2 sentences.
  - **Groq error:** "Abhi samajh nahi paaya, phir se boliye."
  - Template language follows the STT language: `en` → English, everything else → Hinglish.
  - **Memory:** Redis `voice:mem:{user}:{conversation}`, the last 10 turns, 30-minute expiry refreshed each turn, deleted on `end_session`.
  - Logs carry only the action, `llm_ms` and an error code. Never the words.
- **Trip context:** `start` carries `trip_id`. The server checks it with `ownership.find_owned_trip`; another user's trip, or a missing one, counts as "none". Only the title and dates go into the prompt.
- **`reply` message:** gains `ui_actions`, `action` (`navigate:<page>` | `reply` | `error`) and `llm_ms`. An empty transcript gets a fixed reply with no LLM call.
- **Test-only store:** new columns `agent_action` and `llm_time_ms`, added to existing tables with `ALTER TABLE … ADD COLUMN IF NOT EXISTS`.
- **Frontend:**
  - `frontend/src/voice/uiActions.ts` runs only `navigate`, and only to routes in an allowlist that mirrors `pages.py`, plus `?day=1–30` on `/trip/itinerary`. Anything else is ignored with a console warning.
  - `MicButton` sends `trip_id`, runs `ui_actions` first and then plays the reply. Everything from step 1b is kept.
  - `ItineraryView` selects the day given by `?day=N`.
  - The test panel shows "→ navigate itinerary · day 2" and "LLM … ms".

**Tested**
- `backend/tests/test_voice_step2.py`: **49/49**, with Groq simulated at the HTTP level. All other backend tests still pass:
  - the rate limiter
  - step 0: 27/27
  - ownership: 21/21
  - step 0e: 13/13
  - voice step 1: 31/31
  - voice step 1b: 22/22, now with a stand-in agent that echoes
- Frontend: the build passes, lint has no errors, and the route allowlist passes 14/14 checks.
- **Eval** (`python -m scripts.eval_navigation`, 32 typed phrases, real Groq): **29/32 = 91%** on two runs. Average `llm_ms` was 731 and 910.
  - Misses: "nayi trip banani hai" and "plan a new trip" ask for destination and dates instead of opening `/trips/new`. "settings kholo" asked "which setting?" in one of the two runs.
  - Likely fix: one line of meaning per page in the tool (for example "plan_trip: start planning a new trip; more: settings and profile"). Not done, because the tool definition was to be kept exactly as given.
- **Live through the running server** (recorded clips, real Groq + Sarvam):
  - "Show me good places to eat near Hawa Mahal" → `/food`.
  - "Open my itinerary for day 2" with no trip → `/trips` and the no-trip reply.
  - A Hinglish trip request got one transient Groq error, which produced the fallback reply; on retry it asked a short question.
  - Second tap → reply received was about 2.3–2.7 s.
  - No `audio:text:*` keys were written.

**Open items for later**
- **Speech-to-text:**
  - Place names come out wrong (for example Varanasi).
  - Language detection is sometimes wrong, for example Icelandic for Hindi/Hinglish speech.
  - Romanized Hinglish is tagged `en`, so it gets English confirm sentences and the `en-IN` voice.
- **Occasional Groq errors:** they reach the fallback reply. If they're frequent, retry once on Groq's 400 "tool_use_failed".
- **Speed:** the agent adds about 0.5–1 s per turn.

### Step 1c in detail: hearing better (can run any time)

**Goal:** fix the speech-to-text problems found in testing on 13 Nov, and add Wispr Flow as a provider for the hackathon. This doesn't change how the agent works; it gives the agent better text.

**What testing showed** (25 real clips, owner's voice, Groq Whisper):

| Problem | Example | How bad |
| --- | --- | --- |
| Wrong language detected | 3 clips tagged **Icelandic**: "Það er hann" for Hinglish | The whole sentence is lost |
| Indian place names | Varanasi → "Bara Nasi", "Vajara si", "Badaanasi", "**12 nati**"; Jaipur → "Jajapur"; Thiruvananthapuram → "तिलू बननत पूरम"; Delhi → "Gildi"; Bombay → "पॉंबे" | Frequent |
| English words inside Hindi | "agle Friday" → "अगले प्राइटे"; "itinerary page" → "आइटिरी पेज़े" | Sometimes |
| Romanized Hinglish tagged `en` | All Hinglish clips in 1b → English confirm lines and the `en-IN` voice | Every Hinglish turn |
| Fine | navigation commands, food, haan/nahi, "bees/pachaas hazaar", "teen/paanch din", "kal subah", "Diwali ke baad" | — |

Devanagari vs Roman script is **not** a problem: the user never sees the transcript and the agent reads both.

**Fixes**

1. **Language retry** (`voice/stt.py`):
   - If Whisper detects anything other than `hi`, `en` or `ur`, run the same audio again with `language="hi"`.
   - Treat `ur` as `hi`.
   - The retry costs one extra call, and only on bad clips.
2. **Vocabulary hint:** a `prompt` (≤ 224 tokens) with about 40 Indian city and place names, the weekdays and app words. Set it in `VOICE_STT_PROMPT`, already supported. Example:
   *"Varanasi, Jaipur, Mumbai, Bombay, Delhi, Goa, Kolkata, Bengaluru, Chennai, Hyderabad, Thiruvananthapuram, Puducherry, Udaipur, Rishikesh, Manali, Shimla, Amritsar, Agra, Hawa Mahal, Amber Fort… Monday, Friday. Mujhe kal Jaipur jaana hai, budget 20 hazaar, itinerary dikhao."*
3. **Place aliases** (`backend/place_aliases.py`), used by every tool that takes a place:
   - Bombay → Mumbai, Calcutta → Kolkata, Bangalore → Bengaluru, Banaras/Benares → Varanasi, Madras → Chennai, Trivandrum → Thiruvananthapuram, Pondicherry → Puducherry, Gurgaon → Gurugram.
   - Then a fuzzy match against the place search (India only) resolves garbled names like "Badaanasi" and "वारा नसी".
4. **Reply voice language:** Sarvam's `hi-IN` voice reads code-mixed Hindi and English well, so use `hi-IN` for every reply, unless both the transcript and the reply are plain English (no Hindi words). The owner listens and decides.
5. **Wispr Flow provider** (`voice/stt.py`, `VOICE_STT_PROVIDER=wispr`), for the hackathon:
   - **REST first:** on `stop`, WAV → base64 → `POST https://platform-api.wisprflow.ai/api/v1/dash/api` with `Authorization: Bearer <WISPR_API_KEY>`. Read `text`, `detected_language` and `total_time`.
   - **WebSocket later** (faster):
     - open `wss://platform-api.wisprflow.ai/api/v1/dash/ws` at `start`;
     - send the `auth` message;
     - regroup the 100 ms PCM frames into 1-second packets (with a volume value), sent as `append`;
     - send `commit` on `stop`.
   - **Context:**
     - `language: ["hi","en"]`;
     - `dictionary_context` with city names, the trip's destination and saved places;
     - `app: {type: "ai"}`;
     - the last few turns as `conversation`.
   - **Fallback:** if Wispr fails, use Groq for that turn.
   - **Access:** the API is approval-only. Get the key from the hackathon organisers.
6. **Re-score script** (`backend/scripts/rescore_stt.py`):
   - Re-transcribes every saved WAV in `test_audio_folder/` with each setting: prompt off/on, language auto/`hi`, Groq/Wispr/Sarvam.
   - Prints them side by side, with the time each took.
   - Needs `VOICE_DEBUG_STORE` recordings and runs locally only.

**Done when**
- [ ] No clip in the saved set comes back as a language other than Hindi, English or Urdu.
- [ ] Of the place names in the saved set, at least 80% are recognised or resolved by the alias and fuzzy match. Today about 40% are.
- [ ] `rescore_stt.py` comparison table for Groq vs Wispr Flow (vs Sarvam if a key is available), pasted into the Step 1c notes.
- [ ] Owner listens: `hi-IN` voice on Hinglish replies sounds right.
- [ ] Wispr Flow works end to end with `VOICE_STT_PROVIDER=wispr`, and falls back to Groq when it fails.

---

### Step 3 in detail: questions and look-ups

**Goal:** the user can ask travel questions and look things up by voice. Nothing changes any data in this step.

| User says | What happens |
| --- | --- |
| "Amber Fort kab jaana best hai?" | Short spoken answer (≤ 2 sentences); the full answer appears in the Guide chat |
| "Hawa Mahal dikhao" / "where is Amber Fort" | Map opens and flies to it, with a pin and "X km from you" |
| "Meri trips kaun si hain?" | "Aapki 2 trips hain: Jaipur 14 Nov se aur Goa 20 Dec se." My trips opens |
| "Goa wali trip kholo" | That trip becomes the current trip; the trip page opens |
| "Goa wali trip kholo" with two Goa trips | "Goa ki do trips hain: November wali ya December wali?" |
| "Nayi trip banani hai" | Opens the new-trip form. Fixes step 2's eval miss: plain navigation, no questions |

**Tools added to `voice/agent.py`**

| Tool | Arguments | Backend does |
| --- | --- | --- |
| `answer_question` | `question` (the user's question, cleaned up), `place?` | Calls the tour guide (Gemini with Google Search) in **voice mode**: answer in ≤ 2 short sentences in the user's language. Also saves the full answer in the user's Guide chat history (`tour_guide_service.persist_message`), so it's readable later. If Gemini fails, Groq answers with a note that details may vary. |
| `search_places` | `query` | Existing `search_places` (India only) + the aliases from step 1c. Top result → `ui_actions: [{type: "map_focus", lat, lng, name, place_id}]`. Several close matches → asks which one. None → "Yeh jagah nahi mili." |
| `list_my_trips` | — | The user's trips (closed ones skipped unless asked for "purani trips"). Reply lists up to 3 by destination and start date, then navigates to `/trips`. |
| `open_trip` | `destination?`, `month?`, `which?` (`next`/`current`/`last`) | Matches the user's own trips in code. One match → `ui_actions: [{type: "open_trip", trip_id}, {type: "navigate", to: "/trip"}]`. Several → asks with month names. None → "Is naam ki koi trip nahi mili." |

**Changes to the system prompt and tools**
- Every page in `navigate` gets a one-line meaning in the tool description, e.g. `plan_trip: open the new trip form (do not ask for details)`, `more: settings, profile, language`. This fixes the step 2 misses.
- Add to the prompt:
  - "For questions about places, timings, tickets, food or travel tips, call answer_question. Do not answer from memory."
  - "Use search_places when the user wants to see where a place is."
- Today's date (India) goes into the prompt, so "kal" and "is weekend" make sense.

**Backend files**
- `voice/tools/lookups.py`: `answer_question`, `search_places`, `list_my_trips`, `open_trip`.
- `tour_guide_service.py`: add a short `voice_answer(question, user_id, trip, lang)`. It reuses the existing Gemini grounded model with a "max 2 sentences, spoken" instruction and a 6 s timeout.
- The `reply` message: `action` becomes `answer`, `map_focus:<name>`, `list_trips` or `open_trip`.

**Frontend**
- `uiActions.ts`:
  - `map_focus`: navigate to `/map` and set `mapFocusTarget` (already used by the map search from Step 0e), so the card shows the distance.
  - `open_trip`: set the current trip in `TripContext` (only an ID from the user's own trip list), then navigate.
- Guide page: answers asked by voice show in the chat history with a small mic icon.

**Tests** (`backend/tests/test_voice_step3.py`, Groq and Gemini simulated)
- Each tool's backend checks.
- `open_trip` only finds the user's own trips; two matches → a question.
- `search_places` outside India → nothing.
- The answer is trimmed to 2 sentences; a Gemini failure falls back to Groq.
- The full answer is saved to the Guide history and the short one is spoken.
- No user words in logs.

**Eval** (`backend/scripts/eval_lookups.py`, real Groq, ~30 phrases)
- Expected tool and arguments for each phrase, including:
  - "Amber Fort ki timing kya hai", "Jaipur mein kya khana famous hai";
  - "Hawa Mahal dikhao", "show me Gateway of India";
  - "meri trips", "Goa wali trip kholo", "agli trip kholo";
  - "nayi trip banani hai", "settings kholo".
- Also: "ek joke sunao" (decline), and a weather question (`answer_question`).
- Target ≥ 90%. Step 2's navigation eval must still pass.

**Done when**
- [ ] Both evals ≥ 90%.
- [ ] By voice: 5 travel questions get correct, short answers. The full answer is in the Guide chat.
- [ ] "Hawa Mahal dikhao" pins it on the map with the distance.
- [ ] "Goa wali trip kholo" works with one and with two Goa trips.
- [ ] Second tap → answer heard ≤ 4 s for questions (Gemini adds time), ≤ 3 s for the rest.

---

### Step 4 in detail: create a trip by voice

**Goal:** the full conversation from section 6. The user speaks, the server collects the details, reads the date back, and opens the review page already filled in. Nothing is saved until the user taps **Proceed** or says "haan" on that page.

This step also adds the two pieces later steps reuse: **pending actions** and the **Confirm card**.

**The draft** (`voice/draft.py`)
- Kept in Redis under `voice:draft:{user}:{conversation}` for 30 minutes. Deleted when the session ends or the user leaves midway (socket closes).
- Fields:

| Field | Required | Filled from |
| --- | --- | --- |
| `destination` | Yes | Speech → aliases (1c) → place search, India only. Ambiguous → asks |
| `origin` | No | Same as destination |
| `start_date` | Yes | The agent turns "agle Friday", "15 tareekh", "Diwali ke baad" into a date using today's India date in the prompt. Code checks: not in the past, ≤ 1 year ahead |
| `start_date_confirmed` | Yes | Set **only by code**, after the read-back ("14 November, Friday se, sahi hai?") gets a yes |
| `days` or `end_date` | Yes | 1–30 days |
| `adults` | Yes | ≥ 1 |
| `children` | Yes | ≥ 0 ("koi bachcha nahi" = 0) |
| `budget_amount` | Yes | Rupees. "bees hazaar" = 20000, "1.5 lakh" = 150000 |
| `travel_style` | No | From speech, else the user's saved preferences |

- **Code, not the LLM, decides what's missing:** `missing_fields(draft)` is passed to the agent each turn. The agent only phrases the question, at most 2 missing fields per question.

**Tools added**

| Tool | Arguments | Backend does |
| --- | --- | --- |
| `update_trip_draft` | any of the fields above | Checks and normalises each value, saves the draft, returns `missing_fields` and the next step (`ask`, `confirm_date` or `ready`) |
| `confirm_date` | `yes: bool` | Only valid right after the read-back. Yes → `start_date_confirmed`. No → clears the date and asks again |

**The jump**
- When nothing is missing and the date is confirmed, the reply is "Sab details check karke Proceed dabaiye.", with `ui_actions: [{type: "open_review", prefill: TripDraft}]`.
- The frontend opens `navigate('/trips/new', { state: { prefill } })`. The wizard already accepts this since Step 0c and shows its review step.
- **"Haan" on the review page:**
  - The agent calls `submit_review`, and the app presses Proceed itself: `{type: "submit_review"}`. It's only allowed while the review step is showing.
  - So **the values on the page, including any edits the user made by tap, are what get saved**, through the existing wizard path (`trips:create` → `create_trip_for_user`).
  - Voice never creates a trip from its own copy of the draft.

**Pending actions and the Confirm card** (`voice/pending.py`, used from step 5 on)
- A big tool doesn't run. It saves `{id, tool, arguments, summary}` in Redis as `voice:pending:{user}:{conversation}`, for 5 minutes.
- The reply carries `pending_confirmation: {id, summary}`, and the app shows `ConfirmCard.tsx` with **Confirm** and **Cancel**.
- **Confirm:**
  - by tap: `{"type":"confirm","pending_id"}` on `/ws/voice`;
  - by voice: "haan", "yes", "confirm", "kar do".
- **Cancel:** "nahi", "no", "cancel", "rehne do", a new topic, or 5 minutes passing.
- **Clear yes/no words are matched in code first,** with no LLM call, for speed. Anything else goes to the agent with the pending action in its prompt.
- **Only the confirm handler runs the real function,** after checking ownership again. The agent cannot run it.

**After creation**
- The trip is created and the itinerary is queued (existing flow).
- When `ITINERARY_READY` arrives on `/ws/app`, the app speaks a fixed line through the existing TTS endpoint: "Aapka Jaipur plan ready hai. Itinerary kholun?" (caching is fine, since it isn't the user's words).
- "Haan" opens the itinerary.
- The existing visual notice stays.

**Frontend**
- `uiActions.ts`: `open_review`, `submit_review` (only on the wizard's review step).
- `ConfirmCard.tsx`: summary text, Confirm, Cancel; above the nav (`z-[var(--z-modal)]`, through `Portal`).
- `MicButton`: sends `screen = "/trips/new#review"` while the review step shows, so the agent knows "haan" means Proceed.

**Tests** (`test_voice_step4.py`)
- **Draft:** fields, normalisation (Hindi number words, past dates refused, 31 days refused), `missing_fields`, at most 2 questions per turn.
- **Date read-back:** the draft is never `ready` without confirmation.
- **Review page:** `open_review` carries the exact prefill shape; `submit_review` is only allowed on the review screen.
- **Pending:** saved, expires after 5 minutes, confirm runs once (a second confirm does nothing), cancel, a new topic cancels.
- **Ownership:** another user's pending ID is refused.
- **Clean up:** leaving midway deletes the draft.

**Eval** (`eval_create_trip.py`): about 10 scripted multi-turn conversations, typed:
- the section 6 example;
- everything said in one sentence;
- the date changed after the read-back;
- an unknown city;
- budget said as "1.5 lakh";
- "koi bachche nahi";
- changing the destination midway.

Each checks the final prefill. Target: all 10.

**Done when**
- [ ] The section 6 conversation works by voice, start to finish, on a phone.
- [ ] Nothing is created without Proceed or "haan" on the review page. Editing a field by tap and then saying "haan" saves the edited value.
- [ ] The date is always read back, and a wrong date can be corrected.
- [ ] The itinerary-ready line is spoken, and "haan" opens it.
- [ ] Eval 10/10. Earlier evals still pass.

---

### Step 5 in detail: more actions

**Goal:** everyday changes by voice, following the rules in section 1: small ones happen with Undo, big ones ask first, and voice never deletes.

**First, shared trip actions** (`backend/trip_actions.py`)
- Today, add expense, swap activity and mark done are written inline in `main.py`'s WebSocket handlers.
- Move them into functions: `add_expense(db, user, trip_id, ...)`, `swap_activity(...)`, `set_activity_done(...)`, `save_place(...)`, `unsave_place(...)`.
- Both `/ws/app` (taps) and the voice tools call these, so the rules exist once.
- The existing tap tests must still pass unchanged.

**Trip context for the agent** (`voice/context.py`): when a trip is open, the prompt gets a compact view:
- the days, with dates;
- the activities, with short IDs and names (today's day first);
- the total spent vs the budget.

That lets "Hawa Mahal wala mark done karo" become an activity ID. The ID is matched by **code** against the trip's own activities, never trusted from the LLM.

**Tools added**

| Tool | Kind | Arguments | Backend does |
| --- | --- | --- | --- |
| `mark_activity_done` | Small | `activity`, `done` (default true) | Runs now. Reply "Hawa Mahal done mark kar diya." Undo toast → `trips:set_activity_done` with `done=false` |
| `save_place` / `unsave_place` | Small | `place` (from the screen, or the last `search_places` result) | Runs now. Undo toast reverses it |
| `set_filter` | Small | `page` (`food`, `explore`), `filter` (e.g. `veg`, `open_now`) | Frontend-only: `ui_actions: [{type: "set_filter", ...}]`; Undo restores the previous filter |
| `add_expense` | Big | `title`, `amount`, `category` (food, transport, stay, shopping, tickets, other) | Pending: "₹350, auto, transport mein add karun?" → on confirm runs `trip_actions.add_expense` |
| `swap_activity` | Big | `activity`, `reason?` | Opens the existing swap sheet for that activity with options (`ui_actions: [{type: "open_swap", activity_id}]`). The user picks by tap, or by voice ("doosra wala"), and the sheet's own Confirm applies it |
| `regenerate_itinerary` | Big | — | Pending: "Poora itinerary dobara banaun? Isme thoda time lagega." → on confirm queues regeneration (AI rate limit bucket) |
| delete | Not a tool | — | The prompt says: never delete. Reply "Trip delete karne ke liye button khud dabaiye, dhyan se." + navigate to `/trip` |

**After any change:** `ui_actions` also carries `{type: "refresh", what: "itinerary" | "expenses" | "saved_places"}`, so the open screen reloads data that changed through `/ws/voice`.

**Undo** (`ui_actions: [{type: "undo_toast", message, undo: {action, payload}}]`)
- The Undo button runs the reverse through the existing `/ws/app` action, from an allowlist: `trips:set_activity_done`, saved-places add/delete, filter restore.
- It's shown for 5 seconds. Undo is by tap only, as decided.

**Tests** (`test_voice_step5.py`)
- `trip_actions` used by both paths; the old tap tests unchanged.
- An activity name matches only the user's own trip; an unknown name → a question.
- Small actions run with an Undo payload; Undo reverses them.
- Big actions never run without confirm; confirm runs once.
- Another user's trip or activity is refused at every point.
- "Delete my trip" never deletes.
- `refresh` is sent after each change.

**Eval** (`eval_actions.py`, ~30 phrases)
- "Hawa Mahal done ho gaya", "auto ka 350 add karo", "khane ka 1200 kharcha", "Amber Fort ki jagah kuch aur";
- "plan dobara banao", "yeh jagah save karo", "veg wale dikhao", "meri trip delete karo";
- plus earlier phrases, to make sure nothing regressed.

**Done when**
- [ ] Each action behaves as in the table, by voice, on a phone.
- [ ] Undo works for every small action.
- [ ] Big actions never happen without "haan" or Confirm.
- [ ] Delete only redirects.
- [ ] The screen updates after each change without a reload.
- [ ] All evals ≥ 90%. All earlier tests pass.

---

### Step 6 in detail: smart actions

**Goal:** the three AI helpers that already work by tap, now by voice:

| User says | Tool | Before asking |
| --- | --- | --- |
| "Aaj baarish hai, plan badlo" / "kal ka plan mausam ke hisaab se karo" | `weather_replan(day?)` | Reads the real forecast first (`weather_service`, read-only). No bad weather → "Kal mausam theek hai, plan badalne ki zaroorat nahi." and nothing else happens. Bad weather → pending: "Kal dopahar baarish ka forecast hai. Outdoor jagahon ki jagah indoor rakh doon?" More than 16 days away → "Itni door ka forecast abhi nahi hai." |
| "Aaj ka route chhota karo" / "day 2 optimize karo" | `optimize_day(day, goal?)` | `goal`: `MINIMIZE_TRAVEL_TIME` (default), `RELAXED`, `MORE_SIGHTS`. Pending: "Day 2 ka order travel kam karne ke liye badal doon?" |
| "Budget mein fit karo" / "kharcha kam karo" | `optimize_budget()` | Needs a budget amount on the trip; if missing → "Pehle budget batayein, kitna hai?" (and saves it through `trip_actions`). Pending: "Plan ko ₹45,000 ke andar laane ki koshish karoon?" |

**How**
- `day` is resolved in code: "aaj" and "kal" from the trip's dates (India date), "day 2" / "doosra din" from the number. A day outside the trip → a question.
- On confirm, the existing services run: `weather_replan_service`, `optimize_day_flow_service`, `optimize_budget_service`. Ownership is checked again, and the AI rate-limit bucket applies.
- These take several seconds. The reply says so at once ("Plan badal raha hoon, ek minute…"); a second spoken line comes when the service returns.
- **The result is spoken as a one-sentence summary** built from the service's return value, e.g. "Day 2 mein 2 jagah badli: Amber Fort subah, City Palace dopahar." Then `refresh: itinerary`, and the itinerary opens on that day.
- If the service fails, the reply is "Abhi plan badal nahi paaya, thodi der mein try karein." Nothing is half-applied, because the services already run in one database transaction. Check this, and fix it if not.

**Tests** (`test_voice_step6.py`)
- The forecast is read before asking.
- No bad weather → no pending action.
- Far-off trips handled.
- "aaj/kal/day 2" resolution; a day outside the trip → a question.
- Budget missing → asks for it first.
- Confirm runs the service once, on the user's own trip only.
- A service failure leaves the trip unchanged.
- The summary sentence is built from the result.

**Eval** (`eval_smart.py`, ~20 phrases, real Groq; the services are simulated in eval).

**Done when**
- [ ] All three work by voice on the user's own trip, only after confirmation, and say what changed.
- [ ] With good weather, nothing is changed and the user is told why.
- [ ] Evals ≥ 90%. All earlier tests pass.

---

### Step 7 in detail: polish

**Goal:** make it fast, reliable and ready for real users and the hackathon demo.

**Speed** (target: second tap → reply heard ≤ 3 s on a phone; today ~2.3–3.3 s on desktop):
- **Measure first:** the test panel and the debug store already have `stt_ms`, `llm_ms` and `tts_ms`. Make a table for 20 clips on a phone.
- **Shorter replies:** fixed confirm sentences are already templates. Keep model replies to ≤ 2 sentences.
- **Cache fixed lines:** template replies ("Map khol diya.") contain no user words, so their audio can be cached in Redis. Only free-form replies stay uncached.
- **Sarvam streaming,** if available on the plan: start playing before the whole reply is synthesised.
- **Overlap:** for template replies, start TTS as soon as the tool is chosen, while the backend checks run.
- **STT:** the Wispr Flow WebSocket (step 1c) transcribes while the user speaks.

**Errors:** one table in `messages.py` of every error, its spoken line and what the app shows:
- no internet, socket dropped (auto-reconnect), login expired;
- mic blocked (show how to allow it), too short;
- Groq, Sarvam or Wispr down, rate limited (15/min, 100/day: "Thodi der baad try karein").

Each is spoken if possible, otherwise shown, and a test covers each.

**Voice choice**
- A setting in **More → Voice**: `ritu`, `priya`, `rahul` or `aditya` (Sarvam speakers), with a "Play sample" button.
- Saved in user preferences on the server, not the browser, and sent with `start`.

**Barge-in and interruptions**
- Tapping during a reply stops it (built in 1b). Add: a phone call or the app going to the background stops playback and recording.
- Pending actions survive a barge-in, until 5 minutes or a new topic.

**Phones and accessibility**
- Full test on Android Chrome and iPhone Safari over HTTPS: the iPhone autoplay unlock, the mic permission flow, landscape, 320 px wide.
- The mic button has a clear label in each state. The Confirm card works with screen readers.
- Respect the system "reduce motion" setting for the animations.

**Ready for real users**
- `VITE_VOICE_TEST_TRANSCRIPT=false` in production. The panel's code can stay behind the flag.
- `VOICE_DEBUG_STORE` must be off on the cloud server, and the server refuses to start with it on and a non-local URL. That second check is already built.
- The Groq paid tier (the free tier is shared by all users: ~15–20 turns per minute), and Sarvam credits.
- A per-user daily voice limit stays: 100 turns.

**Hackathon demo**
- A 2-minute scripted demo, as a sequence:
  1. Create a trip in Hinglish.
  2. Review page and Proceed.
  3. Itinerary ready (spoken).
  4. "Day 2 dikhao".
  5. "Aaj baarish hai, plan badlo".
  6. "Auto ka 350 add karo".
  7. Undo.
- Recorded as a backup video.

**Done when**
- [ ] Second tap → reply heard ≤ 3 s for 80% of 20 phone clips.
- [ ] Every error in the table tested and understandable.
- [ ] Voice choice saved per user and used on the next reply.
- [ ] Android and iPhone full pass.
- [ ] Production settings checked.
- [ ] Demo script runs cleanly three times in a row.

---

### Later (not scheduled)

- **`add_stay`, `add_transport`:** big actions, asking first. Need hotel or transport details by voice: name, dates, price.
- **`refine`:** free-form changes ("thoda relaxed kar do"). It uses `execute_refinement_actions_service`, and the user needs to see the changes before confirming. Probably a preview screen.
- **Road distance and travel time** on the map (Google Routes API, paid per call).
- **More languages:** Tamil, Bengali and others need the language set explicitly. Wispr Flow can't detect some of them from speech alone.

## 9. Cost, speed and safety

While testing, the only paid part of a voice turn is the spoken reply: about 30 paise for a 100-character reply on Bulbul v3.

| Part | Provider | Cost while testing |
| --- | --- | --- |
| Speech to text | Groq Whisper | Free: 20 requests/min, 2,000/day ([limits](https://www.grizzlypeaksoftware.com/articles/p/groq-api-free-tier-limits-in-2026-what-you-actually-get-uwysd6mb)) |
| Agent, 1–2 calls | Groq `gpt-oss-120b` | Free: 30 requests/min, 1,000/day, 8K tokens/min ([limits](https://www.developersdigest.tech/models/free-api/groq)) |
| Spoken reply | Sarvam Bulbul v3 | ₹30 per 10,000 characters; v2 is ₹15 ([pricing](https://sarvam.ai/api-pricing)); repeated lines are cached in Redis |

**Capacity:** Groq's free limits apply to the whole account, not per user. All users together get roughly 15–20 voice turns per minute, shared with itinerary generation. That's accepted for testing; the paid tier comes before real users.

**Limits per user:** 15 voice turns per minute and 100 per day.

**Speed target:** under ~3 seconds from the second tap to hearing the reply. Sarvam TTS is likely the slowest part; measure it in step 1.

**Safety:**

- Every tool runs as the logged-in user and passes the ownership check (after Step 0a).
- Big actions need confirmation, enforced on the server.
- Voice cannot delete trips.
- Audio is never stored.
- The developer transcript is shown live and never saved.
- Logs keep tool names and outcomes, not the user's words.

## 10. Decisions

All open questions from the first plan are closed. The only item left for later is letting users choose the reply voice.

| # | Question | Decision |
| --- | --- | --- |
| D1 | Languages | Hindi, English, Hinglish; reply in the language the user spoke |
| D2 | How the mic listens | Tap to start, tap to stop, 30-second cap; tapping during a reply interrupts it |
| D3 | Speech-to-text | Groq Whisper, swappable to Sarvam or xAI; compare on ~20 real Hinglish clips before launch |
| D4 | What counts as "yes" | Voice "haan"/"yes" or tapping Proceed/Confirm |
| D5 | Off-topic requests | The agent declines calmly; no cost-guard call |
| D6 | Store recordings | Never |
| D7 | Delete by voice | Not allowed; opens the trip and says the user must delete it themselves, at their own risk |
| D8 | Agent model | Groq (`gpt-oss-120b`); the whole app moves from Gemini to Groq except tour guide chat |
| D9 | Reply voice | `ritu` for now; users choose a voice in settings later (step 7) |
| Q1 | Voice before login | No, mic only after login |
| Q2 | Transport from starting city | The AI suggests transport that fits the budget (Step 0c) |
| Q3 | App speaks on its own | In-app notification when the itinerary is ready, offering to open the download page |
| Q4 | Screen while collecting | Listening/speaking animation, then the editable review page |
| – | Small actions | Run immediately, with an Undo toast (tap only) |
| – | Add expense | Asks for confirmation |
| – | Budget | Required by voice; amount saved, level worked out automatically |
| – | Travellers | Adults and children, always asked |
| – | Dates | The agent works out "agle Friday" and says the exact date back for confirmation |
| – | Leaving midway | Draft thrown away |

## Sources

- [Sarvam AI API pricing](https://sarvam.ai/api-pricing)
- [Sarvam pricing (docs)](https://docs.sarvam.ai/api/getting-started/pricing)
- [Groq API free tier limits 2026](https://www.grizzlypeaksoftware.com/articles/p/groq-api-free-tier-limits-in-2026-what-you-actually-get-uwysd6mb)
- [Groq free models and limits](https://www.developersdigest.tech/models/free-api/groq)
- [Groq free tier is per organization](https://klymentiev.com/blog/groq-api-free-tier)
- [xAI speech-to-text docs](https://docs.x.ai/developers/model-capabilities/audio/voice)