# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

VoyageAI (also called "Cruiser" in Docker/infra names): an AI travel companion. The repo root is the React/Vite frontend; `backend/` is a FastAPI service. The README's "Frontend Setup" refers to a `frontend/` dir that does not exist, so run frontend commands from the repo root.

## Commands

Frontend (repo root):
```sh
npm run dev       # Vite dev server on :5173
npm run build     # tsc -b && vite build. This is the only type check, there is no separate typecheck script
npm run lint      # oxlint (config: .oxlintrc.json)
```
The frontend has no test suite.

Backend (run from `backend/`, needs Postgres + Redis reachable):
```sh
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 80     # API + /docs (test mode runs on port 80)
python worker.py                                       # Redis queue worker; required for itinerary generation
python test_rate_limiter.py                            # standalone async script (not pytest); hits a live Redis
python init_neon_schema.py                             # schema init + session isolation check against DATABASE_URL
python create_subscription_tables.py                   # idempotent create/seed of the 8 subscription/payment tables
```
`backend/COST_GUARD.md` lists `test_cost_guard_contract.py` and `test_cost_guard_matrix.py`, but those files are not in the repo.

Docker: `docker-compose up` starts postgres (5432), the backend (host 5247 → 8000) and the frontend served by nginx (5248). Compose does not start Redis or the worker. See `DOCKER_DEPLOYMENT.md`. The frontend is also deployed to Netlify (`netlify.toml`, SPA catch-all redirect).

## Backend URL (test mode: everything on http://localhost:80)

