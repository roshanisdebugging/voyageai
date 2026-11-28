/** The place-check label for one activity (backend place_verify.py); null = no label (not checked, older trips).
 *  On a trip with a base area (work / event), "far" means far from that area, not from the rest of the day. */
export type PlaceVerifyTone = 'ok' | 'warn';

export function placeVerifyLabel(
  status: string | null | undefined,
  hasBaseArea = false,
): { text: string; tone: PlaceVerifyTone } | null {
  switch (status) {
    case 'verified':
      return { text: 'Found on Google', tone: 'ok' };
    case 'not_found':
      return { text: 'Not found on Google', tone: 'warn' };
    case 'far':
      return { text: hasBaseArea ? 'Far from your base area' : 'Far from the rest of this day', tone: 'warn' };
    default:
      return null;
  }
}
