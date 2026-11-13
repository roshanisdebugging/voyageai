export interface RestaurantPlace {
  id: string;
  name: string;
  rating: number;
  cuisine: string[];
  priceRange: string;
  location: string;
  coordinates: [number, number];
  distanceKm: number;
  openingHours: string;
  photos: string[];
  dietary: string[];
}

export interface HotelPlace {
  id: string;
  name: string;
  rating: number;
  location: string;
  coordinates: [number, number];
  pricePerNight: number;
  photos: string[];
}

export interface DestinationInfo {
  name: string;
  centerCoordinates: [number, number] | null;
  policeContact: string;
  policeStationName: string;
  hospitalName: string;
  hospitalDistanceKm: number;
  restaurants: RestaurantPlace[];
  hotels: HotelPlace[];
}

/**
 * Dynamic destination information helper.
 * Hardcoded regional mock catalogs (Bihar, Kolkata, Goa, Jaipur) are fully removed.
 * Live dining and emergency services are dynamically fetched via Google Places (/api/places/nearby).
 */
export function getDestinationInfo(destinationName?: string, tripCoordinates?: [number, number]): DestinationInfo {
  const destName = destinationName?.trim() || 'Current Location';
  return {
    name: destName,
    centerCoordinates: tripCoordinates || null,
    policeContact: '112',
    policeStationName: 'Local Police Assistance',
    hospitalName: 'Emergency Medical Services',
    hospitalDistanceKm: 0,
    restaurants: [],
    hotels: [],
  };
}
