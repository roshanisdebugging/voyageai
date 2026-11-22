/**
 * The one place the Google Maps JavaScript API is loaded (official @googlemaps/js-api-loader, once per page).
 * Google only: if the key is missing, refused or paused, callers show "Map isn't available right now";
 * no other map provider is ever loaded.
 * The key comes only from VITE_GOOGLE_MAP_DEMO_KEY and is never logged.
 */
import { importLibrary, setOptions } from '@googlemaps/js-api-loader';

export const GOOGLE_MAPS_KEY: string = (import.meta.env.VITE_GOOGLE_MAP_DEMO_KEY || '').trim();
/** Google's demo Map ID: vector map + advanced markers (no Cloud Styling). */
export const MAP_ID = 'DEMO_MAP_ID';

export class MapUnavailableError extends Error {
  /** no_key | auth_failure | load_failed */
  code: string;
  constructor(code: string) {
    super(`Google Maps unavailable: ${code}`);
    this.code = code;
  }
}

let configured = false;
let authFailed = false;
const authListeners = new Set<() => void>();

declare global {
  interface Window {
    gm_authFailure?: () => void;
  }
}

function configure() {
  if (configured) return;
  configured = true;
  setOptions({ key: GOOGLE_MAPS_KEY, v: 'weekly' });
  // Google calls this when the key is refused (bad key, referrer not allowed, API off, paused).
  // Google itself prints the error code (e.g. RefererNotAllowedMapError) to the console.
  window.gm_authFailure = () => {
    authFailed = true;
    console.warn('[MAP] Google Maps refused the key (gm_authFailure); see the Google error above.');
    authListeners.forEach((cb) => cb());
  };
}

/** Called when Google refuses the key after the script loaded. Returns an unsubscribe function. */
export function onMapsAuthFailure(cb: () => void): () => void {
  if (authFailed) cb();
  authListeners.add(cb);
  return () => authListeners.delete(cb);
}

export function mapsAuthFailed(): boolean {
  return authFailed;
}

export async function loadGoogleLibrary<T extends keyof google.maps.ImportLibraryMap>(
  name: T,
): Promise<google.maps.ImportLibraryMap[T]> {
  if (!GOOGLE_MAPS_KEY) throw new MapUnavailableError('no_key');
  if (authFailed) throw new MapUnavailableError('auth_failure');
  configure();
  try {
    return await importLibrary(name);
  } catch (err) {
    console.warn('[MAP] Google Maps library failed to load:', name, err instanceof Error ? err.name : 'error');
    throw new MapUnavailableError('load_failed');
  }
}
