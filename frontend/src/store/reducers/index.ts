import { combineReducers } from '@reduxjs/toolkit';
import tourGuideReducer from './tourGuideSlice';
import nearbyReducer from './nearbySlice';
import mapPlacesReducer from './mapPlacesSlice';
import tripsReducer from './tripsSlice';

export const rootReducer = combineReducers({
  tourGuide: tourGuideReducer,
  nearby: nearbyReducer,
  mapPlaces: mapPlacesReducer,
  trips: tripsReducer,
});

export * from './tourGuideSlice';
export * from './nearbySlice';
export * from './mapPlacesSlice';
export * from './tripsSlice';
