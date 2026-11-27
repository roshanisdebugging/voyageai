/**
 * Booking stage 2 (questions only; nothing is saved or sent): small pure helpers for the screen.
 * The server (backend/booking_flow.py) checks every answer; these only shape what the user types.
 */

export const NAME_MAX = 60;
export const PHONE_INPUT_MAX = 16;

/** The card shows only for an open trip whose plan is ready and that hasn't ended. */
export function bookingCardVisible(itineraryStatus: string | undefined, isPast: boolean, dismissed: boolean): boolean {
  return itineraryStatus === 'READY' && !isPast && !dismissed;
}

/** A phone field keeps digits, spaces, '+' and '-' only (letters are not silently dropped by the server: refused). */
export function cleanPhoneInput(raw: string): string {
  return (raw || '').replace(/[^0-9+\- ]/g, '').slice(0, PHONE_INPUT_MAX);
}

/** An age field keeps digits only, at most 3. */
export function cleanAgeInput(raw: string): string {
  return (raw || '').replace(/\D/g, '').slice(0, 3);
}

/**
 * Same rule as the server (booking_flow.name_problem): Latin or Devanagari letters, spaces and . - ' only,
 * 2 to 60 characters, at least 2 letters. 'script' = letters of another script (Bengali, Tamil, Ol Chiki...).
 */
export function nameProblem(raw: string, max: number = NAME_MAX): 'script' | 'invalid' | null {
  const text = (raw || '').trim().replace(/\s+/g, ' ');
  if (/[\p{L}\p{M}]/u.test(text.replace(/[\p{Script=Latin}\p{Script=Devanagari}̀-ͯ]/gu, ''))) return 'script';
  if (text.length < 2 || text.length > max) return 'invalid';
  if (!/^[\p{L}\p{M} .\-']+$/u.test(text)) return 'invalid';
  return (text.match(/\p{L}/gu) || []).length >= 2 ? null : 'invalid';
}

export function looksLikeName(raw: string): boolean {
  return nameProblem(raw) === null;
}

export const NAME_MESSAGES = {
  script: 'Naam English ya Hindi mein likhiye.',
  invalid: 'Naam mein sirf akshar ho sakte hain, 2 se 60 tak.',
} as const;

/** Multi-select of the services step: tapping one adds or removes it, in a fixed order. */
const ORDER = ['flight', 'train', 'hotel'];
export function toggleService(selected: string[], value: string): string[] {
  if (!ORDER.includes(value)) return selected;
  const next = selected.includes(value) ? selected.filter((s) => s !== value) : [...selected, value];
  return ORDER.filter((s) => next.includes(s));
}

export interface CardRow { key: string; label: string; value: string; current: boolean }

/**
 * Live card: the rows whose value changed since the last view (a voice or tap answer arrived). The first view
 * after opening the screen highlights nothing (prev = null), so coming back doesn't flash every row.
 */
export function changedKeys(prev: Record<string, string> | null, rows: CardRow[]): string[] {
  if (!prev) return [];
  return rows.filter((r) => r.value !== '-' && prev[r.key] !== r.value).map((r) => r.key);
}

export function rowValues(rows: CardRow[]): Record<string, string> {
  return Object.fromEntries(rows.map((r) => [r.key, r.value]));
}

/** Trip page: an open request (new / contacted) replaces the offer with its status line. */
export function requestLine(req: { requestNo?: string; statusLabel?: string } | null | undefined): string | null {
  return req?.requestNo ? `Request ${req.requestNo}: ${req.statusLabel ?? ''}`.trim() : null;
}
