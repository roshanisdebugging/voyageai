import { getApiBaseUrl } from '../config/apiConfig';
import { resolveImageUrlWith, tripCoverFrom } from './imageSources';

/** A displayable image URL (server proxy paths get the API base), or null for "show the placeholder". */
export const resolveImageUrl = (url?: string | null): string | null => resolveImageUrlWith(getApiBaseUrl(), url);

/** The trip's cover picture and its credit, as resolved by the server. No picture -> url null (placeholder). */
export const getTripCover = (trip: any) => {
  const cover = tripCoverFrom(trip);
  return { ...cover, url: resolveImageUrl(cover.url) };
};
