/**
 * Runs the agent's ui_actions from a voice "reply" (voicefirst.md step 2).
 * Only "navigate" exists in this step, and only to routes in this allowlist, which mirrors
 * backend/voice/pages.py. Anything else is ignored with a console warning.
 */
export interface UiAction {
  type: string;
  to?: string;
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

/** Returns how many actions ran. */
export function runUiActions(actions: unknown, navigate: (to: string) => void): number {
  if (!Array.isArray(actions)) return 0;
  let ran = 0;
  for (const action of actions as UiAction[]) {
    if (action?.type === 'navigate' && isAllowedRoute(action.to)) {
      navigate(action.to);
      ran += 1;
    } else {
      console.warn('[voice] ignored ui_action', action);
    }
  }
  return ran;
}
