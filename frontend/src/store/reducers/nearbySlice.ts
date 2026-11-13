import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import axios from 'axios';
import { getApiBaseUrl, getAuthHeaders } from '../../config/apiConfig';

export interface Place {
  id: string;
  name: string;
  category: string;
  latitude: number;
  longitude: number;
  rating?: number;
  is_mock?: boolean;
  _isMock?: boolean;
  distanceMeters?: number;
  address?: string;
  description?: string;
  [key: string]: any;
}

export interface NearbyParams {
  lat: number;
  lng: number;
  radius?: number;
  force?: boolean;
}

export const calculateDistanceKm = (lat1: number, lon1: number, lat2: number, lon2: number): number => {
  const p = 0.017453292519943295; // Math.PI / 180
  const c = Math.cos;
  const a = 0.5 - c((lat2 - lat1) * p) / 2 +
            c(lat1 * p) * c(lat2 * p) * (1 - c((lon2 - lon1) * p)) / 2;
  return 12742 * Math.asin(Math.sqrt(a));
};

export const fetchNearbyPlaces = createAsyncThunk(
  'nearby/fetchPlaces',
  async ({ lat, lng, radius = 5000 }: NearbyParams, { rejectWithValue }) => {
    try {
      const baseUrl = getApiBaseUrl();
      const url = `${baseUrl}/api/tour-guide/nearby`;
      const res = await axios.get(url, {
        params: { lat, lng, radius },
        withCredentials: true,
        headers: getAuthHeaders(),
      });
      return {
        places: res.data.places || [],
        center: res.data.center || { latitude: lat, longitude: lng },
        radius_m: res.data.radius_m || radius,
      };
    } catch (err: any) {
      return rejectWithValue(err.response?.data?.detail || 'Failed to fetch nearby spots');
    }
  },
  {
    // Guard: Skip network call if user is within 500m of previous fetched center
    condition: ({ lat, lng, force }: NearbyParams, { getState }: any) => {
      if (force) return true;
      const { nearby } = getState() as { nearby: NearbyState };
      if (nearby.loading) return false;

      if (nearby.center && nearby.places.length > 0) {
        const distKm = calculateDistanceKm(
          nearby.center.latitude,
          nearby.center.longitude,
          lat,
          lng
        );
        if (distKm < 0.5) return false;
      }
      return true;
    },
  }
);

export interface NearbyState {
  places: Place[];
  center: { latitude: number; longitude: number } | null;
  radius_m: number;
  loading: boolean;
  error: string | null;
}

const initialState: NearbyState = {
  places: [],
  center: null,
  radius_m: 5000,
  loading: false,
  error: null,
};

export const nearbySlice = createSlice({
  name: 'nearby',
  initialState,
  reducers: {
    clearNearby: (state) => {
      state.places = [];
      state.center = null;
      state.error = null;
    },
    clearNearbyCache: (state) => {
      state.places = [];
      state.center = null;
      state.error = null;
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(fetchNearbyPlaces.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(fetchNearbyPlaces.fulfilled, (state, action) => {
        state.loading = false;
        state.places = action.payload.places;
        state.center = action.payload.center;
        state.radius_m = action.payload.radius_m;
        state.error = null;
      })
      .addCase(fetchNearbyPlaces.rejected, (state, action: any) => {
        state.loading = false;
        state.error = action.payload || 'Failed to fetch nearby places';
      });
  },
});

export const { clearNearby, clearNearbyCache } = nearbySlice.actions;
export default nearbySlice.reducer;
