import { useTrip } from './TripContext';
import { hasActiveTrip } from './activeTrip';

/** True when a trip is open (see hasActiveTrip). Use this, not a local check, so every screen agrees. */
export function useHasActiveTrip(): boolean {
  const { currentTrip } = useTrip();
  return hasActiveTrip(currentTrip);
}
