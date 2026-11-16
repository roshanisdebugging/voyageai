/**
 * Tiny pub/sub for "the server says our session is gone" (HTTP 401 / WS auth error).
 * Dependency-free so apiConfig, wsClient and AuthContext can all import it without cycles.
 */
type Handler = () => void;

const handlers = new Set<Handler>();
let fired = false;

export function onSessionExpired(handler: Handler): () => void {
  handlers.add(handler);
  return () => {
    handlers.delete(handler);
  };
}

/** Fires every subscriber once per session. A burst of 401s collapses into one purge. */
export function notifySessionExpired(): void {
  if (fired) return;
  fired = true;
  handlers.forEach((h) => {
    try {
      h();
    } catch (err) {
      console.error('[SESSION] expiry handler failed:', err);
    }
  });
}

/** Re-arm after a successful login / session restore. */
export function resetSessionExpiredFlag(): void {
  fired = false;
}

/** Auth endpoints report their own 401s (bad password, no session yet); never treat them as expiry. */
export function isAuthEndpoint(url: string | undefined | null): boolean {
  return !!url && /\/api\/auth\//.test(url);
}
