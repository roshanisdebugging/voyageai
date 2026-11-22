/**
 * Pure map logic (no DOM, no Google objects), unit-tested in frontend/tests/mapLogic.test.mjs.
 * Pin style per category, cluster style, distance text, the trip-open button rule, map types, camera easing.
 */
import { MAP_CATEGORY_CONFIG, getCanonicalCategory } from './mapCategoryConfig';

export interface PinStyle {
  category: 'sights' | 'food' | 'hotels' | 'experiences';
  emoji: string;
  /** main colour (ring/selected fill) */
  color: string;
  /** dot / icon colour */
  ink: string;
  label: string;
}

/** Category -> the pin's look, from mapCategoryConfig.ts (the single source of category colours and icons). */
export function pinStyle(category: string, name = ''): PinStyle {
  const key = getCanonicalCategory(category, name);
  const cfg = MAP_CATEGORY_CONFIG[key] || MAP_CATEGORY_CONFIG.sights;
  return { category: key, emoji: cfg.emoji, color: cfg.ring, ink: cfg.dot, label: cfg.label };
}

/** Cluster bubble: size grows with the count; big counts read "99+". */
export function clusterStyle(count: number): { size: number; label: string } {
  const size = count < 10 ? 38 : count < 25 ? 44 : count < 50 ? 50 : 56;
  return { size, label: count > 99 ? '99+' : String(count) };
}

/** Clustering: only when there are enough markers to crowd the map; never once zoomed in close. */
export const CLUSTER_OPTIONS = {
  /** pixel radius for grouping (supercluster) */
  radius: 70,
  /** at this zoom and closer, every place shows on its own */
  maxZoom: 16,
  /** fewer markers than this: no clustering at all */
  minMarkers: 12,
} as const;

export function shouldCluster(markerCount: number): boolean {
  return markerCount >= CLUSTER_OPTIONS.minMarkers;
}

/** Card distance: "850 m away" / "4.2 km away"; unknown -> "Nearby" (never an invented number). */
export function formatDistance(meters?: number | null): string {
  if (meters === undefined || meters === null || !Number.isFinite(meters)) return 'Nearby';
  if (meters < 1000) return `${Math.round(meters)} m away`;
  return `${(meters / 1000).toFixed(1)} km away`;
}

/** Search result distance (straight line): "850 m" / "4.2 km" / "240 km". */
export function formatStraightLine(meters: number): string {
  if (meters < 1000) return `${Math.round(meters)} m`;
  const km = meters / 1000;
  return km < 10 ? `${km.toFixed(1)} km` : `${Math.round(km)} km`;
}

/** Great-circle distance in metres (rounded). */
export function haversineMeters(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const R = 6371000;
  const dLat = ((lat2 - lat1) * Math.PI) / 180;
  const dLon = ((lon2 - lon1) * Math.PI) / 180;
  const a = Math.sin(dLat / 2) ** 2 + Math.cos((lat1 * Math.PI) / 180) * Math.cos((lat2 * Math.PI) / 180) * Math.sin(dLon / 2) ** 2;
  return Math.round(R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a)));
}

export type PlaceAction = 'add' | 'save' | 'details';

/** The trip-open rule for a place card: "Add to itinerary" only while a trip is open; Save and Details always. */
export function placeActions(tripOpen: boolean): PlaceAction[] {
  return tripOpen ? ['add', 'save', 'details'] : ['save', 'details'];
}

export type MapTypeKey = 'roadmap' | 'satellite' | 'terrain';
export const MAP_TYPES: { key: MapTypeKey; label: string }[] = [
  { key: 'roadmap', label: 'Map' },
  { key: 'satellite', label: 'Satellite' },
  { key: 'terrain', label: 'Terrain' },
];

/** Smooth camera easing (0..1 -> 0..1). */
export function easeInOutCubic(t: number): number {
  const x = Math.min(1, Math.max(0, t));
  return x < 0.5 ? 4 * x * x * x : 1 - (-2 * x + 2) ** 3 / 2;
}

/**
 * Camera path for a fly-to: zoom out a little on long hops so the move reads as travel, then in.
 * Returns the zoom at progress t (0..1).
 */
