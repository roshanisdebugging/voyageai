import type { Trip, TripDraft, TripStatus } from './types';

/** Today's date in India as YYYY-MM-DD (the backend closes trips by the same date). */
export const todayInIndia = (): string =>
  new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' });

const dateOnly = (value?: string | null): string => (value || '').slice(0, 10);

const CLOSED_STATUSES = new Set(['COMPLETED', 'CANCELLED', 'ARCHIVED']);

/** A past trip: closed by the server, or its end date has already gone by. */
export const isPastTrip = (trip: Trip, today: string = todayInIndia()): boolean =>
  (trip.status || '').toUpperCase() === 'COMPLETED' ||
  (!CLOSED_STATUSES.has((trip.status || '').toUpperCase()) && !!trip.endDate && dateOnly(trip.endDate) < today);

const isCurrentOrUpcoming = (trip: Trip, today: string): boolean =>
  !CLOSED_STATUSES.has((trip.status || '').toUpperCase()) && !isPastTrip(trip, today);

const inMemoryTrips: Record<string, Trip[]> = {};
const inMemoryCurrentTripId: Record<string, string | null> = {};
const inMemoryDrafts: Record<string, TripDraft | null> = {};

export const tripRepository = {
  getStoredTrips(userId?: string): Trip[] {
    const key = userId || 'default';
    return inMemoryTrips[key] || [];
  },

  saveStoredTrips(trips: Trip[], userId?: string) {
    const key = userId || 'default';
    inMemoryTrips[key] = trips;
  },

  getCurrentTripId(userId?: string): string | null {
    const key = userId || 'default';
    return inMemoryCurrentTripId[key] || null;
  },

  setCurrentTripId(id: string | null, userId?: string) {
    const key = userId || 'default';
    inMemoryCurrentTripId[key] = id;
  },

  getDraft(userId?: string): TripDraft | null {
    const key = userId || 'default';
    return inMemoryDrafts[key] || null;
  },

  saveDraft(draft: TripDraft, userId?: string) {
    const key = userId || 'default';
    inMemoryDrafts[key] = { ...draft, updatedAt: new Date().toISOString() };
  },

  clearDraft(userId?: string) {
    const key = userId || 'default';
    delete inMemoryDrafts[key];
  },

  /**
   * Picks the trip to open automatically. Never picks a past trip (COMPLETED, or an end date
   * before today), even if it was the last one viewed; past trips open only when the user taps them.
   * Order: the last-viewed trip if it's still current, then an ongoing trip, then the nearest upcoming one.
   */
  selectCurrentTripId(trips: Trip[], preferredId?: string | null): string | null {
    const today = todayInIndia();
    const current = trips.filter(t => isCurrentOrUpcoming(t, today));
    if (current.length === 0) return null;

    if (preferredId && current.some(t => t.id === preferredId)) return preferredId;

    const byStart = [...current].sort((a, b) => dateOnly(a.startDate).localeCompare(dateOnly(b.startDate)));
    const ongoing = byStart.find(t => dateOnly(t.startDate) <= today);
    if (ongoing) return ongoing.id;
    return byStart[0].id;
  },

  validateStatusTransition(currentStatus: TripStatus, nextStatus: TripStatus): boolean {
    if (currentStatus === nextStatus) return true;

    if (currentStatus === 'COMPLETED' && nextStatus === 'ACTIVE') return false;
    if (currentStatus === 'ARCHIVED' && nextStatus === 'ACTIVE') return false;
    if (currentStatus === 'CANCELLED' && nextStatus === 'ACTIVE') return false;

    return true;
  }
};
