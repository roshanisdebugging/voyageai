/**
 * Runs the agent's ui_actions from a voice "reply" (voicefirst.md steps 2-3).
 * Allowed types only, each strictly checked; anything else is ignored with a console warning:
 * - navigate  {to}: only routes in this allowlist (mirrors backend/voice/pages.py)
 * - map_focus {lat, lng, name, place_id?}: coordinates must be in India; the map shows a pin + distance
 * - open_trip {trip_id}: only an ID from the user's own loaded trip list (checked by the handler)
 */
export interface UiAction {
  type: string;
  to?: string;
  lat?: number;
  lng?: number;
  name?: string;
  place_id?: string;
  trip_id?: string;
}

export interface MapFocusAction { lat: number; lng: number; name: string; placeId?: string }

export interface UiActionHandlers {
  navigate: (to: string) => void;
  mapFocus?: (target: MapFocusAction) => void;
  /** Returns false when the ID isn't one of the user's own trips (the action is then ignored). */
  openTrip?: (tripId: string) => boolean;
}

// Mirrors ROUTES in backend/voice/pages.py.
const ALLOWED_ROUTES = new Set([
  '/home',
  '/trips',
  '/trip',
  '/trip/itinerary',
  '/map',
  '/food',
  '/rides',
  '/expenses',
  '/explore',
  '/guide',
  '/saved-places',
  '/more',
  '/trips/new',
]);
const ITINERARY_DAY = /^\/trip\/itinerary\?day=([1-9]|[12][0-9]|30)$/;

export function isAllowedRoute(to: unknown): to is string {
  return typeof to === 'string' && (ALLOWED_ROUTES.has(to) || ITINERARY_DAY.test(to));
}

const inIndia = (lat: unknown, lng: unknown): boolean =>
  typeof lat === 'number' && typeof lng === 'number' && lat >= 6 && lat <= 37.5 && lng >= 68 && lng <= 97.5;

/** Returns how many actions ran. Accepts the old (navigate) function form too. */
export function runUiActions(actions: unknown, handlers: UiActionHandlers | ((to: string) => void)): number {
  if (!Array.isArray(actions)) return 0;
  const h: UiActionHandlers = typeof handlers === 'function' ? { navigate: handlers } : handlers;
  let ran = 0;
  for (const action of actions as UiAction[]) {
    if (action?.type === 'navigate' && isAllowedRoute(action.to)) {
      h.navigate(action.to);
      ran += 1;
    } else if (action?.type === 'map_focus' && h.mapFocus && inIndia(action.lat, action.lng)
      && typeof action.name === 'string' && action.name.length > 0 && action.name.length <= 120) {
      h.mapFocus({
        lat: action.lat as number,
        lng: action.lng as number,
        name: action.name,
        placeId: typeof action.place_id === 'string' && /^[A-Za-z0-9_-]{1,300}$/.test(action.place_id) ? action.place_id : undefined,
      });
      ran += 1;
    } else if (action?.type === 'open_trip' && h.openTrip && typeof action.trip_id === 'string' && action.trip_id.length <= 80
      && h.openTrip(action.trip_id)) {
      ran += 1;
    } else {
      console.warn('[voice] ignored ui_action', action?.type);
    }
  }
  return ran;
}
