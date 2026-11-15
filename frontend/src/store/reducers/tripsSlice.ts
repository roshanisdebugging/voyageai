import { createAsyncThunk, type PayloadAction } from '@reduxjs/toolkit';
import axios from 'axios';
import { getApiBaseUrl, getAuthHeaders } from '../../config/apiConfig';
import { wsClient } from '../../services/wsClient';
import type { Trip as FeatureTrip, TripStatus } from '../../features/trip/types';
import { createCacheSlice } from '../cache/createCacheSlice';
import { CACHE_TTL, shouldFetch, type CacheState } from '../cache/cacheTypes';
import { STALE, getCacheEpoch } from '../cache/epoch';

export type Trip = FeatureTrip;

export interface TripsExtra {
  activeTab: 'active' | 'upcoming' | 'completed' | 'archived';
}
export type TripsState = CacheState<Trip> & TripsExtra;

export interface FetchUserTripsArg {
  force?: boolean;
}

export const fetchUserTrips = createAsyncThunk<
  Trip[],
  FetchUserTripsArg | undefined,
  { state: { trips: TripsState }; rejectValue: string }
>(
  'trips/fetchUserTrips',
  async (_arg, { rejectWithValue }) => {
    const epoch = getCacheEpoch();
    try {
      const res = await axios.get(`${getApiBaseUrl()}/api/trips`, {
        withCredentials: true,
        headers: { ...getAuthHeaders(), Accept: 'application/json' },
      });
      if (epoch !== getCacheEpoch()) return rejectWithValue(STALE);
      const data = res.data;
      return (Array.isArray(data) ? data : data?.trips || []) as Trip[];
    } catch (httpErr: any) {
      // A 401 is handled globally by the auth interceptor; do not mask it with a WS retry.
      if (httpErr?.response?.status === 401) {
        return rejectWithValue('Session expired');
      }
      try {
        const wsTrips = await wsClient.sendRequest<Trip[]>('trips:list', {});
        if (epoch !== getCacheEpoch()) return rejectWithValue(STALE);
        if (Array.isArray(wsTrips)) return wsTrips;
        return rejectWithValue('Failed to fetch user trips');
      } catch {
        return rejectWithValue(httpErr?.response?.data?.detail || 'Failed to fetch user trips');
      }
    }
  },
  {
    condition: (arg, { getState }) =>
      shouldFetch(getState().trips, CACHE_TTL.trips, arg?.force),
  },
);

const { slice } = createCacheSlice<Trip, TripsExtra>()({
  name: 'trips',
  selectId: (t) => t.id,
  extraInitialState: { activeTab: 'active' },
  reducers: {
    setActiveTab(state: TripsState, action: PayloadAction<TripsExtra['activeTab']>) {
      state.activeTab = action.payload;
    },
    updateTripStatusLocally(state: TripsState, action: PayloadAction<{ tripId: string; status: TripStatus }>) {
      const trip = state.data.find((t) => t.id === action.payload.tripId);
      if (trip) trip.status = action.payload.status;
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(fetchUserTrips.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(fetchUserTrips.fulfilled, (state, action) => {
        state.loading = false;
        state.isInitialized = true;
        state.data = action.payload;
        state.error = null;
        state.lastFetchedAt = Date.now();
      })
      .addCase(fetchUserTrips.rejected, (state, action) => {
        if (action.payload === STALE) return; // a purge happened mid-flight; state is already reset
        state.loading = false;
        state.error = action.payload || 'Failed to fetch user trips';
      });
  },
});

export const tripsSlice = slice;
export const {
  set: setTrips,
  upsert: upsertTrip,
  remove: removeTrip,
  clear: clearTrips,
  invalidate: invalidateTrips,
  setActiveTab,
  updateTripStatusLocally,
} = slice.actions;
export default slice.reducer;
