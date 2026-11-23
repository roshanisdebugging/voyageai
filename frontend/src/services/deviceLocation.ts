/**
 * The one device-location source for travel times (map Route button, itinerary cards, voice).
 * - Reads the device location only when a screen opens (ensureFresh) or "Use my location again" is tapped (read).
 *   No background polling here.
 * - The route origin moves only when the device moved SAME_ORIGIN_M (300 m) or more; route results are kept for the
 *   current origin only, so a smaller move (or reopening a day) makes no new Google call.
 * - Route calls: at most one per destination+mode per origin, queued one at a time when asked; counts per screen are
 *   logged (counts only, never coordinates). After a quota / paused answer, no calls for 10 minutes.
 * No React and no network imports: the app instance is made in useDeviceLocation.ts, tests make their own.
 */
import {
  INITIAL_LOCATION_STATE, applyError, applyReading, errorFromCode, originKey,
  type DeviceLocationState, type DeviceReading,
} from './deviceLocationLogic';
import type { RouteMode } from '../components/map/mapLogic';
import type { RouteResult } from './routesApi';

export interface GeoLike {
  getCurrentPosition(ok: (p: { coords: { latitude: number; longitude: number; accuracy: number }; timestamp?: number }) => void,
    fail: (e: { code?: number }) => void, opts?: unknown): void;
}

type Compute = (o: { lat: number; lng: number }, d: { lat: number; lng: number }, mode: RouteMode) => Promise<RouteResult>;

export interface StoreDeps {
  geo: GeoLike | null;
  compute: Compute;
  now?: () => number;
  log?: (line: string) => void;
}

export const FRESH_MS = 60_000;
export const PAUSE_MS = 10 * 60 * 1000;

export class RoutePausedError extends Error {
  constructor() { super('Route abhi available nahi hai'); }
}

export function createDeviceLocationStore(deps: StoreDeps) {
  const now = deps.now || (() => Date.now());
  const log = deps.log || ((line: string) => console.info(line));
  let state: DeviceLocationState = INITIAL_LOCATION_STATE;
  const listeners = new Set<() => void>();
  let inflight: Promise<DeviceLocationState> | null = null;

  let resultsFor: string | null = null;
  const results = new Map<string, Promise<RouteResult>>();
  const callsByScreen: Record<string, number> = {};
  let pausedUntil = 0;
  let chain: Promise<unknown> = Promise.resolve();

  const set = (next: DeviceLocationState) => {
    state = next;
    listeners.forEach((l) => l());
  };

  function read(): Promise<DeviceLocationState> {
    if (inflight) return inflight;
    if (!deps.geo) {
      set(applyError(state, 'unsupported'));
      return Promise.resolve(state);
    }
    set({ ...state, status: 'loading' });
    const p = new Promise<DeviceLocationState>((resolve) => {
      deps.geo!.getCurrentPosition(
        (pos) => {
          const r: DeviceReading = { lat: pos.coords.latitude, lng: pos.coords.longitude, accuracy_m: pos.coords.accuracy, updatedAt: now() };
          set(applyReading(state, r));
          resolve(state);
        },
        (e) => {
          set(applyError(state, errorFromCode(e?.code)));
          resolve(state);
        },
        { enableHighAccuracy: true, timeout: 15000, maximumAge: 30000 },
      );
    });
    // cleared after it settles (also when the device answers synchronously)
    inflight = p.then((st) => { if (inflight === p2) inflight = null; return st; });
    const p2 = inflight;
    return p2;
  }

  /** On screen open: read unless there is a reading younger than FRESH_MS (or one is on its way). */
  function ensureFresh(): Promise<DeviceLocationState> {
    if (inflight) return inflight;
    if (state.reading && now() - state.reading.updatedAt < FRESH_MS) return Promise.resolve(state);
    return read();
  }

  /**
   * The route from the current origin to dest. Kept for this origin only; one Google call per destination+mode per
   * origin. queued=true: one at a time (itinerary cards). Caller must have checked travelPlan(...).kind === 'route'.
   */
  function route(dest: { lat: number; lng: number }, mode: RouteMode, screen: string, queued = false): Promise<RouteResult> {
    const origin = state.origin;
    const ok = originKey(origin);
    if (!origin || !ok) return Promise.reject(new Error('no origin'));
    if (ok !== resultsFor) { results.clear(); resultsFor = ok; }
    const key = `${mode}|${dest.lat.toFixed(5)},${dest.lng.toFixed(5)}`;
    const have = results.get(key);
    if (have) return have;
    if (now() < pausedUntil) return Promise.reject(new RoutePausedError());
    const run = async () => {
      if (now() < pausedUntil) throw new RoutePausedError();
      callsByScreen[screen] = (callsByScreen[screen] || 0) + 1;
      log(`[ROUTES] screen=${screen} google_calls=${callsByScreen[screen]}`);
      return deps.compute({ lat: origin.lat, lng: origin.lng }, dest, mode);
    };
    let p: Promise<RouteResult>;
    if (queued) {
      p = chain.then(run, run);
      chain = p.catch(() => undefined);
    } else {
      p = run();
    }
    const kept = p.catch((err: unknown) => {
      if (resultsFor === ok) results.delete(key);          // failures are not kept: a later open may retry
      const status = (err as { status?: number })?.status;
      if (status === 503 || status === 429) pausedUntil = now() + PAUSE_MS;
      throw err;
    });
    results.set(key, kept);
    return kept;
  }

  return {
    getState: () => state,
    subscribe(l: () => void) { listeners.add(l); return () => { listeners.delete(l); }; },
    read,
    ensureFresh,
    route,
    callCounts: () => ({ ...callsByScreen }),
  };
}

export type DeviceLocationStore = ReturnType<typeof createDeviceLocationStore>;