ngrok is no longer used. The frontend dev server runs on :5173, and the backend on `http://localhost:80` (HTTP and `ws://localhost:80/ws/app`). When the user asks to change the backend URL, update **all** of these together:
1. `.env` (repo root): `VITE_API_URL`, `VITE_API_BASE_URL`, `VITE_WS_URL` (ws:// or wss://).
2. `src/config/apiConfig.ts`: `DEFAULT_BACKEND_URL`.
3. `vite.config.ts`: the `/api` and `/ws` proxy targets.
4. If the *frontend* moves to a new origin: add it to `ALLOWED_ORIGINS` in `backend/.env` (or `_DEFAULT_ALLOWED_ORIGINS` in `main.py`).
5. If a proxy or tunnel is put in front of the API: set `TRUSTED_PROXY_HOPS` in `backend/.env`.
6. The uvicorn `--port` in the commands above, and this section.
Restart `npm run dev` after editing `.env`; Vite reads it only at startup.

## Backend architecture

- **Two parallel APIs.** The frontend's main transport is one long-lived WebSocket (`/ws/app`, `src/services/wsClient.ts`). It sends RPC frames `{id, action, payload}`, and `process_ws_action` in `main.py` dispatches them by action name (`trips:create`, `trips:get_itinerary`, `tour_guide:chat`, `auth:login`, …). The connection loop (`websocket_tour_app_endpoint`) resolves the user from each frame's token once (`resolve_ws_session`), applies a per-action Redis rate limit (`WS_RATE_LIMITS`), and passes `session` into `process_ws_action`. Actions not in `WS_PUBLIC_ACTIONS` require login, and every action in `WS_TRIP_ACTIONS` has its `trip_id` ownership-checked and normalized before the branch runs. When adding a WS action, add it to these sets rather than doing auth inside the branch. REST (`/api/*`) is used for register/login/session, saved places, and as a fallback when a WS call fails. Most features are implemented separately in both paths, so a behaviour change usually has to be made in both.
- **`main.py` is a ~4.9k-line monolith** that holds nearly all HTTP and WebSocket routes. Many routes are registered under several aliases at once (for example `/trips` and `/api/trips`, or `/api/chat` and `/api/tour-guide/chat`). Keep the stacked decorators together when you edit a handler. The `*_service.py` modules hold the logic, and some are imported lazily inside handlers.
- **DB**: `database.py` has one pooled SQLAlchemy engine tuned for Neon serverless Postgres (pre_ping, recycle=300). Use `get_db` for routes and `get_db_context` elsewhere. Tables are created by `init_db()` at import time in `main.py`, using `Base.metadata.create_all`. There is no Alembic, so schema changes to existing tables need manual SQL or a script like `create_subscription_tables.py`. ORM models are split across `models*.py` and `payment_models.py`. They must be imported before `init_db()` so they register.
- **Async itinerary pipeline**: WS `trips:create` (or `POST /api/trips`) → `task_queue.enqueue_itinerary_generation` (Redis LPUSH on `voyageai:tasks:itinerary`) → `worker.py` (BRPOP) → `itinerary_service.process_async_itinerary_generation` → `publish_trip_event` (Pub/Sub `voyageai:events:trip`) → `events_listener` (started in the FastAPI lifespan, reconnects on Redis loss) → `connection_registry.push_to_user` sends `ITINERARY_READY` (status `READY` or `FAILED`) only to the trip owner's `/ws/app` sockets. If the worker is not running, itineraries never complete. Generated itineraries are cached in Redis for 7 days keyed by destination/days/styles/budget level (`itinerary_cache_service.py`) and copied into each trip; mock output is never cached.
- **Trip creation** lives in `trip_lifecycle.create_trip_for_user`. It handles:
  - validation, with a 30-day and 20-traveler limit
  - idempotency via `clientRequestId`
  - `adultsCount`/`childrenCount`
  - `budgetAmount`, saved as `budget.targetAmount`. `budget.level` is derived from it by `budget_level_for` (per person per day; a child counts as half).
  - an optional `origin` starting city, stored once in the `cities` table (`models_place.get_or_create_city`) and linked by `trips.origin_city_id`
  - queueing the itinerary job

  Both REST and WS call it, and so will the voice agent. Don't re-implement it in a handler. `serialize_trip(trip, db)` is the shared response shape.
- **Past trips close themselves on read:** `trip_lifecycle.close_finished_trips(db, trips)` sets open trips whose `end_date` is before today to `COMPLETED`. "Today" is `today_ist()`, the India date. It's called from `trips:list`, `GET /api/trips` and `GET /api/trips/{id}`, so there is no scheduled job. Call it from any new endpoint that lists or returns trips.
- **Itinerary generation** asks the AI for `transportSuggestions` when the trip has a starting city. They're saved as `trip_transports` rows with status `RECOMMENDED`, replaced on regenerate. The itinerary cache key includes the origin.
- **Schema additions without migrations:** new columns on existing tables must also be added as `ALTER TABLE … ADD COLUMN IF NOT EXISTS` in `database.init_db()`. `create_all` won't add them. Examples: `trips.origin_city_id`, `itinerary_activities.is_done`.
- **Weather** comes from `weather_service.get_trip_forecast` (Open-Meteo, no key, up to 16 days ahead). It raises `ForecastUnavailable` instead of inventing weather.
- **Ownership**: all "does this user own this trip/activity" checks go through `ownership.py` (`find_owned_trip`, `require_owned_trip`, `find_owned_activity`, …). They never fall back to another user's data. `verify_trip_ownership` in `main.py` wraps `require_owned_trip`; use the returned trip's `id` afterwards, since the frontend sends IDs with or without the `trip_` prefix.
- **`request.state.user`** only ever holds a full `AuthUser` (set by `get_current_user`). `UserRateLimiter` stores its key in `request.state.rate_limit_user_id` instead.
- **Redis has two clients**: a sync one in `redis_client.py` (queue/pubsub/cache, `REDIS_HOST`/`REDIS_PORT`) and an async one inside `rate_limiter.py` (`REDIS_URL`).
- **AI**: `ai_provider.py` defines `MockAIProvider`, `GeminiProvider` and `GroqProvider`. `GroqProvider` uses the same prompts; only the call goes through `groq_client.py`.
  - `AI_PROVIDER` (default `groq`) chooses the provider per call: `groq` means `FallbackAIProvider([Groq, Gemini])`; `gemini` and `mock` mean only that provider.
  - Call sites with their own prompt use `ai_provider.complete_json(prompt)`. Never call Gemini or Groq HTTP directly elsewhere.
  - `GROQ_API_KEY` and `GROQ_MODEL` (default `openai/gpt-oss-120b`) are in `backend/.env`. With no Groq key, calls quietly go to Gemini.
  - The cost guard follows the same order (`COST_GUARD_BACKEND=groq`: `GroqClassifier`, then `GeminiClassifier`) and still fails closed. Gemini errors are raised, never replaced with mock data: mock output (a Goa/Bihar dataset or a generic "{dest} Zone N" template) looks real to users and must only appear with `AI_PROVIDER=mock`. Add new AI capabilities to the interface and to both implementations. The tour-guide chat (`tour_guide_service.py`) calls Gemini through its own SDK/REST tiers, not through `ai_provider.py`.
- **Cost guard** (`cost_guard.py`, see `backend/COST_GUARD.md`): a fail-closed intent classifier (`travel/emergency/off_topic/unknown`) runs before any paid concierge answer. Keep the `(allowed, gate, reply)` return contract and the `PASSED_ESSENTIAL_NEED` emergency path. Never make it fail open. It guards `tour_guide:chat`/`/api/chat` and the free-chat path of `/api/ai/concierge`.
- **Rate limiting** (`rate_limiter.py`): Redis ZSET sliding window. `NetworkRateLimiter` keys on the client IP, normalized to /64 for IPv6. The IP comes from `client_ip_from`, which ignores `X-Forwarded-For` unless `TRUSTED_PROXY_HOPS` > 0 (default 0, because the API is reached directly). Behind a proxy, set it to the number of proxies, and only the entry that proxy appended is trusted. Login, register and paid-AI limiters use `fail_closed=True` (503 when Redis is down); the rest fail open. Tokens are never read from URL query strings on HTTP routes. `UserRateLimiter` keys on the session user and uses a cache-aside session lookup (`session_cache:{token}`), which is warmed on login and invalidated on logout. Routes attach the named limiter instances (`general_limiter`, `ai_limiter`, `ai_chat_limiter`, `places_limiter`, …) via `dependencies=[Depends(...)]`.
- Google Maps calls live in `services/google_maps_service.py`; the tour guide in top-level `tour_guide_service.py`.

## Auth model

`auth.py` handles sessions. The server issues a random token and stores only `SHA-256(token)` in `sessions.token_hash`. The client carries the token in the `voyageai_session` HttpOnly cookie (7 days, SameSite=Lax), with `Authorization: Bearer` / `X-Auth-Token` as a fallback. `cookie_flags()` in `main.py` sets Secure + SameSite=None over HTTPS and SameSite=Lax without Secure over plain HTTP (localhost). User identity must always come from the session, never from a `user_id` query or body param. Accounts are created only by `/api/auth/register`; `auth.authenticate_user` always requires the password and never creates users. CORS allows only `_DEFAULT_ALLOWED_ORIGINS` in `main.py` plus the comma-separated `ALLOWED_ORIGINS` env var (add a new frontend URL there). The global exception handler adds CORS headers only for those origins and does not return exception text.

## Frontend architecture

- `src/config/apiConfig.ts` resolves the backend URL: `VITE_API_URL`/`VITE_API_BASE_URL` (and `VITE_WS_URL` for WebSockets) from `.env`, else `DEFAULT_BACKEND_URL`. Send requests with `getDefaultFetchOptions()` (credentials: 'include' + auth headers). `getWsBaseUrl()` derives WebSocket URLs.
- **Trip wizard** (`features/trip/screens/TripCreationWizard.tsx`): Where (with optional starting city) → When → Who (adults/children) → Style → Budget amount → Review.
  - Review is step 6, where every field is editable on one page with a Proceed button.
  - `navigate('/trips/new', { state: { prefill: TripDraft } })` opens it pre-filled at Review. This is the voice "jump" target.
  - India-only place search is `features/trip/components/PlaceSearchField.tsx`.
- **Small actions with Undo:** `useToast().showToast({ message, undo })` from `components/common/UndoToast.tsx`. `ToastProvider` is mounted in `App.tsx`. Used for mark done (`TripContext.setActivityDone` → WS `trips:set_activity_done`), save/unsave place, and Explore/Food filters.
- **Which trip opens by itself:** `tripRepository.selectCurrentTripId()`. Order: the last-viewed trip if still current, then an ongoing trip, then the nearest upcoming one, otherwise none. It never picks a past trip; `isPastTrip()` means COMPLETED, or an end date before `todayInIndia()`. With no current trip, `/trip` (`ItineraryView`) shows an empty state with Plan a trip and Past trips. Past trips open only from the Past trips tab in My trips. Don't add other "fall back to the first trip" logic.
- **Map search** (`components/map/MapView.tsx`): a debounced `places:search`, India-only via `isInIndia()` from `PlaceSearchField.tsx`. It shows a pin and the straight-line distance from the GPS location only. The map always renders, starting over India when there is no location.
- **`ITINERARY_READY`** for any of the user's trips sets `TripContext.readyNotice`. `components/trip/ItineraryReadyNotice.tsx` then offers to open the itinerary or download page.
- Data access is mostly WS-first with a REST fallback (see `features/trip/TripContext.tsx`). When both fail, throw an error for the UI to show; don't fabricate local stand-in records or sessions.
- The auth token is kept **in memory only** (`setAuthToken`). `main.tsx` clears localStorage and sessionStorage on every load, keeping only `cruiser_theme`. Do not add browser-storage persistence, since it is wiped on boot. Persist state server-side instead.
- State is split between React contexts (`AuthContext`, `AppContext`, `TripContext` in `features/trip/`, `NavigationContext`, `ThemeContext`) and a Redux Toolkit store (`src/store/reducers/`: `tourGuide`, `nearby`, `mapPlaces`, `trips` slices).
- Routing (`App.tsx`, react-router v7) is a mobile-first shell: bottom nav with Home `/`, Trip `/trip/*`, Explore and More, plus global sheets and modals. `AuthGuard` sends logged-out users to `/login` and users who haven't finished onboarding to `/onboarding`. `MapView` (Leaflet) is lazy-loaded.
- Styling: Tailwind v4 via `@tailwindcss/vite`, with many hard-coded hex colors (for example `#355F58`, `#1F2522`).

## Working on this repo: lessons learned

Mistakes made in earlier sessions, and what to do instead:

- **Check how the frontend calls a feature before describing or changing its flow.** An early architecture write-up assumed REST was the main path (`POST /api/trips`, `/api/chat`). In fact the app sends almost everything over the `/ws/app` WebSocket first. Grep `wsClient.sendRequest(` and `fetch(` in `src/` first. Then fix both the WS branch and the REST route, or neither.
- **Don't trust names or comments.** `verify_trip_ownership` didn't verify ownership. `from fastapi import requests` looked like the HTTP library but wasn't, so `/api/trips/itinerary/swap-options` always returned mock data. A function was also defined twice in `main.py`, and the later copy silently won. After editing `main.py`, check for duplicates: `grep -oE "^(class|def|async def) [A-Za-z_]+" backend/main.py | sort | uniq -d`.
- **Silent fallbacks hide bugs.** The code used to swallow errors and return fake data: mock itineraries, `usr_local` sessions, local-only trips. Before assuming a feature works, check whether it is quietly returning a fallback.
- **Fallback queries can leak data.** `/api/trips/itinerary/add` accepted guests and fell back to "the latest trip overall", which meant another user's trip. Find these with `grep -n "db.query(TripModel)" backend/main.py | grep -v user_id`. Every hit must be inside an owner-checked path (`WS_TRIP_ACTIONS`, `verify_trip_ownership`, `require_owned_trip`).
- **Testing frontend logic without a test runner:** esbuild isn't installed (Vite here doesn't ship it). Transpile one `.ts` file with `require('typescript').transpileModule` and import the output from a scratchpad `.mjs`. This only works for files with type-only imports, such as `tripRepository.ts`.
- **Live end-to-end checks** against the user's running server are fine when needed. Use throwaway `step0check-*@example.com` accounts and delete them afterwards: remove rows with that `user_id` from every table, then from `auth_users`. Stop any worker you started.
- **Unused-file detection has false positives.** Files imported as `./App.tsx`, or by directory (`./store`, `../types`), look unused to a basename grep. Confirm before deleting, then rerun the check, because deleting one file can orphan another (for example `PackageInclusions.tsx`).
- **Never import `main.py` against the real database.** `database.py` calls `load_dotenv(override=True)`, and importing `main` runs `init_db()`. To test the backend locally, use the pattern in the next bullet.
- **Backend smoke-test pattern** (no real DB):
  - Replace `dotenv.load_dotenv` with a no-op.
  - Set a fake `DATABASE_URL` and `AI_PROVIDER=mock`.
  - Replace `database.engine` and `database.SessionLocal` with SQLite *before* `import main`, then `create_all`.
  - Use `TestClient` **as a context manager** (`with TestClient(app) as c:`). Without it, each request gets a new event loop and the module-level async Redis client fails with "Event loop is closed". Real uvicorn has one loop, so this doesn't happen in production.
  - Remove any queue jobs the test created from `voyageai:tasks:itinerary`, matching only the test's trip IDs.
