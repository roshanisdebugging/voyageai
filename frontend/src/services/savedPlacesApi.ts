import { getApiBaseUrl, fetchWithAuth } from '../config/apiConfig';

export interface SavedPlaceItem {
  id?: string;
  place_id: string;
  title: string;
  category?: string;
  location_name?: string;
  location?: string;
  coordinates?: [number, number];
  rating?: number;
  distance_text?: string;
  duration_text?: string;
  cost_text?: string;
  description?: string;
  created_at?: string;
}

export type SavedPlace = SavedPlaceItem;
export type SavePlacePayload = SavedPlaceItem;

/**
 * 1. Unified Save
 * Persists place bookmark to PostgreSQL saved_places table.
 */
export const savePlace = async (place: SavedPlaceItem): Promise<{ status: string; place_id: string }> => {
  const payload = {
    ...place,
    location_name: place.location_name || place.location || '',
  };
  const baseUrl = getApiBaseUrl();
  const res = await fetchWithAuth(`${baseUrl}/api/places/save`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || 'Failed to save place');
  }

  return await res.json();
};

/**
 * 2. Unified Unsave
 * Removes place bookmark from the database.
 */
export const removeSavedPlace = async (placeId: string): Promise<{ status: string; place_id: string }> => {
  const baseUrl = getApiBaseUrl();
  const res = await fetchWithAuth(`${baseUrl}/api/places/save/${encodeURIComponent(placeId)}`, {
    method: 'DELETE',
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || 'Failed to remove saved place');
  }

  return await res.json();
};

/**
 * 3. Unified Fetch List
 * Throws on any failure so callers (and the Redux cache) can keep their last good list
 * instead of being overwritten with an empty one.
 */
export const getSavedPlaces = async (): Promise<SavedPlaceItem[]> => {
  const baseUrl = getApiBaseUrl();
  const res = await fetchWithAuth(`${baseUrl}/api/places/saved`, { method: 'GET' });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || 'Failed to fetch saved places');
  }
  const data = await res.json();
  return Array.isArray(data) ? data : [];
};

/**
 * 4. Unified Status Check
 * Lightweight check returning boolean indicating if the current user has bookmarked this spot.
 */
export const checkPlaceSaved = async (placeId: string): Promise<boolean> => {
  if (!placeId) return false;
  try {
    const baseUrl = getApiBaseUrl();
    const res = await fetchWithAuth(`${baseUrl}/api/places/saved/check/${encodeURIComponent(placeId)}`, {
      method: 'GET',
    });
    if (res.ok) {
      const data = await res.json();
      return Boolean(data?.is_saved);
    }
  } catch (err) {
    console.warn('[SAVED PLACES] Failed to check saved status:', err);
  }
  return false;
};
