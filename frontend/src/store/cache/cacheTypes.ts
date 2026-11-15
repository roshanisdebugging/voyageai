export interface CacheState<T> {
  data: T[];
  loading: boolean;
  isInitialized: boolean;
  error: string | null;
  lastFetchedAt: number | null;
}

/** Per-slice TTLs in milliseconds. */
export const CACHE_TTL = {
  trips: 2 * 60_000,
  tripDetails: 2 * 60_000,
  savedPlaces: 5 * 60_000,
  tourGuide: 60_000,
  nearby: 5 * 60_000,
  placesSearch: 10 * 60_000,
} as const;

export function createInitialCacheState<T>(): CacheState<T> {
  return {
    data: [],
    loading: false,
    isInitialized: false,
    error: null,
    lastFetchedAt: null,
  };
}

export function isStale(
  s: Pick<CacheState<unknown>, 'lastFetchedAt'>,
  ttlMs: number,
  now: number = Date.now(),
): boolean {
  return s.lastFetchedAt === null || now - s.lastFetchedAt > ttlMs;
}

/** Refetch if forced, or if not loading and (not initialized or stale). */
export function shouldFetch(
  s: Pick<CacheState<unknown>, 'loading' | 'isInitialized' | 'lastFetchedAt'>,
  ttlMs: number,
  force?: boolean,
): boolean {
  if (force) return true;
  if (s.loading) return false;
  return !s.isInitialized || isStale(s, ttlMs);
}
