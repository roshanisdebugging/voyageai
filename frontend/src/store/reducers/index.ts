import { combineReducers } from '@reduxjs/toolkit';
import tourGuideReducer from './tourGuideSlice';
import nearbyReducer from './nearbySlice';
import mapPlacesReducer from './mapPlacesSlice';
import tripsReducer from './tripsSlice';
import tripDetailsReducer from './tripDetailsSlice';
import savedPlacesReducer from './savedPlacesSlice';

export const rootReducer = combineReducers({
  tourGuide: tourGuideReducer,
  nearby: nearbyReducer,
  mapPlaces: mapPlacesReducer,
  trips: tripsReducer,
  tripDetails: tripDetailsReducer,
  savedPlaces: savedPlacesReducer,
});

export * from './tourGuideSlice';
export * from './nearbySlice';
export * from './mapPlacesSlice';
export * from './tripsSlice';
export * from './tripDetailsSlice';
export * from './savedPlacesSlice';
