/** Pure helpers for the Jarvis place cards (GuidePlaceCards.tsx); tested by tests/guideStream.test.mjs. */
import type { GuidePlace } from '../../services/guideStream';

/** "450 m" / "1.2 km"; nothing when unknown. */
export function placeDistanceLabel(meters: number | null | undefined): string | null {
  if (meters === null || meters === undefined || !Number.isFinite(meters)) return null;
  return meters < 1000 ? `${Math.round(meters)} m` : `${(meters / 1000).toFixed(1)} km`;
}

/** Under this many reviews a rating says little: the card adds "Few reviews". */
export const FEW_REVIEWS_BELOW = 5;

/** A rating is shown only with its review count; no count -> no rating. */
export function placeRating(p: GuidePlace): { text: string; few: boolean } | null {
  if (p.rating === null || !p.rating_count || p.rating_count < 1) return null;
  return { text: `${p.rating.toFixed(1)} (${p.rating_count})`, few: p.rating_count < FEW_REVIEWS_BELOW };
}

/** Google Maps directions: Google's own link for the place when it sent one, else directions to the pin. */
export function directionsUrl(p: GuidePlace): string {
  return p.maps_url || `https://www.google.com/maps/dir/?api=1&destination=${p.lat},${p.lng}`;
}

/** Digits and a leading + only, for a tel: link. */
export function telHref(phone: string): string {
  return `tel:${phone.replace(/[^\d+]/g, '')}`;
}