- **Mocks in tests:** use `SimpleNamespace` for `request.state`, not `MagicMock`. `MagicMock` invents any attribute, so `getattr(state, "x", None)` returns something truthy and hides real behaviour.
- **Windows environment:**
  - Run Python scripts that print emoji with `PYTHONIOENCODING=utf-8`.
  - Long inline `python - <<'EOF'` heredocs sometimes fail in the Bash tool. Write the script to the scratchpad and run it from there.
  - Don't use `git stash` to compare before/after: it turned staged `git rm` deletions into unstaged ones.
- **Local Redis is old** (no `HELLO` command). Redis clients need `protocol=2`.
- **Security findings stay out of shared pages.** The architecture artifact is shared by link, so vulnerability details go only in chat or private notes.
- **The user edits `voicefirst.md` / `testing.md` in the IDE at the same time.** Once, their editor saved an older buffer over my changes: ticks and notes vanished and a status line went back. Re-read a plan file right before editing it, check the edit landed, and never assume an earlier edit is still there.
- **The plan can change between sessions.** For example, voice moved from a `voice:turn` action on `/ws/app` to its own `/ws/voice`. Read the current step's section in `voicefirst.md` before building, not the summary in this file.
- **Only tick boxes that a test actually proved.** Leave browser- and phone-dependent boxes for the owner, and say so next to them.
- **The user's backend runs with `--reload`** on :80, so new backend code is live as soon as it's saved. Live checks hit it directly. The voice debug store is on there, so live voice checks write into `voice_test`; delete those rows and the `test_audio_folder/<session>` folder afterwards.
- **Test clips without a microphone:** Windows SAPI (`System.Speech`, voices David/Zira/Hazel, English only) can write 16 kHz mono WAVs for live STT checks. Real Hindi or Hinglish accuracy still needs a human speaker.
- **WebSocket tests:** `TestClient.websocket_connect(path, headers={"origin": ...})` covers `/ws/voice`. Patch `voice.pipeline.get_stt` to simulate Groq. For test-only saving, create and drop a throwaway local Postgres DB (`voice_test_ci`), never the owner's `voice_test`.
- **Secrets the user gives in chat** (like the local Postgres password) go only into gitignored `.env` files, never into CLAUDE.md, plan files or memory.
- **The user's preferred workflow:**
  - Explain the plan in plain words.
  - Fix bugs and clean up before adding features.
  - Work on a branch, and don't commit until asked.
  - Report exactly what was and wasn't tested.

