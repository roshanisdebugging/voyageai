import { createSlice, createAsyncThunk, type PayloadAction } from '@reduxjs/toolkit';
import axios from 'axios';
import { getApiBaseUrl, getAuthHeaders } from '../../config/apiConfig';
import { calculateDistanceKm } from './nearbySlice';

export interface MapNearbyParams {
  lat: number;
  lng: number;
  radius?: number;
  limit?: number;
  category?: string;
  force?: boolean;
}


export const fetchMapNearbyPlaces = createAsyncThunk(
  'mapPlaces/fetchNearby',
  async ({ lat, lng, radius = 5000, limit = 40, category = 'all' }: MapNearbyParams, { rejectWithValue }) => {
    try {
      const baseUrl = getApiBaseUrl();
      const categoryParam = category !== 'all' ? `&category=${encodeURIComponent(category)}` : '';
      const url = `${baseUrl}/api/places/nearby?lat=${lat}&lng=${lng}&radius=${radius}&limit=${limit}${categoryParam}`;

      const res = await axios.get(url, {
        withCredentials: true,
        headers: getAuthHeaders(),
      });

      const data = res.data;
      const rawItems = Array.isArray(data)
        ? data
        : (data.places || data.results || []);

      return {
        places: rawItems,
        center: { lat, lng },
        radius,
        category,
      };
    } catch (err: any) {
      return rejectWithValue(err.response?.data?.detail || 'Failed to fetch map places');
    }
  },
  {
    condition: ({ lat, lng, category = 'all', force }: MapNearbyParams, { getState }: any) => {
      if (force) return true;
      const { mapPlaces } = getState() as { mapPlaces: MapPlacesState };
      if (mapPlaces.loading) return false;

      if (mapPlaces.center && mapPlaces.places.length > 0) {
        const distKm = calculateDistanceKm(
          mapPlaces.center.lat,
          mapPlaces.center.lng,
          lat,
          lng
        );
        if (distKm < 0.5 && (category === mapPlaces.category || category === 'all')) {
          return false;
        }
      }
      return true;
    },
  }
);

export interface MapPlacesState {
  places: any[];
  center: { lat: number; lng: number } | null;
  radius: number;
  category: string;
  loading: boolean;
  selectedPlaceId: string | null;
  error: string | null;
  lastFetchedAt: number | null;
}

const initialState: MapPlacesState = {
  places: [],
  center: null,
  radius: 5000,
  category: 'all',
  loading: false,
  selectedPlaceId: null,
  error: null,
  lastFetchedAt: null,
};

export const mapPlacesSlice = createSlice({
  name: 'mapPlaces',
  initialState,
  reducers: {
    setSelectedPlaceId: (state, action: PayloadAction<string | null>) => {
      state.selectedPlaceId = action.payload;
    },
    clearMapPlaces: (state) => {
      state.places = [];
      state.center = null;
      state.selectedPlaceId = null;
      state.lastFetchedAt = null;
      state.error = null;
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(fetchMapNearbyPlaces.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(fetchMapNearbyPlaces.fulfilled, (state, action) => {
        state.loading = false;
        state.places = action.payload.places;
        state.center = action.payload.center;
        state.radius = action.payload.radius;
        state.category = action.payload.category;
        state.lastFetchedAt = Date.now();
        state.error = null;
      })
      .addCase(fetchMapNearbyPlaces.rejected, (state, action: any) => {
        state.loading = false;
        state.error = action.payload || 'Failed to fetch map places';
      });
  },
});

export const { setSelectedPlaceId, clearMapPlaces } = mapPlacesSlice.actions;
export default mapPlacesSlice.reducer;
