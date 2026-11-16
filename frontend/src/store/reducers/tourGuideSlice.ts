import { createAsyncThunk, type PayloadAction } from '@reduxjs/toolkit';
import axios from 'axios';
import { getApiBaseUrl, getAuthHeaders } from '../../config/apiConfig';
import { createCacheSlice } from '../cache/createCacheSlice';
import { CACHE_TTL, shouldFetch, type CacheState } from '../cache/cacheTypes';
import { STALE, getCacheEpoch } from '../cache/epoch';

export interface Message {
  id: string;
  sender: 'user' | 'assistant';
  role: 'user' | 'assistant';
  text: string;
  content: string;
  timestamp?: string;
  created_at?: string;
  card?: any;
  chips?: string[];
  recommendations?: any[];
  metadata?: any;
  mode?: string;
  trip_id?: string | null;
  /** Optimistic message not yet confirmed by the server. Never persisted. */
  pending?: boolean;
}

/** All chat messages live in `data` (the former `messages` / `history` arrays were identical). */
export type TourGuideState = CacheState<Message>;

const parseMeta = (raw: any) => {
  if (typeof raw !== 'string') return raw || {};
  try {
    return JSON.parse(raw);
  } catch {
    return {};
  }
};

const normalizeMessage = (item: any): Message => {
  const meta = parseMeta(item.metadata);
  const role: 'user' | 'assistant' =
    item.role === 'assistant' || item.role === 'guide' || item.sender === 'assistant' ? 'assistant' : 'user';
  const text = item.content || item.text || meta?.reply || '';
  const card = item.card || meta?.card || null;
  const chips = item.chips || meta?.chips || item.recommendations || [];
  const timestamp = item.created_at || item.timestamp || new Date().toISOString();

  return {
    id: String(item.id || `msg_${Date.now()}_${Math.random()}`),
    sender: role,
    role,
    text,
    content: text,
    timestamp,
    created_at: timestamp,
    card,
    chips,
    recommendations: chips,
    metadata: { ...meta, card, chips },
    mode: item.mode || 'local',
    trip_id: item.trip_id || null,
    ...(item.pending ? { pending: true } : {}),
  };
};

type ThunkCfg = { state: { tourGuide: TourGuideState }; rejectValue: string };

export const fetchTourGuideHistory = createAsyncThunk<Message[], { force?: boolean } | undefined, ThunkCfg>(
  'tourGuide/fetchHistory',
  async (_arg, { rejectWithValue }) => {
    const epoch = getCacheEpoch();
    try {
      const res = await axios.get(`${getApiBaseUrl()}/api/tour-guide/history?limit=100`, {
        withCredentials: true,
        headers: getAuthHeaders(),
      });
      if (epoch !== getCacheEpoch()) return rejectWithValue(STALE);
      const data = res.data;
      const rawList = Array.isArray(data) ? data : data.messages || data.history || [];
      return rawList.map((item: any) => normalizeMessage(item));
    } catch (err: any) {
      return rejectWithValue(err.response?.data?.detail || 'Failed to fetch guide history');
    }
  },
  {
    condition: (arg, { getState }) => shouldFetch(getState().tourGuide, CACHE_TTL.tourGuide, arg?.force),
  },
);

const { slice } = createCacheSlice<Message>()({
  name: 'tourGuide',
  selectId: (m) => m.id,
  reducers: {
    /** Upserts by id, so confirming an optimistic message (pending -> not pending) replaces it. */
    appendGuideMessage(state: TourGuideState, action: PayloadAction<any>) {
      const normalized = normalizeMessage(action.payload);
      const idx = state.data.findIndex((m) => m.id === normalized.id);
      if (idx >= 0) state.data[idx] = normalized;
      else state.data.push(normalized);
      state.isInitialized = true;
    },
    removeGuideMessage(state: TourGuideState, action: PayloadAction<string>) {
      state.data = state.data.filter((m) => m.id !== action.payload);
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(fetchTourGuideHistory.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(fetchTourGuideHistory.fulfilled, (state, action) => {
        // Server data replaces the slice, but keep optimistic messages still in flight.
        const inFlight = state.data.filter((m) => m.pending);
        state.data = [...action.payload, ...inFlight];
        state.loading = false;
        state.isInitialized = true;
        state.error = null;
        state.lastFetchedAt = Date.now();
      })
      .addCase(fetchTourGuideHistory.rejected, (state, action) => {
        if (action.payload === STALE) return;
        state.loading = false;
        state.error = action.payload || 'Failed to fetch guide history';
      });
  },
});

export const tourGuideSlice = slice;
export const {
  appendGuideMessage,
  removeGuideMessage,
  clear: resetGuideHistory,
  invalidate: invalidateGuideHistory,
} = slice.actions;
export default slice.reducer;