## Known remaining issues

- `/api/admin/pool-status` needs no login.
- Live location history (`_user_location_history`) and tour-guide sessions are in server memory only, so they are lost on restart and not shared across processes.
- `/ws/location` still accepts the token as a URL query parameter, because browsers can't set headers on WebSockets.
- `log_pipeline_5_steps` / `log_frontend_payload` print user requests and prompts to the server log.
- Accounts created by the old password-less login path can't log in. There is no password reset flow.
- Subscription tables (`payment_models.py`) aren't used by any route yet.
- `backend/COST_GUARD.md` refers to test files that aren't in the repo.
- The worker sometimes logs `Job failed: Timeout reading from socket` while idle. It looks like a Redis idle timeout, logged as if a job had failed.
- `FoodSheet.tsx` fills in made-up details when a place has none: rating 4.5, opening hours, "Vegetarian Friendly". As a result, the Pure Veg filter matches every place.

## Voice pipeline (built in step 1)

- **Separate from `/ws/app`.** Voice has its own socket, `/ws/voice` (`backend/voice/ws.py`), mounted in `main.py` with `mount_voice(app, origin_allowed=is_allowed_origin)`. The frontend is in `src/voice/` and doesn't use `wsClient`.
- **Protocol** (`backend/voice/messages.py`):
  - Text frames are control messages: `auth`, `start`, `stop`, `end_session` → `ready`, `recording`, `transcript`, `error`.
  - Binary frames are raw PCM: 16 kHz, 16-bit, mono, about 100 ms each, made by `public/pcm-worklet.js`.
  - Login is the cookie, or a first `auth` message. Never a URL token.
  - A foreign `Origin` is refused.
  - Limits: 30 s / 960 KB per recording (cut, then transcribed), one recording at a time per connection, 15 a minute and 100 a day per user (fails closed).
