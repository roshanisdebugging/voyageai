/**
 * Travel-time origin rules (pure; unit-tested in tests/deviceLocation.test.mjs).
 * The origin of every travel time is the device's current location: never a previous activity, a hotel, the trip
 * destination, the map centre or a default. The backend voice tool uses the same numbers (voice/tools/lookups.py).
 */

/** Worse than this accuracy: not a usable origin (no Google call). */
export const MAX_ACCURACY_M = 1000;
/** A move shorter than this keeps the same origin (no new route calls). */
export const SAME_ORIGIN_M = 300;
/** Farther than this from a place: no driving time, "Aap is jagah se door hain". */
export const FAR_AWAY_M = 300_000;
/** Closer than this: "Aap yahin hain". */
export const HERE_M = 150;

export type LocationError = 'denied' | 'unavailable' | 'timeout' | 'unsupported';

export interface DeviceReading {
  lat: number;
  lng: number;
  accuracy_m: number;
  updatedAt: number;
}

export interface DeviceLocationState {
  status: 'idle' | 'loading' | 'ok' | 'error';
  /** the last reading from the device (also kept when the accuracy is poor) */
  reading: DeviceReading | null;
  /** the origin used for routes: moves only when the device moved SAME_ORIGIN_M or more */
  origin: DeviceReading | null;
  error: LocationError | null;
}

export const INITIAL_LOCATION_STATE: DeviceLocationState = { status: 'idle', reading: null, origin: null, error: null };

export function metersBetween(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const R = 6371000;
  const dLat = ((lat2 - lat1) * Math.PI) / 180;
  const dLon = ((lon2 - lon1) * Math.PI) / 180;
  const a = Math.sin(dLat / 2) ** 2 + Math.cos((lat1 * Math.PI) / 180) * Math.cos((lat2 * Math.PI) / 180) * Math.sin(dLon / 2) ** 2;
  return Math.round(R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a)));
}

export function isUsable(r: DeviceReading | null | undefined): r is DeviceReading {
  return Boolean(r) && Number.isFinite(r!.lat) && Number.isFinite(r!.lng)
    && Number.isFinite(r!.accuracy_m) && r!.accuracy_m >= 0 && r!.accuracy_m <= MAX_ACCURACY_M;
}

/** A new device reading -> the next state. The route origin only moves on a usable reading SAME_ORIGIN_M+ away. */
export function applyReading(prev: DeviceLocationState, r: DeviceReading): DeviceLocationState {
  let origin = prev.origin;
  if (isUsable(r)) {
    if (!origin || metersBetween(origin.lat, origin.lng, r.lat, r.lng) >= SAME_ORIGIN_M) origin = r;
    else origin = { ...origin, accuracy_m: r.accuracy_m, updatedAt: r.updatedAt }; // same place: same coordinates
  }
  return { status: 'ok', reading: r, origin, error: null };
}

export function applyError(prev: DeviceLocationState, error: LocationError): DeviceLocationState {
  return { ...prev, status: 'error', error };
}

/** Geolocation error code -> our error. */
export function errorFromCode(code: number | undefined): LocationError {
  return code === 1 ? 'denied' : code === 3 ? 'timeout' : 'unavailable';
}

/** The key route results are kept under: changes only when the origin moved SAME_ORIGIN_M or more. */
export function originKey(origin: DeviceReading | null): string | null {
  return origin ? `${origin.lat.toFixed(5)},${origin.lng.toFixed(5)}` : null;
}

export type TravelPlan =
  | { kind: 'no-coords' }
  | { kind: 'no-location'; reason: LocationError | 'loading' | 'idle' }
  | { kind: 'poor'; straightM: number; accuracyM: number }
  | { kind: 'here'; straightM: number }
  | { kind: 'far'; straightM: number }
  | { kind: 'route'; straightM: number; origin: DeviceReading };

/** What a card / the map sheet / voice does for one destination. Only kind 'route' calls Google. */
export function travelPlan(state: DeviceLocationState, dest: { latitude?: unknown; longitude?: unknown }): TravelPlan {
  const dLat = Number(dest.latitude), dLng = Number(dest.longitude);
  if (dest.latitude == null || dest.longitude == null || !Number.isFinite(dLat) || !Number.isFinite(dLng)) return { kind: 'no-coords' };
  const r = state.reading;
  if (!r) return { kind: 'no-location', reason: state.status === 'error' ? state.error || 'unavailable' : state.status === 'loading' ? 'loading' : 'idle' };
  if (!isUsable(r) || !state.origin) {
    return { kind: 'poor', straightM: metersBetween(r.lat, r.lng, dLat, dLng), accuracyM: r.accuracy_m };
  }
  const o = state.origin;
  const straightM = metersBetween(o.lat, o.lng, dLat, dLng);
  if (straightM < HERE_M) return { kind: 'here', straightM };
  if (straightM > FAR_AWAY_M) return { kind: 'far', straightM };
  return { kind: 'route', straightM, origin: o };
}

/** "From: Your location (accuracy 30 m)" */
export function originLabel(accuracyM: number | null | undefined): string {
  if (accuracyM == null || !Number.isFinite(accuracyM)) return 'From: Your location';
  const acc = accuracyM < 1000 ? `${Math.max(1, Math.round(accuracyM))} m` : `${(accuracyM / 1000).toFixed(1)} km`;
  return `From: Your location (accuracy ${acc})`;
}

/** Why there is no usable location, in the app's Hinglish. */
export function noLocationReason(reason: LocationError | 'loading' | 'idle' | 'poor'): string {
  switch (reason) {
    case 'denied': return 'Location chahiye: location ki permission band hai.';
    case 'timeout': return 'Location chahiye: location milne mein der ho gayi.';
    case 'unsupported': return 'Location chahiye: is browser mein location nahi hai.';
    case 'poor': return 'Aapki exact location nahi mili.';
    case 'loading': return 'Aapki location dekh rahe hain…';
    case 'idle':
    case 'unavailable':
    default: return 'Location chahiye: location abhi nahi mili.';
  }
}

/** "812 km" for "Aap is jagah se door hain (812 km)". */
export function farKm(meters: number): string {
  return `${Math.round(meters / 1000)} km`;
}

/** Google Maps directions link with both coordinates (opens Google Maps; no API call from the app). */
export function googleMapsDirectionsUrl(origin: { lat: number; lng: number }, dest: { lat: number; lng: number }): string {
  const p = new URLSearchParams({
    api: '1',
    origin: `${origin.lat.toFixed(6)},${origin.lng.toFixed(6)}`,
    destination: `${dest.lat.toFixed(6)},${dest.lng.toFixed(6)}`,
    travelmode: 'driving',
  });
  return `https://www.google.com/maps/dir/?${p.toString()}`;
}
