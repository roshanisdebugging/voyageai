/** The place-check label for one activity (backend place_verify.py); null = no label (not checked, older trips). */
export type PlaceVerifyTone = 'ok' | 'warn';

export function placeVerifyLabel(status: string | null | undefined): { text: string; tone: PlaceVerifyTone } | null {
  switch (status) {
    case 'verified':
      return { text: 'Found on Google', tone: 'ok' };
    case 'not_found':
      return { text: 'Not found on Google', tone: 'warn' };
    case 'far':
      return { text: 'Far from the rest of this day', tone: 'warn' };
    default:
      return null;
  }
}
