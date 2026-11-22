/**
 * Voice step 5: the place page on screen (PlaceDetailsPage sets it, clears it on leave), so "yeh jagah save
 * karo" knows which place. Sent with "start"; the server only accepts it on /details/<that place_id>.
 */
export interface ScreenPlace { place_id: string; name: string; address?: string }

let current: ScreenPlace | null = null;

export const setScreenPlace = (place: ScreenPlace | null) => { current = place; };
export const getScreenPlace = () => current;

/** Fired after voice saves/unsaves a place (or an Undo), so a page holding its own "saved" state re-checks. */
export const SAVED_PLACES_CHANGED = 'voyage:saved-places-changed';
