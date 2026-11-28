/**
 * Runs the agent's ui_actions from a voice "reply" (voicefirst.md steps 2-3).
 * Allowed types only, each strictly checked; anything else is ignored with a console warning:
 * - navigate  {to}: only routes in this allowlist (mirrors backend/voice/pages.py)
 * - map_focus {lat, lng, name, place_id?}: coordinates must be in India; the map shows a pin + distance
 * - map_results {title, places: [{name, lat, lng, place_id?, rating?, address?, category?}]} (max 6, India only):
 *   voice "Hawa Mahal ke paas restaurant": the map shows them as its place markers and cards
 * - open_trip {trip_id}: only an ID from the user's own loaded trip list (checked by the handler)
 * - open_review {prefill}: open the trip wizard's review page with the voice draft (checked shape, India only),
 *   including the purpose (purposeType / purposeText / baseArea, checked like the wizard's own fields)
 * - submit_review: press Proceed on the wizard's review page (the wizard ignores it on any other step)
 * - open_swap {activity_id, activity_name, day_number}: the existing swap sheet (its own Confirm applies the swap)
 * - refresh {what}: reload itinerary | expenses | saved_places after a change made by voice (steps 5, 6),
 *   or booking (booking stage 2): the booking screen reloads its state (a window event, BOOKING_CHANGED)
 * - undo_toast {message, undo: {action, payload}}: 5 s toast; Undo (tap only) runs an allowlisted /ws/app action
 */
import type { TripDraft } from '../features/trip/types';
import { cleanPurposeText, isPurposeType, showsBaseArea } from '../features/trip/tripPurpose';

export interface UiAction {
  type: string;
  to?: string;
  lat?: number;
  lng?: number;
  name?: string;
  place_id?: string;
  trip_id?: string;
  prefill?: unknown;
  activity_id?: string;
  activity_name?: string;
  day_number?: number;
  what?: string;
  message?: string;
  undo?: { action?: unknown; payload?: unknown };
  title?: string;
  places?: unknown;
}

export type RefreshWhat = 'itinerary' | 'expenses' | 'saved_places' | 'booking';
const REFRESH_WHAT = new Set<RefreshWhat>(['itinerary', 'expenses', 'saved_places', 'booking']);
/** Fired when a voice reply changed the booking flow; the booking screen and card reload their state. */
export const BOOKING_CHANGED = 'voyage:booking-changed';

/** The ONLY /ws/app actions an Undo may run (mirrors UNDO_ALLOWLIST in backend/voice/tools/actions.py). */
export const UNDO_ALLOWLIST = new Set(['trips:set_activity_done', 'places:save', 'places:unsave']);

export interface UndoToastAction { message: string; action: string; payload: Record<string, unknown> }
export interface OpenSwapAction { tripId: string; activityId: string; activityName: string; dayNumber: number }

export interface MapFocusAction { lat: number; lng: number; name: string; placeId?: string }

export interface MapResultPlace {
  name: string; lat: number; lng: number; placeId?: string; rating?: number; address?: string; category?: string;
}
export interface MapResultsAction { title: string; places: MapResultPlace[] }
export const MAX_MAP_RESULTS = 6;
const PLACE_ID = /^[A-Za-z0-9_-]{1,300}$/;

/** A map_results action's places: only well-formed ones in India, at most MAX_MAP_RESULTS. */
export function checkedMapResults(raw: unknown): MapResultPlace[] {
  if (!Array.isArray(raw)) return [];
  const out: MapResultPlace[] = [];
  for (const item of raw.slice(0, MAX_MAP_RESULTS)) {
    if (!item || typeof item !== 'object') continue;
    const p = item as Record<string, unknown>;
    const name = str(p.name, 120);
    if (!name || !inIndia(p.lat, p.lng)) continue;
    out.push({
      name, lat: p.lat as number, lng: p.lng as number,
      placeId: typeof p.place_id === 'string' && PLACE_ID.test(p.place_id) ? p.place_id : undefined,
      rating: typeof p.rating === 'number' && p.rating >= 0 && p.rating <= 5 ? p.rating : undefined,
      address: str(p.address, 200),
      category: typeof p.category === 'string' && /^[a-z_]{1,40}$/.test(p.category) ? p.category : undefined,
    });
  }
  return out;
}

export interface UiActionHandlers {
  navigate: (to: string) => void;
  mapFocus?: (target: MapFocusAction) => void;
  mapResults?: (results: MapResultsAction) => void;
  /** Returns false when the ID isn't one of the user's own trips (the action is then ignored). */
  openTrip?: (tripId: string) => boolean;
  openReview?: (prefill: TripDraft) => void;
  submitReview?: () => void;
  openSwap?: (target: OpenSwapAction) => void;
  refresh?: (what: Exclude<RefreshWhat, 'booking'>) => void;
  undoToast?: (toast: UndoToastAction) => void;
}

