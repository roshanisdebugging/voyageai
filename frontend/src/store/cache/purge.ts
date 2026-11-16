import { store } from '../store';
import { resetAllCaches } from './globalActions';
import { bumpCacheEpoch } from './epoch';
import { clearPersistedCache, setCacheOwner } from './persist';
import { clearMemoCache } from '../../services/memoCache';

/**
 * Drop every client-side cache: all Redux cache slices, the persisted copy, and the memo cache.
 * Used on logout, on 401 / session expiry, and when a different user signs in.
 */
export function purgeClientCaches(): void {
  bumpCacheEpoch(); // invalidates responses that are still in flight
  store.dispatch(resetAllCaches());
  clearPersistedCache(); // after the dispatch, so it cancels the write that dispatch scheduled
  setCacheOwner(null);
  clearMemoCache();
}
