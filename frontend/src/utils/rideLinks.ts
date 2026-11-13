/**
 * Links that hand a ride or route over to real apps. The app itself doesn't book cabs,
 * so it never shows made-up fares, drivers or booking codes.
 */
export interface RideTarget {
  name: string;
  coordinates?: [number, number] | null;
}

/** Uber universal link: opens the Uber app (or m.uber.com) with the drop-off filled in. */
export const uberRideUrl = ({ name, coordinates }: RideTarget): string => {
  const params = new URLSearchParams({ action: 'setPickup', pickup: 'my_location' });
  if (coordinates) {
    params.set('dropoff[latitude]', String(coordinates[0]));
    params.set('dropoff[longitude]', String(coordinates[1]));
    params.set('dropoff[nickname]', name);
  } else {
    params.set('dropoff[formatted_address]', name);
  }
  return `https://m.uber.com/ul/?${params.toString()}`;
};

/** Google Maps driving directions from the user's current location. */
export const googleMapsDirectionsUrl = ({ name, coordinates }: RideTarget): string => {
  const destination = coordinates ? `${coordinates[0]},${coordinates[1]}` : name;
  const params = new URLSearchParams({ api: '1', destination, travelmode: 'driving' });
  return `https://www.google.com/maps/dir/?${params.toString()}`;
};
