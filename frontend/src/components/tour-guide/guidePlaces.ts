/** Pure helpers for the Jarvis place cards (GuidePlaceCards.tsx); tested by tests/guideStream.test.mjs. */
import type { GuidePlace } from '../../services/guideStream';

/** "450 m" / "1.2 km"; nothing when unknown. */
export function placeDistanceLabel(meters: number | null | undefined): string | null {
  if (meters === null || meters === undefined || !Number.isFinite(meters)) return null;
  return meters < 1000 ? `${Math.round(meters)} m` : `${(meters / 1000).toFixed(1)} km`;
}

/** Google Maps directions: Google's own link for the place when it sent one, else directions to the pin. */
export function directionsUrl(p: GuidePlace): string {
  return p.maps_url || `https://www.google.com/maps/dir/?api=1&destination=${p.lat},${p.lng}`;
}

/** Digits and a leading + only, for a tel: link. */
export function telHref(phone: string): string {
  return `tel:${phone.replace(/[^\d+]/g, '')}`;
}
