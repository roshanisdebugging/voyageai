/**
 * Why the trip is made (purpose) and where the traveller will mostly be (base area). Optional; never blocks a trip.
 * Same rules as backend/trip_purpose.py: only Business, Event and Other get a base area (and the focused planner
 * rules); the free text is one line of at most 120 letters, digits and common punctuation.
 */
import type { DestinationReference } from './types';

export type PurposeType = 'leisure' | 'business' | 'event' | 'pilgrimage' | 'other';

export const PURPOSE_OPTIONS: { id: PurposeType; label: string }[] = [
  { id: 'leisure', label: 'Ghoomna' },
  { id: 'business', label: 'Kaam / Business' },
  { id: 'event', label: 'Event / Hackathon' },
  { id: 'pilgrimage', label: 'Teerth' },
  { id: 'other', label: 'Kuch aur' },
];

export const PURPOSE_TEXT_MAX = 120;
const TEXT_PUNCT = new Set(" .,'-()&/!?:;+#@%".split(''));

export const isPurposeType = (v: unknown): v is PurposeType =>
  typeof v === 'string' && PURPOSE_OPTIONS.some(o => o.id === v);

/** Business, Event and Other ask "where will you mostly be?". */
export const showsBaseArea = (t: PurposeType | null | undefined): boolean =>
  t === 'business' || t === 'event' || t === 'other';

/** One trimmed line of at most 120 characters, or null when empty / not allowed (quotes, markup, line breaks). */
export function cleanPurposeText(raw: unknown): string | null {
  if (typeof raw !== 'string') return null;
  const text = raw.split(/\s+/).filter(Boolean).join(' ');
  if (!text || text.length > PURPOSE_TEXT_MAX) return null;
  let hasLetter = false;
  for (const ch of text) {
    if (/\p{L}/u.test(ch)) hasLetter = true;
    else if (!/[\p{M}\p{N}]/u.test(ch) && !TEXT_PUNCT.has(ch)) return null;
  }
  return hasLetter ? text : null;
}

export interface PurposeFields {
  purposeType: PurposeType | null;
  purposeText: string | null;
  baseArea: DestinationReference | null;
}

/** What is sent with the trip: text only for Business / Event / Other, the base area only for those three. */
export function purposePayload(type: PurposeType | null, text: string, area: DestinationReference | null): PurposeFields {
  const focused = showsBaseArea(type);
  return {
    purposeType: type,
    purposeText: focused ? cleanPurposeText(text) : null,
    baseArea: focused ? area : null,
  };
}

/** The review page's problem with the purpose text, or null (empty text is fine: it is optional). */
export function purposeTextProblem(text: string): string | null {
  if (!text.trim()) return null;
  return cleanPurposeText(text) ? null : `Purpose: one line, at most ${PURPOSE_TEXT_MAX} letters, digits and . , ' - ( ) & / ! ?`;
}

/** The review summary: "Event / Hackathon · near Electronic City", or null when no purpose was chosen. */
export function purposeSummary(type: PurposeType | null | undefined, area: DestinationReference | null | undefined): string | null {
  const opt = PURPOSE_OPTIONS.find(o => o.id === type);
  if (!opt) return null;
  return showsBaseArea(type) && area?.name ? `${opt.label} · near ${area.name}` : opt.label;
}
