# Caching Implementation Plan — VoyageAI (remaining work)

> Already completed (do not redo):
> - Session-user cache (`session_user:{token}`, 5 min TTL) in `auth.get_session_user`
> - Joined single-query session lookup + write throttling (5 min)
> - Prometheus metrics + `/metrics` endpoint + Grafana dashboard
> - Request timing middleware removed (Prometheus replaces it)
> - `ARCHITECTURE_AND_FLOWS.md` doc
>
> Goal of this plan (current scope): improve perceived speed via frontend caching (Redux + localStorage). Backend caching is out of scope for this revision.

---

## 1. Current state

- Backend: session user cached. No caching for trips, saved places, chat history, tour-guide session, or places search.
- Frontend: Redux exists for `tourGuide`, `nearby`, `mapPlaces`, `trips`, but no `localStorage` persistence. `authService` caches session in `localStorage` (`cachedSession`).
- Every navigation/page load can re-hit the database for lists and details.

## 2. Proposed architecture

### Layer A — Frontend Redux + localStorage (perceived speed)
- **Redux Toolkit slices** for: `trips`, `savedPlaces`, `chat`, `tourGuide` (auth already cached).
- **Persist slice state** to `localStorage` via middleware (non-sensitive data only).
- On app boot: hydrate Redux from `localStorage` immediately (instant UI), then refetch in background and reconcile.
- **Never store the auth token** in localStorage — only cached user/profile/prefs/trips. Token stays in HttpOnly cookie.

### Layer B — Backend caching — OUT OF SCOPE
- No backend caching in this revision. Backend remains the source of truth.
- A later revision may add server-side caching; frontend invalidation rules below will not change.

## 3. What to cache, where, TTL, invalidation

| Resource | Frontend (Redux+LS) | TTL | Invalidate on |
|----------|---------------------|-----|---------------|
| Session user/profile/prefs | Yes (done) | 5 min | login, logout, onboarding update |
| Trips list | Yes | 2 min | create/update/delete trip |
| Trip detail + itinerary | Yes (by id) | 2 min | update trip, activity toggle, stay/transport/expense CRUD, regenerate, swap/optimize/refine |
| Saved places | Yes | 5 min | save/unsave place |
| Saved place check | memoize | 5 min | save/unsave |
| Chat history | Yes (last N) | 1 min | new message |
| Tour-guide session | Yes | 2 min | visit/nearby |
| Places search/autocomplete | memoize | 10 min | never (external data) |
| Places nearby | memoize | 5 min | never |
| Weather | memoize | 30 min | never |

## 4. Implementation phases (remaining)

### Phase 1 — Frontend Redux (no backend changes)
1. Add Redux slices: `tripsSlice`, `savedPlacesSlice`, `chatSlice`.
2. Add `localStorage` persist middleware (whitelist slices, version key).
3. Hydrate on app boot before `restoreSession` resolves (show cached data instantly).
4. Reconcile after API responses (replace slice with server data).
5. Add cache invalidation in mutation thunks (createTrip → refetch list).

**Files:** `frontend/src/store/*`, `App.tsx`, `AuthContext.tsx`, screens.

### Phase 2 — (Deferred) Backend caching
- Out of scope now. Read endpoints stay uncached on the backend.
- Re-enable later without changing frontend invalidation rules.

### Phase 3 — Chat & tour-guide caching (frontend only)
1. Keep last N messages / tour-guide session in Redux slices.
2. Refetch on mount; no backend caching.

### Phase 4 — Places/weather caching (frontend memoization only)
1. Memoize search/autocomplete/nearby/weather in Redux or component cache.
2. Long TTL (5–30 min); no backend caching.

### Phase 5 — Frontend invalidation contract (critical)
Implement every invalidation listed in §5.

### Phase 6 — LocalStorage hydration polish
1. Show cached UI immediately on reload; show subtle "refreshing" indicator.
2. Handle stale cache: if API returns 401, clear localStorage session and redirect to login.
3. **Versioned persisted state:** store `cacheVersion` in localStorage alongside data. On load, if version mismatch → discard cached state and fall back to empty (full refetch). Bump version on any slice schema change.
4. Wrap hydration in try/catch; on parse failure, clear localStorage and continue (never crash on bad cache).

## 5. Phase 5 — Frontend invalidation contract (Redux-only, constant rules)

> Backend caching is out of scope, so there is NO backend cache to invalidate. The backend remains the source of truth; the frontend Redux store is the only cache. All invalidation happens in the frontend slices/thunks.

### 5.0 Constant rules (apply to every slice)

