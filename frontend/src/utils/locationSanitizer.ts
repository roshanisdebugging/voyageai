/**
 * Location String Sanitizer Utility
 * Cleans up raw GPS strings like "Live Gps (Continuous)", "(Continuous)", "(GPS Live)", "Local Area"
 * into clean, user-friendly geographic names.
 * NEVER returns "Local Area" or "Live GPS". Defaults to "Madhubani".
 */
export function sanitizeLocationName(raw?: string): string {
  if (!raw) return 'Madhubani';

  const cleaned = raw
    .replace(/live gps|continuous|local area|current area|user location|live position|\(.*?\)/gi, '')
    .replace(/,\s*,/g, ',')
    .replace(/^[\s,]+|[\s,]+$/g, '')
    .trim();

  return cleaned && cleaned.length > 1 ? cleaned : 'Madhubani';
}
