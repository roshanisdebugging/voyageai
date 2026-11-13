import { createSlice, createAsyncThunk, type PayloadAction } from '@reduxjs/toolkit';
import axios from 'axios';
import { getApiBaseUrl, getAuthHeaders } from '../../config/apiConfig';

export interface Trip {
  id: string;
  userId?: string;
  title: string;
  status: 'PLANNING' | 'CONFIRMED' | 'COMPLETED' | 'ARCHIVED';
  itineraryStatus?: string;
  startDate: string;
  endDate: string;
  totalDays?: number;
  destination?: {
    name: string;
    city?: string;
    state?: string;
    country?: string;
    latitude?: number;
    longitude?: number;
  };
  coverMedia?: {
    url: string;
    alt?: string;
  };
  progress?: {
    completedActivitiesCount: number;
    totalActivitiesCount: number;
  };
  [key: string]: any;
}

export interface TripsState {
  trips: Trip[];
  activeTab: 'active' | 'upcoming' | 'completed' | 'archived';
  loading: boolean;
  isInitialized: boolean;
  error: string | null;
}

const initialState: TripsState = {
  trips: [],
  activeTab: 'active',
  loading: false,
  isInitialized: false,
  error: null,
};

export const fetchUserTrips = createAsyncThunk(
  'trips/fetchUserTrips',
  async (_force: boolean = false, { rejectWithValue }) => {
    try {
      const baseUrl = getApiBaseUrl();
      const url = `${baseUrl}/api/trips`;
      const res = await axios.get(url, {
        withCredentials: true,
        headers: getAuthHeaders(),
      });
      const data = res.data;
      return Array.isArray(data) ? data : data.trips || [];
    } catch (err: any) {
      return rejectWithValue(err.response?.data?.detail || 'Failed to fetch user trips');
    }
  },
  {
    condition: (force, { getState }: any) => {
      if (force) return true;
      const { trips } = getState() as { trips: TripsState };
      if (trips.isInitialized || trips.loading) return false;
      return true;
    },
  }
);

export const tripsSlice = createSlice({
  name: 'trips',
  initialState,
  reducers: {
    setActiveTab: (state, action: PayloadAction<TripsState['activeTab']>) => {
      state.activeTab = action.payload;
    },
    updateTripStatusLocally: (state, action: PayloadAction<{ tripId: string; status: Trip['status'] }>) => {
      const trip = state.trips.find(t => t.id === action.payload.tripId);
      if (trip) trip.status = action.payload.status;
    },
    clearTrips: (state) => {
      state.trips = [];
      state.isInitialized = false;
      state.error = null;
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(fetchUserTrips.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(fetchUserTrips.fulfilled, (state, action: PayloadAction<Trip[]>) => {
        state.loading = false;
        state.isInitialized = true;
        state.trips = action.payload;
        state.error = null;
      })
      .addCase(fetchUserTrips.rejected, (state, action: any) => {
        state.loading = false;
        state.error = action.payload || 'Failed to fetch user trips';
      });
  },
});

export const { setActiveTab, updateTripStatusLocally, clearTrips } = tripsSlice.actions;
export default tripsSlice.reducer;
