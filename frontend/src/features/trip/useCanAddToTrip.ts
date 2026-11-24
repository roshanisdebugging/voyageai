import { useTrip } from './TripContext';
import type { Itinerary, Trip } from './types';
import { itineraryDayOf, tripAreaResult, type PlaceCoords } from './tripArea';

export interface AddToTripState {
  /** Inside the open trip's area: adding is allowed. */
  canAdd: boolean;
  /** The day this place is already on. Shown as "Added to Day N" wherever the place is. */
  addedDay?: number;
  /** Show the Add / Added button; when false, Save place takes its room. */
  showAdd: boolean;
  /** Muted line for a place known to be outside the open trip's area, else null. */
  hint: string | null;
}

/**
 * Decides "Add to itinerary" for one place card, the same on every screen. `sessionDay` is the day it was added to on
 * this screen; places already in the loaded itinerary are found by ID. `other`: judge another trip than the open one
 * (the tour guide's trip picker).
 */
export function useCanAddToTrip(other?: { trip: Trip | null; itinerary: Itinerary | null }): (place: PlaceCoords & { id: string; name: string }, sessionDay?: number) => AddToTripState {
  const open = useTrip();
  const currentTrip = other ? other.trip : open.currentTrip;
  const currentItinerary = other ? other.itinerary : open.currentItinerary;
  return (place, sessionDay) => {
    const area = tripAreaResult(place, currentTrip, currentItinerary);
    const canAdd = area === 'inside';
    const addedDay = area === 'no_trip' ? undefined : sessionDay ?? itineraryDayOf(place.id, place.name, currentItinerary);
    const destination = currentTrip?.destination?.name?.split(',')[0].trim();
    return {
      canAdd,
      addedDay,
      showAdd: canAdd || addedDay !== undefined,
      hint: area === 'outside' && addedDay === undefined ? `Outside your ${destination} trip area` : null,
    };
  };
}
