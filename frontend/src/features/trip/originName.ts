/**
 * The optional starting city's name rule. Same rule as the backend (trip_lifecycle.clean_place_name):
 * 2 to 60 characters; only letters (any script, with their vowel signs), spaces and . , ' - ( ) & /;
 * at least one letter; no digits. Unit-tested in tests/originName.test.mjs.
 */
export const ORIGIN_MAX_CHARS = 60;

const ALLOWED = /^[\p{L}\p{M} .,'()&/-]+$/u;

/** The trimmed name, or null when it isn't a place name. */
export function cleanOriginName(raw: unknown): string | null {
  if (typeof raw !== 'string') return null;
  const name = raw.split(/\s+/).filter(Boolean).join(' ');
  if (name.length < 2 || name.length > ORIGIN_MAX_CHARS) return null;
  if (!ALLOWED.test(name) || !/\p{L}/u.test(name)) return null;
  return name;
}
