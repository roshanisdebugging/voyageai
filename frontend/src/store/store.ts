import { configureStore } from '@reduxjs/toolkit';
import { rootReducer } from './reducers';
import { loadPersistedState, persistMiddleware } from './cache/persist';
import { installAxiosAuthInterceptor } from '../config/apiConfig';

// Central 401 handling for every axios call made by the thunks.
installAxiosAuthInterceptor();

export const store = configureStore({
  reducer: rootReducer,
  // Instant first paint: hydrate cached slices synchronously (never throws; bad cache is discarded).
  preloadedState: loadPersistedState() as Partial<ReturnType<typeof rootReducer>> | undefined,
  middleware: (getDefaultMiddleware) =>
    getDefaultMiddleware({
      serializableCheck: false,
    }).concat(persistMiddleware),
  devTools: import.meta.env.DEV,
});

export type AppDispatch = typeof store.dispatch;
export type RootState = ReturnType<typeof rootReducer>;
