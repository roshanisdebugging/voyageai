import { createAsyncThunk } from '@reduxjs/toolkit';
import axios from 'axios';
import { getApiBaseUrl, getAuthHeaders } from '../../config/apiConfig';
import { wsClient } from '../../services/wsClient';
import type { Itinerary, TripStay, TripTransport, TripExpense } from '../../features/trip/types';
import { createCacheSlice } from '../cache/createCacheSlice';
import { CACHE_TTL, type CacheState } from '../cache/cacheTypes';
import { STALE, getCacheEpoch } from '../cache/epoch';

export interface TripDetail {
  tripId: string;
  itinerary?: Itinerary | null;
  stays?: TripStay[];
  transports?: TripTransport[];
  expenses?: TripExpense[];
  /** When the itinerary was last fetched from the server. */
  fetchedAt: number;
  /** When stays/transports/expenses were last fetched from the server. */
  packageFetchedAt?: number;
}
export type TripDetailsState = CacheState<TripDetail>;

interface FetchArg {
  tripId: string;
  force?: boolean;
}
type ThunkCfg = { state: { tripDetails: TripDetailsState }; rejectValue: string };

const httpGet = async <T,>(path: string): Promise<T> => {
  const res = await axios.get(`${getApiBaseUrl()}${path}`, {
    withCredentials: true,
    headers: { ...getAuthHeaders(), Accept: 'application/json' },
  });
  return res.data as T;
};

const isFresh = (ts: number | undefined, ttl: number) => ts !== undefined && Date.now() - ts < ttl;

export const fetchTripDetail = createAsyncThunk<{ tripId: string; itinerary: Itinerary }, FetchArg, ThunkCfg>(
  'tripDetails/fetchTripDetail',
  async ({ tripId }, { rejectWithValue }) => {
    const epoch = getCacheEpoch();
    try {
      const data = await wsClient.sendRequest<Itinerary>('trips:get_itinerary', { trip_id: tripId });
      if (epoch !== getCacheEpoch()) return rejectWithValue(STALE);
      if (data) return { tripId, itinerary: data };
      return rejectWithValue('Empty itinerary');
    } catch {
      try {
        const data = await httpGet<Itinerary>(`/api/trips/${tripId}/itinerary`);
        if (epoch !== getCacheEpoch()) return rejectWithValue(STALE);
        if (data) return { tripId, itinerary: data };
        return rejectWithValue('Empty itinerary');
      } catch (httpErr: any) {
        return rejectWithValue(httpErr?.response?.data?.detail || 'Failed to fetch itinerary');
      }
    }
  },
  {
    condition: ({ tripId, force }, { getState }) => {
      if (force) return true;
      const entry = getState().tripDetails.data.find((d) => d.tripId === tripId);
      return !(entry?.itinerary && isFresh(entry.fetchedAt, CACHE_TTL.tripDetails));
    },
  },
);

export const fetchTripPackage = createAsyncThunk<
  { tripId: string; stays?: TripStay[]; transports?: TripTransport[]; expenses?: TripExpense[] },
  FetchArg,
  ThunkCfg
>(
  'tripDetails/fetchTripPackage',
  async ({ tripId }, { rejectWithValue }) => {
    const epoch = getCacheEpoch();
    try {
      const [stays, transports, expenses] = await Promise.all([
        wsClient.sendRequest<TripStay[]>('trips:get_stays', { trip_id: tripId }),
        wsClient.sendRequest<TripTransport[]>('trips:get_transports', { trip_id: tripId }),
        wsClient.sendRequest<TripExpense[]>('trips:get_expenses', { trip_id: tripId }),
      ]);
      if (epoch !== getCacheEpoch()) return rejectWithValue(STALE);
      return {
        tripId,
        stays: Array.isArray(stays) ? stays : undefined,
        transports: Array.isArray(transports) ? transports : undefined,
        expenses: Array.isArray(expenses) ? expenses : undefined,
      };
    } catch {
      try {
        const detail = await httpGet<any>(`/api/trips/${tripId}`);
        if (epoch !== getCacheEpoch()) return rejectWithValue(STALE);
        return {
          tripId,
          stays: Array.isArray(detail?.stays) ? detail.stays : undefined,
          transports: Array.isArray(detail?.transports) ? detail.transports : undefined,
          expenses: Array.isArray(detail?.expenses) ? detail.expenses : undefined,
        };
      } catch (httpErr: any) {
        return rejectWithValue(httpErr?.response?.data?.detail || 'Failed to fetch trip package data');
      }
    }
  },
  {
    condition: ({ tripId, force }, { getState }) => {
      if (force) return true;
      const entry = getState().tripDetails.data.find((d) => d.tripId === tripId);
      return !isFresh(entry?.packageFetchedAt, CACHE_TTL.tripDetails);
    },
  },
);

const { slice } = createCacheSlice<TripDetail>()({
  name: 'tripDetails',
  selectId: (d) => d.tripId,
  extraReducers: (builder) => {
    builder
      .addCase(fetchTripDetail.fulfilled, (state, action) => {
        const { tripId, itinerary } = action.payload;
        const existing = state.data.find((d) => d.tripId === tripId);
        if (existing) {
          existing.itinerary = itinerary;
          existing.fetchedAt = Date.now();
        } else {
          state.data.push({ tripId, itinerary, fetchedAt: Date.now() });
        }
        state.isInitialized = true;
        state.lastFetchedAt = Date.now();
        state.error = null;
      })
      .addCase(fetchTripDetail.rejected, (state, action) => {
        if (action.payload === STALE) return;
        state.error = action.payload || 'Failed to fetch itinerary';
      })
      .addCase(fetchTripPackage.fulfilled, (state, action) => {
        const { tripId, stays, transports, expenses } = action.payload;
        const now = Date.now();
        let entry = state.data.find((d) => d.tripId === tripId);
        if (!entry) {
          entry = { tripId, itinerary: null, fetchedAt: 0 };
          state.data.push(entry);
        }
        if (stays) entry.stays = stays;
        if (transports) entry.transports = transports;
        if (expenses) entry.expenses = expenses;
        entry.packageFetchedAt = now;
        state.isInitialized = true;
        state.lastFetchedAt = now;
      })
      .addCase(fetchTripPackage.rejected, (state, action) => {
        if (action.payload === STALE) return;
        state.error = action.payload || 'Failed to fetch trip package data';
      });
  },
});

export const selectTripDetail = (
  state: { tripDetails: TripDetailsState },
  tripId: string | null | undefined,
): TripDetail | undefined =>
  tripId ? state.tripDetails.data.find((d) => d.tripId === tripId) : undefined;

export const tripDetailsSlice = slice;
export const {
  set: setTripDetails,
  upsert: upsertTripDetail,
  remove: removeTripDetail,
  clear: clearTripDetails,
  invalidate: invalidateTripDetails,
} = slice.actions;
export default slice.reducer;
