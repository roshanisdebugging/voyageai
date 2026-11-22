import type { Trip } from './types';

/**
 * Is a trip open? The one rule every screen uses to decide whether "Add to itinerary" shows:
 * a trip is open when it has a destination name (same check Explore's trip mode always used).
 * No trip open -> only "Save place" is offered.
 */
export function hasActiveTrip(trip: Pick<Trip, 'destination'> | null | undefined): boolean {
  return Boolean(trip?.destination?.name?.trim());
}
