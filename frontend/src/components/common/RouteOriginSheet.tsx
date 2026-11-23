/**
 * Tapping a travel line: who it is from and to, and an "Open in Google Maps" link with both coordinates.
 * The link just opens Google Maps; the app makes no Google call here.
 */
import React from 'react';
import { createPortal } from 'react-dom';
import { ExternalLink, MapPin, Navigation, X } from 'lucide-react';
import { googleMapsDirectionsUrl, originLabel } from '../../services/deviceLocationLogic';

export interface RouteOriginSheetProps {
  origin: { lat: number; lng: number; accuracy_m: number };
  dest: { name: string; lat: number; lng: number };
  /** "22 min by car · 6.8 km", or a straight-line line */
  summary?: string | null;
  onClose: () => void;
}

export const RouteOriginSheet: React.FC<RouteOriginSheetProps> = ({ origin, dest, summary, onClose }) => {
  const body = (
    <div className="fixed inset-0 z-[1200] flex items-end justify-center bg-black/40" role="dialog" aria-modal="true"
      aria-label="Route details" onClick={onClose}>
      <div className="w-full max-w-md rounded-t-3xl bg-[var(--color-surface)] p-5 pb-8 space-y-4 shadow-xl"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <h2 className="text-base font-extrabold text-[var(--color-text-primary)]">Route</h2>
          <button type="button" onClick={onClose} aria-label="Close" className="min-w-[44px] min-h-[44px] flex items-center justify-center rounded-full">
            <X className="w-5 h-5" aria-hidden="true" />
          </button>
        </div>
        <div className="space-y-3 text-sm">
          <p className="flex items-start gap-2">
            <Navigation className="w-4 h-4 mt-0.5 shrink-0 text-[#1A73E8]" aria-hidden="true" />
            <span><span className="font-bold text-[var(--color-text-primary)]">{originLabel(origin.accuracy_m)}</span></span>
          </p>
          <p className="flex items-start gap-2">
            <MapPin className="w-4 h-4 mt-0.5 shrink-0 text-[var(--color-primary)]" aria-hidden="true" />
            <span><span className="font-bold text-[var(--color-text-primary)]">To: {dest.name}</span></span>
          </p>
          {summary && <p className="font-semibold tabular-nums text-[var(--color-text-secondary)]">{summary}</p>}
        </div>
        <a href={googleMapsDirectionsUrl(origin, dest)} target="_blank" rel="noopener noreferrer"
          className="w-full min-h-[44px] rounded-xl bg-[#1A73E8] text-white font-semibold text-sm flex items-center justify-center gap-2">
          <ExternalLink className="w-4 h-4" aria-hidden="true" /> Open in Google Maps
        </a>
      </div>
    </div>
  );
  return typeof document !== 'undefined' ? createPortal(body, document.body) : body;
};
