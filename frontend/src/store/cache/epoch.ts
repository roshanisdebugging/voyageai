/**
 * Cache epoch. Bumped on every purge (logout / 401 / user switch). A thunk captures the epoch
 * before its network call and, if it changed by the time the response arrives, rejects with
 * STALE instead of writing the previous user's data back into a freshly-reset store.
 */
let epoch = 0;

export const STALE = '__stale__';
export const getCacheEpoch = (): number => epoch;
export const bumpCacheEpoch = (): void => {
  epoch += 1;
};
