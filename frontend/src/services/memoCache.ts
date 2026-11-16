/**
 * In-memory TTL memoization for external-data lookups (place search, nearby, geocoding).
 * Never persisted. Cleared on logout / session expiry.
 */
const MAX_ENTRIES = 200;

interface Entry {
  value: unknown;
  expiresAt: number;
}

const store = new Map<string, Entry>();
const inFlight = new Map<string, Promise<unknown>>();
let generation = 0;

export function memoize<T>(key: string, ttlMs: number, loader: () => Promise<T>): Promise<T> {
  const hit = store.get(key);
  if (hit) {
    if (hit.expiresAt > Date.now()) return Promise.resolve(hit.value as T);
    store.delete(key);
  }

  const pending = inFlight.get(key);
  if (pending) return pending as Promise<T>;

  const startedAt = generation;
  const p = loader()
    .then((value) => {
      // A purge (logout / session expiry) happened while this was in flight: hand the value to
      // the caller that asked, but do not cache it for whoever uses the app next.
      if (startedAt === generation) {
        store.set(key, { value, expiresAt: Date.now() + ttlMs });
        // Oldest-first eviction (Map preserves insertion order).
        while (store.size > MAX_ENTRIES) {
          const oldest = store.keys().next().value;
          if (oldest === undefined) break;
          store.delete(oldest);
        }
      }
      return value;
    })
    .finally(() => {
      if (inFlight.get(key) === p) inFlight.delete(key);
    });
  // Rejections propagate to every waiter and are never cached.
  inFlight.set(key, p);
  return p;
}

export function clearMemoCache(): void {
  generation += 1;
  store.clear();
  inFlight.clear();
}
