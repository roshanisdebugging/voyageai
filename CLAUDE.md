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
- **Trip creation** lives in `trip_lifecycle.create_trip_for_user` (validation, 30-day and 20-traveler limits, idempotency via `clientRequestId`, queueing). Both REST and WS call it; don't re-implement it in a handler.
- **Ownership**: all "does this user own this trip/activity" checks go through `ownership.py` (`find_owned_trip`, `require_owned_trip`, `find_owned_activity`, …). They never fall back to another user's data. `verify_trip_ownership` in `main.py` wraps `require_owned_trip`; use the returned trip's `id` afterwards, since the frontend sends IDs with or without the `trip_` prefix.
- **`request.state.user`** only ever holds a full `AuthUser` (set by `get_current_user`). `UserRateLimiter` stores its key in `request.state.rate_limit_user_id` instead.
- **Redis has two clients**: a sync one in `redis_client.py` (queue/pubsub/cache, `REDIS_HOST`/`REDIS_PORT`) and an async one inside `rate_limiter.py` (`REDIS_URL`).
- **AI**: `ai_provider.py` defines `AIProviderInterface` with `MockAIProvider` and `GeminiProvider`. `DynamicAIProviderProxy` picks one per call from the `AI_PROVIDER` env var (`gemini|mock`). Gemini errors are raised, never replaced with mock data: mock output (a Goa/Bihar dataset or a generic "{dest} Zone N" template) looks real to users and must only appear with `AI_PROVIDER=mock`. Add new AI capabilities to the interface and to both implementations. The tour-guide chat (`tour_guide_service.py`) calls Gemini through its own SDK/REST tiers, not through `ai_provider.py`.
- **Cost guard** (`cost_guard.py`, see `backend/COST_GUARD.md`): a fail-closed intent classifier (`travel/emergency/off_topic/unknown`) runs before any paid concierge answer. Keep the `(allowed, gate, reply)` return contract and the `PASSED_ESSENTIAL_NEED` emergency path. Never make it fail open. It guards `tour_guide:chat`/`/api/chat` and the free-chat path of `/api/ai/concierge`.
- **Rate limiting** (`rate_limiter.py`): Redis ZSET sliding window. `NetworkRateLimiter` keys on the client IP, normalized to /64 for IPv6. The IP comes from `client_ip_from`, which ignores `X-Forwarded-For` unless `TRUSTED_PROXY_HOPS` > 0 (default 0, because the API is reached directly). Behind a proxy, set it to the number of proxies, and only the entry that proxy appended is trusted. Login, register and paid-AI limiters use `fail_closed=True` (503 when Redis is down); the rest fail open. Tokens are never read from URL query strings on HTTP routes. `UserRateLimiter` keys on the session user and uses a cache-aside session lookup (`session_cache:{token}`), which is warmed on login and invalidated on logout. Routes attach the named limiter instances (`general_limiter`, `ai_limiter`, `ai_chat_limiter`, `places_limiter`, …) via `dependencies=[Depends(...)]`.
- Google Maps calls live in `services/google_maps_service.py`; the tour guide in top-level `tour_guide_service.py`.

## Auth model

`auth.py` handles sessions. The server issues a random token and stores only `SHA-256(token)` in `sessions.token_hash`. The client carries the token in the `voyageai_session` HttpOnly cookie (7 days, SameSite=Lax), with `Authorization: Bearer` / `X-Auth-Token` as a fallback. `cookie_flags()` in `main.py` sets Secure + SameSite=None over HTTPS and SameSite=Lax without Secure over plain HTTP (localhost). User identity must always come from the session, never from a `user_id` query or body param. Accounts are created only by `/api/auth/register`; `auth.authenticate_user` always requires the password and never creates users. CORS allows only `_DEFAULT_ALLOWED_ORIGINS` in `main.py` plus the comma-separated `ALLOWED_ORIGINS` env var (add a new frontend URL there). The global exception handler adds CORS headers only for those origins and does not return exception text.

## Frontend architecture

- `src/config/apiConfig.ts` resolves the backend URL: `VITE_API_URL`/`VITE_API_BASE_URL` (and `VITE_WS_URL` for WebSockets) from `.env`, else `DEFAULT_BACKEND_URL`. Send requests with `getDefaultFetchOptions()` (credentials: 'include' + auth headers). `getWsBaseUrl()` derives WebSocket URLs.
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

## Roadmap: voice-first mode (next major feature)

Goal: the user can do everything by speaking as well as by tapping. Planned design:
- **Normal / Voice toggle**, with a push-to-talk mic.
- **One voice turn:** audio goes over `/ws/app` as a `voice:turn` action. The backend runs Sarvam speech-to-text, then a Gemini "voice agent" with tools, then Sarvam TTS. The frontend gets back `{audio, text, ui_actions}`.
- **What `ui_actions` does on the frontend:** navigate, open the trip wizard pre-filled, show a confirm card.
- **Tools that only change the screen run immediately.** Tools that change data (`create_trip`, `add_expense`, `swap_activity`) only create a pending action on the server, which runs after the user says yes or taps Confirm.
- **Agent tools must call the shared services** (`trip_lifecycle.create_trip_for_user`, `ownership.py`) and never re-implement logic.
- **Data gap:** trips have no "travelling from" (origin) field yet.
- **Still to decide with the user:** languages (Hindi/English/Hinglish?), hold-to-talk vs tap-and-auto-stop, and build order.

## Specs in progress

`VoyageAI_Subscription_Architecture_v3.3_FINAL.md` is the authoritative spec for the in-progress Razorpay subscription system (FREE/ULTRA quotas, two-phase gateway calls with no external HTTP inside DB transactions, a global lock ordering, fail-closed entitlement). Follow it when you work on `payment_models.py`, `create_subscription_tables.py` or billing routes.
