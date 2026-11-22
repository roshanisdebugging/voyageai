/**
 * Place search, Google-call-light (map stage 4.6):
 * - suggestPlaces(q): while typing, autocomplete only (3+ characters, debounced by the caller); no coordinates.
 * - resolvePlace(id): the suggestion the user picked, one Place Details call for that place only.
 * - lookupPlace(q):   a named lookup (Enter): one Text Search call, ranked landmark-first on the server.
 */
import { wsClient } from './wsClient';
import { memoize } from './memoCache';
import { CACHE_TTL } from '../store/cache/cacheTypes';
import type { DestinationReference } from '../features/trip/types';

export const SUGGEST_MIN_CHARS = 3;

export interface PlaceSuggestion {
  placeId: string;
  name: string;
  /** "Badi Choupad, Jaipur, Rajasthan, India" */
  secondary?: string;
}

export function suggestPlaces(query: string): Promise<PlaceSuggestion[]> {
  const q = query.trim();
  if (q.length < SUGGEST_MIN_CHARS) return Promise.resolve([]);
  return memoize(`places:suggest:${q.toLowerCase()}`, CACHE_TTL.placesSearch,
    () => wsClient.sendRequest('places:suggest', { query: q }));
}

export function resolvePlace(placeId: string): Promise<DestinationReference> {
  return memoize(`places:resolve:${placeId}`, CACHE_TTL.placesSearch,
    () => wsClient.sendRequest('places:resolve', { place_id: placeId }));
}

export function lookupPlace(query: string): Promise<DestinationReference[]> {
  const q = query.trim();
  return memoize(`places:search:${q.toLowerCase()}`, CACHE_TTL.placesSearch,
    () => wsClient.sendRequest('places:search', { query: q }));
}
