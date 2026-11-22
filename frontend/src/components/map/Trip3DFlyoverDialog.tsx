/** The 3D fly-over dialog (lazy-loaded by Trip3DFlyover.tsx, so the Google loader isn't in the main bundle). */
import React, { useEffect, useRef, useState } from 'react';
import { X } from 'lucide-react';
import { Portal } from '../common/Portal';
import { loadGoogleLibrary } from './googleMapsLoader';

interface Map3DLike extends HTMLElement {
  flyCameraAround?: (o: object) => void;
  stopCameraAnimation?: () => void;
}

const FlyoverDialog: React.FC<{ lat: number; lng: number; name: string; onClose: () => void }> = ({ lat, lng, name, onClose }) => {
  const hostRef = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let el: Map3DLike | null = null;
    let cancelled = false;
    (async () => {
      try {
        const lib = await loadGoogleLibrary('maps3d') as unknown as { Map3DElement: new (o: object) => Map3DLike };
        if (cancelled || !hostRef.current) return;
        const camera = { center: { lat, lng, altitude: 0 }, range: 2500, tilt: 65, heading: 0 };
        el = new lib.Map3DElement({ ...camera, mode: 'SATELLITE' });
        el.style.cssText = 'width:100%;height:100%;display:block';
        el.addEventListener('gmp-error', () => setFailed(true));
        el.addEventListener('gmp-steadychange', () => {
          // One slow orbit once the scene is ready (reduced motion: stay still).
          if (!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
            el?.flyCameraAround?.({ camera, durationMillis: 40000, repeatCount: 1 });
          }
        }, { once: true });
        hostRef.current.appendChild(el);
      } catch {
        if (!cancelled) setFailed(true);
      }
    })();
    return () => {
      cancelled = true;
      el?.stopCameraAnimation?.();
      el?.remove();
    };
  }, [lat, lng]);

  return (
    <Portal>
      <div className="fixed inset-0 z-[var(--z-modal)] bg-black/80 flex items-center justify-center p-3" role="dialog" aria-modal="true" aria-label={`3D view of ${name}`}>
        <div className="relative w-full max-w-3xl h-[70dvh] rounded-3xl overflow-hidden bg-zinc-900">
          <div ref={hostRef} className="absolute inset-0" />
          {failed && (
            <div className="absolute inset-0 flex items-center justify-center text-sm text-zinc-200 p-6 text-center">
              3D view isn&apos;t available right now.
            </div>
          )}
          <button type="button" onClick={onClose} aria-label="Close 3D view"
            className="absolute top-3 right-3 w-10 h-10 rounded-full bg-white/90 text-zinc-900 flex items-center justify-center press-scale">
            <X className="w-5 h-5" aria-hidden="true" />
          </button>
          <div className="absolute bottom-3 left-3 px-3 py-1.5 rounded-full bg-black/60 text-white text-xs font-semibold">{name}</div>
        </div>
      </div>
    </Portal>
  );
};

export default FlyoverDialog;