1. **One mutation = one reconciliation.** After a successful mutation, either (a) apply the server response to the slice, or (b) dispatch `invalidate` + refetch. Never leave stale data.
2. **Optimistic updates are allowed**, but must be reverted on failure and reconciled on success.
3. **Every slice exposes the same standard actions:** `set`, `upsert`, `remove`, `clear`, `invalidate` (marks `isInitialized=false` so next mount refetches).
4. **Every slice has the same state shape:** `{ data, loading, isInitialized, error, lastFetchedAt }`.
5. **Refetch policy:** refetch on mount if `!isInitialized` or `lastFetchedAt` older than TTL; always refetch when `force=true`.
6. **Global invalidation:** logout or any 401 clears ALL slices + localStorage and redirects to login.

### 5.1 TTLs (frontend, per slice)

| Slice | TTL | Refetch trigger |
|-------|-----|-----------------|
| `trips` | 2 min | mount if stale, after any trip mutation |
| `savedPlaces` | 5 min | mount if stale, after save/unsave |
| `chat` | 1 min | mount if stale, after new message |
| `tourGuide` | 2 min | mount if stale, after visit/nearby |

### 5.2 Per-resource invalidation (constant pattern)

**Trips (`tripsSlice`)**
- `createTrip` success → `upsertTrip(returnedTrip)` OR `invalidate` + `fetchUserTrips(true)`.
- `updateTrip` success → `upsertTrip(updatedTrip)`.
- `deleteTrip` success → `removeTrip(tripId)`.
- `toggleActivity` / status change → `upsertTrip` with updated progress, or `invalidate` + refetch trip.
- stay/transport/expense CRUD → `invalidate` + refetch trip detail.
- regenerate / swap / optimize / refine / weather-replan → `invalidate` + refetch trip detail.
- On failure → revert optimistic change + set `error`.

**Saved places (`savedPlacesSlice`)**
- `savePlace` success → `addSavedPlace(place)`.
- `unsavePlace` success → `removeSavedPlace(placeId)`.
- `clearAllSaved` success → `clearSavedPlaces()`.
- On failure → revert + set `error`.

**Chat (`chatSlice`)**
- `sendMessage` success → `appendMessage(userMsg, assistantMsg)`; refetch history in background if needed.
- `fetchHistory` success → replace slice with server data.
- On failure → remove optimistic message + set `error`.

**Tour-guide (`tourGuideSlice`)**
- `visit` / `nearby` success → `updateSession(returnedSession)` (or `invalidate` + refetch).
- `fetchSession` success → replace slice.
- On failure → revert + set `error`.

### 5.3 Global invalidation (constant)

- **Logout:** dispatch `clearTrips`, `clearSavedPlaces`, `clearChat`, `clearTourGuide`, remove `cachedSession` and persisted Redux state from localStorage.
- **401 from any endpoint:** same as logout + redirect to login.
- **Version mismatch / parse failure in persisted state:** discard persisted state, fall back to empty, refetch.

### 5.4 localStorage persistence (constant)

- Persist only: `trips`, `savedPlaces`, `chat` (last N), `tourGuide`. Never auth token.
- Version key `cacheVersion`; bump on any slice schema change; on mismatch discard.
- Wrap hydration in try/catch; on failure clear localStorage and continue.
- Cap stored items (e.g., last 20 trips); store itinerary separately if needed.

## 6. Security considerations

- Auth token never in localStorage; only non-sensitive cached data (profile, trips, prefs).
- On logout: clear Redux state + localStorage.
- On 401 from any cached endpoint: clear all caches and redirect to login.
- Cached data may be stale across devices; TTL + refetch mitigates.

## 7. Self-review

**Strengths**
- Frontend-only: instant UI, simpler backend.
- Incremental phases; each independently shippable.
- Centralized invalidation rules across slices.

**Risks / mitigations**
- **Stale data on multi-device:** short TTLs + refetch on mount.
- **localStorage size:** cap cached items (last 20 trips), store itinerary separately.
- **Redux persist migration:** versioned state + try/catch + fallback to empty.
- **Privacy:** no tokens in localStorage; avoid caching sensitive fields.

**Recommendation:** Start with Phase 1 (frontend Redux) + Phase 5 (invalidation). Backend caching can be added later without changing these rules.

## 8. Files likely touched

- `frontend/src/store/*` (slices + persist middleware + invalidation actions)
- `frontend/src/auth/AuthContext.tsx` (hydrate from cache, logout/401 clearing)
- `frontend/src/services/*` (mutation thunks with reconciliation)

---

*Planning document only; no code changes made.*