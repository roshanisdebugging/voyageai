/**
 * Is a place inside the open trip's destination area? The one rule for showing "Add to itinerary" on every screen
 * (through useCanAddToTrip). The backend refuses with the same radius (backend/trip_area.py, TRIP_AREA_RADIUS_KM).
 * Pure (no React), unit-tested in frontend/tests/tripArea.test.mjs.
 */
import { haversineMeters } from '../../components/map/mapLogic';
import { hasActiveTrip } from './activeTrip';
import type { Itinerary, Trip } from './types';

/** Goa is about 100 km long: 60 km covers a destination region but not another state. */
const DEFAULT_TRIP_AREA_RADIUS_KM = 60;
const fromEnv = Number(import.meta.env.VITE_TRIP_AREA_RADIUS_KM);
export const TRIP_AREA_RADIUS_KM = Number.isFinite(fromEnv) && fromEnv > 0 ? fromEnv : DEFAULT_TRIP_AREA_RADIUS_KM;

export interface PlaceCoords { latitude?: number | null; longitude?: number | null }
type AreaTrip = Pick<Trip, 'id' | 'destination'> | null | undefined;
type AreaItinerary = Pick<Itinerary, 'days'> | null | undefined;

/** inside / outside: both sides have coordinates. unknown: the place or the trip has none. no_trip: no trip open. */
export type TripAreaResult = 'inside' | 'outside' | 'unknown' | 'no_trip';

/** Real coordinates, or null. 0,0 is this app's old "unknown", never a place in India. */
function coordsOf(p: PlaceCoords | null | undefined): [number, number] | null {
  const lat = p?.latitude, lng = p?.longitude;
  if (typeof lat !== 'number' || typeof lng !== 'number' || !Number.isFinite(lat) || !Number.isFinite(lng)) return null;
  if (Math.abs(lat) > 90 || Math.abs(lng) > 180 || (lat === 0 && lng === 0)) return null;
  return [lat, lng];
}

const warnedTrips = new Set<string>();

/** The middle of the trip area: the destination, else the average of the itinerary's activities, else unknown. */
function tripCentre(trip: NonNullable<AreaTrip>, itinerary: AreaItinerary): [number, number] | null {
  const dest = coordsOf(trip.destination);
  if (dest) return dest;
  const points = (itinerary?.days || []).flatMap((d) => d.activities || []).map(coordsOf).filter((c) => c !== null);
  if (points.length > 0) {
    const sum = points.reduce((a, c) => [a[0] + c[0], a[1] + c[1]], [0, 0]);
    return [sum[0] / points.length, sum[1] / points.length];
  }
  if (!warnedTrips.has(trip.id)) {
    warnedTrips.add(trip.id);
    console.warn(`[TRIP AREA] trip ${trip.id} has no destination or activity coordinates: "Add to itinerary" stays hidden`);
  }
  return null;
}

export function tripAreaResult(place: PlaceCoords | null | undefined, trip: AreaTrip, itinerary?: AreaItinerary): TripAreaResult {
  if (!trip || !hasActiveTrip(trip)) return 'no_trip';
  const centre = tripCentre(trip, itinerary);
  const at = coordsOf(place);
  if (!centre || !at) return 'unknown';
  return haversineMeters(centre[0], centre[1], at[0], at[1]) <= TRIP_AREA_RADIUS_KM * 1000 ? 'inside' : 'outside';
}

/** True only when a trip is open and the place is known to be within TRIP_AREA_RADIUS_KM of it. */
export function isPlaceInTripArea(place: PlaceCoords | null | undefined, trip: AreaTrip, itinerary?: AreaItinerary): boolean {
  return tripAreaResult(place, trip, itinerary) === 'inside';
}

/** Highlight cards carry [lat, lng]. */
export function coordsFromPair(pair: readonly number[] | null | undefined): PlaceCoords {
  return Array.isArray(pair) && pair.length === 2 ? { latitude: pair[0], longitude: pair[1] } : {};
}

/** The day a place is already on (added earlier with this ID and name), or undefined. */
export function itineraryDayOf(placeId: string, title: string, itinerary: AreaItinerary): number | undefined {
  return itinerary?.days?.find((d) => d.activities?.some((a) => a.id === placeId && a.title === title))?.dayNumber;
}