- **Adding a stage** (agent, tools, TTS) means adding to `voice/pipeline.run_turn`. `after_turn` runs once the app has its reply.
  - Pipeline functions are blocking; `ws.py` runs them with `run_in_threadpool`, so `/ws/app` never waits.
  - Logs carry the turn ID, lengths, timings and status. Never words or audio.
- **STT provider:** `voice/stt.get_stt()` chooses it from `VOICE_STT_PROVIDER`. Default: Groq `whisper-large-v3-turbo`, about 0.8 s for a 7 s clip.
- **Test-only saving** (`testing.md`, `voice/debug_store.py`):
  - Turns on only with `VOICE_DEBUG_STORE=true` plus `VOICE_DEBUG_DATABASE_URL`.
  - It has its own SQLAlchemy `MetaData`, never the app's `Base`, and refuses a non-local host.
  - WAVs go to `backend/test_audio_folder/` (gitignored).
  - The owner's local Postgres 17 (user `postgres`) has a `voice_test` DB. Its password is only in `backend/.env`; never write it into tracked files, docs or memory.
- **The `voice` logger** gets its own handler in `mount_voice`, because uvicorn doesn't configure app loggers. INFO lines from other app loggers don't show.
- **The test transcript panel** shows only with `VITE_VOICE_TEST_TRANSCRIPT=true`. Without it, voice errors go to the Undo toast.

