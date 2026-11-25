import React from 'react';
import { MapPin, Navigation, Phone, Star, Siren } from 'lucide-react';
import { GoogleMapsAttribution } from '../common/GoogleMapsAttribution';
import type { GuidePlace } from '../../services/guideStream';
import { placeDistanceLabel, placeRating, directionsUrl, telHref } from './guidePlaces';

const EmergencyStrip: React.FC = () => (
  <div
    role="region"
    aria-label="Emergency numbers"
    className="sticky top-0 z-10 flex flex-wrap items-center gap-2 rounded-lg bg-[var(--guide-warning-panel)] px-3 py-2 text-xs text-[var(--guide-warning)]"
  >
    <Siren className="w-4 h-4 shrink-0" aria-hidden="true" />
    <span className="font-semibold">Emergency?</span>
    <a href="tel:112" className="min-h-9 inline-flex items-center gap-1 rounded-md guide-control px-3 font-semibold">
      <Phone className="w-3.5 h-3.5" aria-hidden="true" /> Call 112
    </a>
    <a href="tel:108" className="min-h-9 inline-flex items-center gap-1 rounded-md guide-control px-3 font-semibold">
      <Phone className="w-3.5 h-3.5" aria-hidden="true" /> Ambulance 108
    </a>
  </div>
);

/**
 * Real places under a Jarvis reply (from Google; unknown values are never guessed: no hours -> "Hours not available",
 * a rating only with its review count, "Few reviews" under 5).
 * Call only when Google gave a phone (live replies; history leaves phones out), Directions, Show on map.
 */
export const GuidePlaceCards: React.FC<{
  places: GuidePlace[];
  emergency?: boolean;
  onShowOnMap: (place: GuidePlace) => void;
}> = ({ places, emergency, onShowOnMap }) => {
  if (!emergency && places.length === 0) return null;
  return (
    <div className="mt-3 space-y-2">
      {emergency && <EmergencyStrip />}
      {places.length > 0 && (
        <ul className="space-y-2" aria-label="Nearby places">
          {places.map((p, idx) => {
            const distance = placeDistanceLabel(p.distance_m);
            const rating = placeRating(p);
            return (
              <li
                key={`${p.name}-${idx}`}
                className="rounded-xl bg-[var(--guide-panel)] border border-[var(--guide-border)] p-3"
              >
                <div className="flex items-start justify-between gap-3">
                  <h4 className="min-w-0 text-sm font-semibold leading-snug wrap-anywhere">{p.name}</h4>
                  {p.open_now !== null ? (
                    <span
                      className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold ${
                        p.open_now
                          ? 'bg-[var(--guide-raised)] text-[var(--guide-ink)]'
                          : 'bg-[var(--guide-warning-panel)] text-[var(--guide-warning)]'
                      }`}
                    >
                      {p.open_now ? 'Open now' : 'Closed'}
                    </span>
                  ) : (
                    <span className="shrink-0 py-0.5 text-[11px] text-[var(--guide-muted)]">Hours not available</span>
                  )}
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-[var(--guide-muted)]">
                  {distance && <span className="tabular-nums">{distance} away</span>}
                  {rating && (
                    <span className="flex items-center gap-1 tabular-nums">
                      <Star className="w-3 h-3 fill-current" aria-hidden="true" />
                      {rating.text}
                    </span>
                  )}
                  {rating?.few && <span>Few reviews</span>}
                </div>
                {p.address && <p className="mt-1 text-xs text-[var(--guide-muted)] wrap-anywhere">{p.address}</p>}
                <div className="mt-2.5 flex flex-wrap gap-2">
                  {p.phone && (
                    <a
                      href={telHref(p.phone)}
                      className="min-h-9 px-3 rounded-lg guide-control text-xs font-semibold inline-flex items-center gap-1.5"
                    >
                      <Phone className="w-3.5 h-3.5" aria-hidden="true" /> Call
                    </a>
                  )}
                  <a
                    href={directionsUrl(p)}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="min-h-9 px-3 rounded-lg guide-control text-xs font-semibold inline-flex items-center gap-1.5"
                  >
                    <Navigation className="w-3.5 h-3.5" aria-hidden="true" /> Directions
                  </a>
                  <button
                    type="button"
                    onClick={() => onShowOnMap(p)}
                    className="min-h-9 px-3 rounded-lg guide-control text-xs font-semibold inline-flex items-center gap-1.5"
                  >
                    <MapPin className="w-3.5 h-3.5" aria-hidden="true" /> Show on map
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
      {places.length > 0 && (
        <div className="flex justify-end">
          <GoogleMapsAttribution />
        </div>
      )}
    </div>
  );
};
