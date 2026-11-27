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

/** Same rule as the server: letters (any script, with vowel marks) and spaces, 2 to 60 characters. */
export function looksLikeName(raw: string): boolean {
  const text = (raw || '').trim().replace(/\s+/g, ' ');
  if (text.length < 2 || text.length > NAME_MAX) return false;
  if (!/^[\p{L}\p{M} ]+$/u.test(text)) return false;
  return (text.match(/\p{L}/gu) || []).length >= 2;
}

/** Multi-select of the services step: tapping one adds or removes it, in a fixed order. */
const ORDER = ['flight', 'train', 'hotel'];
export function toggleService(selected: string[], value: string): string[] {
  if (!ORDER.includes(value)) return selected;
  const next = selected.includes(value) ? selected.filter((s) => s !== value) : [...selected, value];
  return ORDER.filter((s) => next.includes(s));
}
