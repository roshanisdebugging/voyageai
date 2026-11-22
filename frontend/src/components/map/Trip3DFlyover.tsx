/**
 * Optional (VITE_MAP_3D=true, default off): a satellite 3D fly-over of the open trip's destination, using Google's
 * 3D Maps element (maps3d). Google only; if 3D is refused or paused, the dialog says so and nothing else loads.
 */
import React, { Suspense, useState } from 'react';
import { Orbit } from 'lucide-react';
import { useTrip } from '../../features/trip/TripContext';
import { hasActiveTrip } from '../../features/trip/activeTrip';

const MAP_3D_ENABLED = import.meta.env.VITE_MAP_3D === 'true';
const FlyoverDialog = React.lazy(() => import('./Trip3DFlyoverDialog'));

/** "3D fly-over" button for the trip page. Renders nothing unless VITE_MAP_3D=true and a trip with coordinates is open. */
export const Trip3DFlyoverButton: React.FC = () => {
  const { currentTrip } = useTrip();
  const [open, setOpen] = useState(false);
  const d = currentTrip?.destination;
  if (!MAP_3D_ENABLED || !hasActiveTrip(currentTrip) || d?.latitude == null || d?.longitude == null) return null;
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}
        className="min-h-[40px] px-3.5 rounded-full border border-[var(--color-border)] bg-[var(--color-surface)] text-xs font-bold text-[var(--color-text-primary)] flex items-center gap-1.5 press-scale">
        <Orbit className="w-4 h-4 text-[var(--color-primary)]" aria-hidden="true" /> 3D fly-over
      </button>
      {open && <Suspense fallback={null}><FlyoverDialog lat={d.latitude} lng={d.longitude} name={d.name || 'Destination'} onClose={() => setOpen(false)} /></Suspense>}
    </>
  );
};
