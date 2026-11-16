import { createAsyncThunk } from '@reduxjs/toolkit';
import {
  getSavedPlaces,
  savePlace as savePlaceApi,
  removeSavedPlace as removeSavedPlaceApi,
  type SavedPlaceItem,
} from '../../services/savedPlacesApi';
import { createCacheSlice } from '../cache/createCacheSlice';
import { CACHE_TTL, shouldFetch, type CacheState } from '../cache/cacheTypes';
import { STALE, getCacheEpoch } from '../cache/epoch';

export type SavedPlacesState = CacheState<SavedPlaceItem>;
type ThunkCfg = { state: { savedPlaces: SavedPlacesState }; rejectValue: string };

const errMsg = (e: unknown, fallback: string) => (e instanceof Error && e.message ? e.message : fallback);

export const fetchSavedPlaces = createAsyncThunk<SavedPlaceItem[], { force?: boolean } | undefined, ThunkCfg>(
  'savedPlaces/fetch',
  async (_arg, { rejectWithValue }) => {
    const epoch = getCacheEpoch();
    try {
      const places = await getSavedPlaces();
      if (epoch !== getCacheEpoch()) return rejectWithValue(STALE);
      return places;
    } catch (e) {
      return rejectWithValue(errMsg(e, 'Failed to fetch saved places'));
    }
  },
  {
    condition: (arg, { getState }) => shouldFetch(getState().savedPlaces, CACHE_TTL.savedPlaces, arg?.force),
  },
);

/** Optimistic save. Reverts and sets `error` on failure. */
export const savePlaceThunk = createAsyncThunk<void, SavedPlaceItem, ThunkCfg>(
  'savedPlaces/save',
  async (place, { dispatch, rejectWithValue }) => {
    const epoch = getCacheEpoch();
    dispatch(addSavedPlace(place));
    try {
      await savePlaceApi(place);
    } catch (e) {
      // After a purge the store belongs to the next session; don't touch it.
      if (epoch !== getCacheEpoch()) return rejectWithValue(STALE);
      dispatch(removeSavedPlace(place.place_id));
      return rejectWithValue(errMsg(e, 'Failed to save place'));
    }
  },
);

/** Optimistic unsave. Restores the snapshot and sets `error` on failure. */
export const unsavePlaceThunk = createAsyncThunk<void, string, ThunkCfg>(
  'savedPlaces/unsave',
  async (placeId, { dispatch, getState, rejectWithValue }) => {
    const epoch = getCacheEpoch();
    const snapshot = getState().savedPlaces.data.find((p) => p.place_id === placeId);
    dispatch(removeSavedPlace(placeId));
    try {
      await removeSavedPlaceApi(placeId);
    } catch (e) {
      if (epoch !== getCacheEpoch()) return rejectWithValue(STALE);
      if (snapshot) dispatch(addSavedPlace(snapshot));
      return rejectWithValue(errMsg(e, 'Failed to remove saved place'));
    }
  },
);

const { slice } = createCacheSlice<SavedPlaceItem>()({
  name: 'savedPlaces',
  selectId: (p) => p.place_id,
  extraReducers: (builder) => {
    builder
      .addCase(fetchSavedPlaces.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(fetchSavedPlaces.fulfilled, (state, action) => {
        state.loading = false;
        state.isInitialized = true;
        state.data = action.payload;
        state.error = null;
        state.lastFetchedAt = Date.now();
      })
      .addCase(fetchSavedPlaces.rejected, (state, action) => {
        if (action.payload === STALE) return;
        state.loading = false;
        state.error = action.payload || 'Failed to fetch saved places';
      })
      .addCase(savePlaceThunk.rejected, (state, action) => {
        if (action.payload === STALE) return;
        state.error = action.payload || 'Failed to save place';
      })
      .addCase(unsavePlaceThunk.rejected, (state, action) => {
        if (action.payload === STALE) return;
        state.error = action.payload || 'Failed to remove saved place';
      });
  },
});

/** `undefined` = slice not loaded yet, caller should fall back to checkPlaceSaved(). */
export const selectIsPlaceSaved = (
  state: { savedPlaces: SavedPlacesState },
  placeId: string,
): boolean | undefined =>
  state.savedPlaces.isInitialized || state.savedPlaces.data.length > 0
    ? state.savedPlaces.data.some((p) => p.place_id === placeId)
    : undefined;

export const savedPlacesSlice = slice;
export const {
  set: setSavedPlaces,
  upsert: addSavedPlace,
  remove: removeSavedPlace,
  clear: clearSavedPlaces,
  invalidate: invalidateSavedPlaces,
} = slice.actions;
export default slice.reducer;