export function flyZoom(from: number, to: number, distanceMeters: number, t: number): number {
  const e = easeInOutCubic(t);
  const dip = distanceMeters > 3000 ? Math.min(4, Math.log2(distanceMeters / 3000) + 1) : 0;
  const base = from + (to - from) * e;
  return base - dip * Math.sin(Math.PI * e);
}

/** Fly-to duration: longer for longer hops, capped. */
export function flyDurationMs(distanceMeters: number): number {
  return Math.round(Math.min(1800, 700 + Math.log10(Math.max(10, distanceMeters)) * 180));
}

// ── Routes (map stage 3) ──

export type RouteMode = 'drive' | 'two_wheeler' | 'walk';
export const DEFAULT_ROUTE_MODE: RouteMode = 'drive';
export const ROUTE_MODES: { key: RouteMode; label: string; words: string }[] = [
  { key: 'drive', label: 'Car', words: 'by car' },
  { key: 'two_wheeler', label: 'Bike', words: 'by bike' },
  { key: 'walk', label: 'Walk', words: 'on foot' },
];

/** "22 min" / "1 h 5 min" / "2 h". */
export function formatDurationShort(seconds: number): string {
  const mins = Math.max(1, Math.round(seconds / 60));
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  if (!h) return `${mins} min`;
  return m ? `${h} h ${m} min` : `${h} h`;
}

/** "850 m" / "6.8 km" / "240 km" (route distance). */
export function formatRouteDistance(meters: number): string {
  return formatStraightLine(meters);
}

/** "6.8 km · 22 min by car" */
export function formatRouteSummary(distanceM: number, durationS: number, mode: RouteMode): string {
  const words = ROUTE_MODES.find((m) => m.key === mode)?.words || 'by car';
  return `${formatRouteDistance(distanceM)} · ${formatDurationShort(durationS)} ${words}`;
}

/** "22 min by car" (itinerary legs). */
export function formatLegTime(durationS: number, mode: RouteMode = 'drive'): string {
  const words = ROUTE_MODES.find((m) => m.key === mode)?.words || 'by car';
  return `${formatDurationShort(durationS)} ${words}`;
}

/** Google's encoded polyline -> [{lat, lng}]. (The map uses google.maps.geometry; this is the same algorithm.) */
export function decodePolyline(encoded: string): { lat: number; lng: number }[] {
  const out: { lat: number; lng: number }[] = [];
  let index = 0, lat = 0, lng = 0;
  while (index < encoded.length) {
    for (const axis of [0, 1]) {
      let result = 0, shift = 0, b: number;
      do {
        b = encoded.charCodeAt(index++) - 63;
        result |= (b & 0x1f) << shift;
        shift += 5;
      } while (b >= 0x20);
      const delta = result & 1 ? ~(result >> 1) : result >> 1;
      if (axis === 0) lat += delta; else lng += delta;
    }
    out.push({ lat: lat / 1e5, lng: lng / 1e5 });
  }
  return out;
}

/** India bounding box (same as isInIndia() and the backend's in_india()). */
export function inIndia(lat: unknown, lng: unknown): boolean {
  const a = Number(lat), b = Number(lng);
  return Number.isFinite(a) && Number.isFinite(b) && a >= 6 && a <= 37.5 && b >= 68 && b <= 97.5;
}

/** A place gets a Route button only with real coordinates in India and when it is not mock data. */
export function canRoute(place: { latitude?: unknown; longitude?: unknown; isMock?: boolean } | null | undefined): boolean {
  return Boolean(place) && !place!.isMock && inIndia(place!.latitude, place!.longitude);
}

/** Itinerary: travel times for at most this many legs per day (one Routes call each, lazily, cached). */
export const MAX_LEGS_PER_DAY = 8;

/** A leg gets a travel time only when both activities have real coordinates in India (never invented). */
export function legHasCoords(from: { latitude?: unknown; longitude?: unknown }, to: { latitude?: unknown; longitude?: unknown }): boolean {
  return inIndia(from.latitude, from.longitude) && inIndia(to.latitude, to.longitude);
}
