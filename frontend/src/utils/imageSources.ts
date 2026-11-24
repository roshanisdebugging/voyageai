/**
 * Pure picture rules (no imports, unit-tested in tests/imageSources.test.mjs).
 * Pictures come from the server (Google place photos through /api/place-photo, Wikimedia, Pexels, or the cover
 * catalog). Nothing here invents a picture: no URL -> null -> the UI shows <ImagePlaceholder>.
 */

export type ImageSource = 'google' | 'wikipedia' | 'pexels' | 'catalog';

export interface ImageCreditInfo {
  source?: string | null;
  credit?: string | null;
  creditUrl?: string | null;
}

/** A displayable URL, or null. Server-relative proxy paths ("/api/...") get the API base in front. */
export const resolveImageUrlWith = (apiBase: string, url?: string | null): string | null => {
  if (!url || typeof url !== 'string') return null;
  const u = url.trim();
  if (u.startsWith('/api/')) return `${apiBase.replace(/\/$/, '')}${u}`;
  return /^https?:\/\//i.test(u) ? u : null;
};

/** Which src to render: null once this exact src has failed (then the placeholder shows). */
export const pickImageSrc = (resolved: string | null, failedSrc: string | null): string | null =>
  resolved && resolved !== failedSrc ? resolved : null;

/** The trip cover from the server's coverMedia (or a direct coverImage). Old "fallback" stock photos are ignored. */
export const tripCoverFrom = (trip: any): { url: string | null } & ImageCreditInfo => {
  if (!trip) return { url: null };
  const media = trip.coverMedia;
  if (media && typeof media.url === 'string' && media.url && media.provider !== 'fallback' && media.provider !== 'none') {
    return { url: media.url, source: media.provider, credit: media.credit ?? null, creditUrl: media.creditUrl ?? null };
  }
  if (typeof trip.coverImage === 'string' && /^https?:\/\//i.test(trip.coverImage)) return { url: trip.coverImage };
  return { url: null };
};

export type PlaceholderKind = 'food' | 'beach' | 'market' | 'music' | 'nightlife' | 'nature' | 'heritage' | 'festival' | 'place';

/** The icon the placeholder shows for a category (never a photo). */
export const placeholderKind = (category?: string | null): PlaceholderKind => {
  const c = (category || '').toLowerCase();
  if (/food|culinary|restaurant|cafe|street/.test(c)) return 'food';
  if (/beach|coast|sea/.test(c)) return 'beach';
  if (/market|shopping|bazaar/.test(c)) return 'market';
  if (/festival|fair|celebration/.test(c)) return 'festival';
  if (/music|concert|show/.test(c)) return 'music';
  if (/night/.test(c)) return 'nightlife';
  if (/adventure|nature|trek|hill|mountain|lake|park/.test(c)) return 'nature';
  if (/sight|culture|heritage|temple|fort|palace|museum|monument/.test(c)) return 'heritage';
  return 'place';
};

/** The credit line for a picture, or null when there is nothing to credit. */
export const creditLabel = (info: ImageCreditInfo): string | null => {
  const credit = (info.credit || '').trim();
  switch (info.source) {
    case 'google':
      return credit ? `Photo: ${credit}` : 'Photo';
    case 'wikipedia':
      return credit || 'Wikimedia Commons (CC BY-SA)';
    case 'pexels':
      return credit || 'Photo from Pexels';
    case 'catalog':
      return credit ? `Photo: ${credit}` : null;
    default:
      return null;
  }
};
