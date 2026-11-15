import type { Middleware } from '@reduxjs/toolkit';

/** Bump on ANY persisted slice schema change. A mismatch discards the cache. */
export const CACHE_VERSION = 1;
export const CACHE_STORAGE_KEY = 'voyageai_cache';

/** Whitelist. The auth token is never part of Redux and must never be added here. */
export const PERSISTED_SLICES = ['trips', 'tripDetails', 'savedPlaces', 'tourGuide'] as const;
type PersistedSlice = (typeof PERSISTED_SLICES)[number];

const CAPS = { trips: 20, tripDetails: 5, tourGuide: 50 } as const;
const DEBOUNCE_MS = 500;

interface Envelope {
  cacheVersion: number;
  ownerUserId: string | null;
  savedAt: number;
  slices: Partial<Record<PersistedSlice, any>>;
}

let ownerUserId: string | null = null;
let ownerLoaded = false;
let timer: ReturnType<typeof setTimeout> | null = null;
let lastRefs: Partial<Record<PersistedSlice, unknown>> = {};

function storage(): Storage | null {
  try {
    return typeof localStorage !== 'undefined' ? localStorage : null;
  } catch {
    return null;
  }
}

function removeKey() {
  try {
    storage()?.removeItem(CACHE_STORAGE_KEY);
  } catch {
    /* ignore */
  }
}

export function getCacheOwner(): string | null {
  return ownerUserId;
}

export function setCacheOwner(userId: string | null) {
  ownerUserId = userId;
  ownerLoaded = true;
  // Rewrite envelope owner on next persist.
  lastRefs = {};
}

/** Hydrate persisted slices. Never throws; any problem discards the cache. */
export function loadPersistedState(): Record<string, any> | undefined {
  try {
    const raw = storage()?.getItem(CACHE_STORAGE_KEY);
    if (!raw) return undefined;
    const env = JSON.parse(raw) as Envelope;
    if (!env || env.cacheVersion !== CACHE_VERSION || typeof env.slices !== 'object' || !env.slices) {
      removeKey();
      return undefined;
    }
    ownerUserId = env.ownerUserId ?? null;
    ownerLoaded = true;

    const out: Record<string, any> = {};
    for (const key of PERSISTED_SLICES) {
      const s = env.slices[key];
      if (!s || !Array.isArray(s.data)) continue;
      // Never restore transient flags.
      out[key] = { ...s, loading: false, error: null };
    }
    return Object.keys(out).length ? out : undefined;
  } catch {
    removeKey();
    return undefined;
  }
}

function buildSlices(state: any, includeDetails: boolean): Envelope['slices'] {
  const slices: Envelope['slices'] = {};
  for (const key of PERSISTED_SLICES) {
    if (key === 'tripDetails' && !includeDetails) continue;
    const s = state?.[key];
    if (!s) continue;
    if (key === 'trips') {
      slices.trips = { ...s, data: s.data.slice(0, CAPS.trips) };
    } else if (key === 'tripDetails') {
      const newest = [...s.data]
        .sort((a: any, b: any) => (b.fetchedAt ?? 0) - (a.fetchedAt ?? 0))
        .slice(0, CAPS.tripDetails);
      slices.tripDetails = { ...s, data: newest };
    } else if (key === 'tourGuide') {
      // Optimistic (pending) messages are never persisted: a reload would strand them forever.
      slices.tourGuide = { ...s, data: s.data.filter((m: any) => !m.pending).slice(-CAPS.tourGuide) };
    } else {
      slices[key] = s;
    }
  }
  return slices;
}

const hasContent = (state: any) =>
  PERSISTED_SLICES.some((k) => state?.[k] && (state[k].isInitialized || state[k].data?.length > 0));

function write(state: any) {
  const ls = storage();
  if (!ls) return;
  // Nothing worth keeping (e.g. right after a purge): leave no key behind rather than an empty shell.
  if (!hasContent(state)) {
    removeKey();
    return;
  }
  const make = (includeDetails: boolean): string =>
    JSON.stringify({
      cacheVersion: CACHE_VERSION,
      ownerUserId,
      savedAt: Date.now(),
      slices: buildSlices(state, includeDetails),
    } satisfies Envelope);
  try {
    ls.setItem(CACHE_STORAGE_KEY, make(true));
  } catch {
    // Quota exceeded: drop the heaviest slice and retry once, else skip silently.
    try {
      ls.setItem(CACHE_STORAGE_KEY, make(false));
    } catch {
      /* give up silently */
    }
  }
}

export const persistMiddleware: Middleware = (api) => (next) => (action) => {
  const result = next(action);
  const state = api.getState() as any;

  let changed = false;
  for (const key of PERSISTED_SLICES) {
    if (lastRefs[key] !== state?.[key]) {
      lastRefs[key] = state?.[key];
      changed = true;
    }
  }
  if (changed) {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      // Do not write a bare cache for an unknown owner before auth settles.
      if (!ownerLoaded) ownerLoaded = true;
      write(api.getState());
    }, DEBOUNCE_MS);
  }
  return result;
};

/** Remove the persisted cache and cancel any pending debounced write. */
export function clearPersistedCache(): void {
  if (timer) {
    clearTimeout(timer);
    timer = null;
  }
  lastRefs = {};
  removeKey();
}