## Roadmap: voice-first mode (next major feature)

Goal: the user can do everything by speaking as well as by tapping. Summary of `voicefirst.md` v2:
- **Mic and voice turn:**
  - One floating mic button after login. There's no Voice/Normal toggle. Tap to start, tap to stop, up to 30 seconds.
  - A voice turn runs over the dedicated `/ws/voice` socket (see "Voice pipeline" above). The older plan's `voice:turn` action on `/ws/app` was replaced.
  - Speech-to-text is Groq Whisper (swappable). The agent is a Groq function-calling model. Replies are spoken by Sarvam TTS with the `ritu` voice.
  - The server keeps a draft trip in Redis and finally jumps the app to the pre-filled review page (wizard step 6).
- **Tool rules:**
  - Small actions run at once, with an Undo toast.
  - Big actions (create trip, add expense, swap, regenerate, optimize, weather replan) become a server-side pending action. It runs only after "haan" or a Proceed/Confirm tap.
  - Voice never deletes trips.
  - Agent tools must call the shared services (`trip_lifecycle.create_trip_for_user`, `ownership.py`) and never re-implement logic.
- **The plan of record is `voicefirst.md`** (decisions closed 12 Nov 2026), plus `testing.md` for test-only saving.
  - Step 0 (0a–0e) was done on 13 Nov 2026 and tested live.
  - Step 1 (voice pipeline) was built on 13 Nov 2026 and tested by script and live with Groq. It still needs the owner's browser and phone tests.
  - Each step is reviewed by the user before the next one starts. Don't start step 1b (spoken reply) until asked.

## Specs in progress

`VoyageAI_Subscription_Architecture_v3.3_FINAL.md` is the authoritative spec for the in-progress Razorpay subscription system (FREE/ULTRA quotas, two-phase gateway calls with no external HTTP inside DB transactions, a global lock ordering, fail-closed entitlement). Follow it when you work on `payment_models.py`, `create_subscription_tables.py` or billing routes.
