/**
 * POST /api/routes/compute (Google Routes API on the server; login required, cached on the server).
 * Called only when the user taps Route / changes the mode chip, or for an itinerary leg that scrolled into view.
 * Not cached (Google's Routes terms); the server caches only if ROUTES_CACHE_TTL_S > 0.
 */
import { getApiBaseUrl, fetchWithAuth } from '../config/apiConfig';
import { memoize } from './memoCache';
import type { RouteMode } from '../components/map/mapLogic';

export interface RouteResult {
  distance_m: number;
  duration_s: number;
  polyline: string | null;
  mode: RouteMode;
  /** Google's route warnings (show them with walk / bike routes), or null. */
  warning: string | null;
  cached?: boolean;
}

export class RouteError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

const r4 = (x: number) => Math.round(x * 1e4) / 1e4;
// Google's Routes terms (19.3) allow caching only lat/lng, so route results are not kept in memory either:
// memoize only joins identical requests that are in flight at the same moment.
const CLIENT_TTL_MS = 0;

export function computeRoute(
  origin: { lat: number; lng: number },
  destination: { lat: number; lng: number },
  mode: RouteMode,
): Promise<RouteResult> {
  const key = `route:${mode}:${r4(origin.lat)},${r4(origin.lng)}:${r4(destination.lat)},${r4(destination.lng)}`;
  return memoize(key, CLIENT_TTL_MS, async () => {
    const res = await fetchWithAuth(`${getApiBaseUrl()}/api/routes/compute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ origin, destination, mode }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new RouteError(res.status, typeof body.detail === 'string' ? body.detail : 'Route unavailable');
    }
    return res.json() as Promise<RouteResult>;
  });
}