/** An undo_toast's undo, only if its action is allowlisted and its payload is a plain object. */
export function checkedUndo(raw: unknown): { action: string; payload: Record<string, unknown> } | null {
  if (!raw || typeof raw !== 'object') return null;
  const u = raw as { action?: unknown; payload?: unknown };
  if (typeof u.action !== 'string' || !UNDO_ALLOWLIST.has(u.action)) return null;
  if (!u.payload || typeof u.payload !== 'object' || Array.isArray(u.payload)) return null;
  return { action: u.action, payload: u.payload as Record<string, unknown> };
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const isInt = (v: unknown, min: number, max: number) => typeof v === 'number' && Number.isInteger(v) && v >= min && v <= max;
const str = (v: unknown, max = 200) => (typeof v === 'string' && v.length > 0 && v.length <= max ? v : undefined);

function placeRef(raw: unknown) {
  if (!raw || typeof raw !== 'object') return null;
  const p = raw as Record<string, unknown>;
  const name = str(p.name, 120);
  if (!name || !inIndia(p.latitude, p.longitude)) return null;
  return {
    id: str(p.id, 300), name, city: str(p.city, 120), region: str(p.region, 120), country: 'India',
    latitude: p.latitude as number, longitude: p.longitude as number, displayName: str(p.displayName, 300),
  };
}

/** The voice draft -> the wizard's TripDraft, only with values that pass the checks. */
export function sanitizePrefill(raw: unknown): TripDraft | null {
  if (!raw || typeof raw !== 'object') return null;
  const p = raw as Record<string, unknown>;
  const destination = placeRef(p.destination);
  if (!destination) return null;
  const startDate = typeof p.startDate === 'string' && ISO_DATE.test(p.startDate) ? p.startDate : undefined;
  const endDate = typeof p.endDate === 'string' && ISO_DATE.test(p.endDate) ? p.endDate : undefined;
  return {
    destination,
    origin: placeRef(p.origin),
    startDate,
    endDate: startDate && endDate && endDate >= startDate ? endDate : undefined,
    adultsCount: isInt(p.adultsCount, 1, 20) ? (p.adultsCount as number) : undefined,
    childrenCount: isInt(p.childrenCount, 0, 19) ? (p.childrenCount as number) : undefined,
    customBudgetAmount: isInt(p.customBudgetAmount, 1000, 100_000_000) ? (p.customBudgetAmount as number) : undefined,
    planCardId: typeof p.planCardId === 'string' && /^[a-z0-9][a-z0-9-]{0,79}$/.test(p.planCardId) ? p.planCardId : undefined,
    ...prefillPurpose(p),
  };
}

/** The voice draft's purpose -> the wizard's fields. Only keys the draft sent (an older prefill keeps the wizard's
 *  own values); the text and the base area only for Business / Event / Other, like the wizard sends them. */
function prefillPurpose(p: Record<string, unknown>): Pick<TripDraft, 'purposeType' | 'purposeText' | 'baseArea'> {
  if (!isPurposeType(p.purposeType)) return {};
  const focused = showsBaseArea(p.purposeType);
  return {
    purposeType: p.purposeType,
    purposeText: focused ? cleanPurposeText(p.purposeText) : null,
    baseArea: focused ? placeRef(p.baseArea) : null,
  };
}

/** The booking screen (booking stage 2). */
export const BOOKING_ROUTE = '/trip/booking';

// Mirrors ROUTES in backend/voice/pages.py, plus BOOKING_ROUTE (see below).
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
  // NOT in pages.py on purpose: the model's navigate tool can't open the booking screen. Only the booking flow's
  // own code (backend/voice/booking_voice.py) sends it, on start / resume and after the services answer.
  BOOKING_ROUTE,
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
      // The booking screen already open: nothing to do (no second history entry, no reload).
      if (action.to === BOOKING_ROUTE && typeof window !== 'undefined' && window.location?.pathname === BOOKING_ROUTE) continue;
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
    } else if (action?.type === 'map_results' && h.mapResults && str(action.title, 80)
      && checkedMapResults(action.places).length > 0) {
      h.mapResults({ title: action.title as string, places: checkedMapResults(action.places) });
      ran += 1;
    } else if (action?.type === 'open_review' && h.openReview) {
      const prefill = sanitizePrefill(action.prefill);
      if (prefill) {
        h.openReview(prefill);
        ran += 1;
      } else {
        console.warn('[voice] ignored ui_action', action.type);
      }
    } else if (action?.type === 'submit_review' && h.submitReview) {
      h.submitReview();
      ran += 1;
    } else if (action?.type === 'open_swap' && h.openSwap && str(action.trip_id, 80) && str(action.activity_id, 120)
      && str(action.activity_name, 120) && isInt(action.day_number, 1, 60)) {
      h.openSwap({
        tripId: action.trip_id as string, activityId: action.activity_id as string,
        activityName: action.activity_name as string, dayNumber: action.day_number as number,
      });
      ran += 1;
    } else if (action?.type === 'refresh' && action.what === 'booking') {
      if (typeof window !== 'undefined') window.dispatchEvent(new Event(BOOKING_CHANGED));
      ran += 1;
    } else if (action?.type === 'refresh' && h.refresh && REFRESH_WHAT.has(action.what as RefreshWhat)) {
      h.refresh(action.what as Exclude<RefreshWhat, 'booking'>);
      ran += 1;
    } else if (action?.type === 'undo_toast' && h.undoToast && str(action.message, 160) && checkedUndo(action.undo)) {
      const undo = checkedUndo(action.undo)!;
      h.undoToast({ message: action.message as string, action: undo.action, payload: undo.payload });
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
