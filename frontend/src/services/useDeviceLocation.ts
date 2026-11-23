/**
 * useDeviceLocation(): the device's current location for travel times, shared by the map Route button, the itinerary
 * cards and voice. Re-reads when the calling screen opens (if the last reading is older than a minute) and when
 * `retry()` is tapped ("Use my location again"). Never polls in the background.
 */
import { useEffect, useSyncExternalStore } from 'react';
import { createDeviceLocationStore } from './deviceLocation';
import { computeRoute } from './routesApi';
import type { DeviceLocationState } from './deviceLocationLogic';

export const deviceLocation = createDeviceLocationStore({
  geo: typeof navigator !== 'undefined' && 'geolocation' in navigator ? navigator.geolocation : null,
  compute: computeRoute,
});

export function useDeviceLocation(readOnOpen = true): DeviceLocationState & { retry: () => void } {
  const state = useSyncExternalStore(deviceLocation.subscribe, deviceLocation.getState);
  useEffect(() => {
    if (readOnOpen) void deviceLocation.ensureFresh();
  }, [readOnOpen]);
  return { ...state, retry: () => { void deviceLocation.read(); } };
}
