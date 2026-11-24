import React, { createContext, useContext, useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useStore } from 'react-redux';
import type { Trip, TripDraft, CreateTripPayload, TripStatus, Itinerary, ItineraryStatus, TripStay, TripTransport, TripExpense } from './types';
import { tripRepository } from './tripRepository';
import { useAuth } from '../../auth/AuthContext';
import { wsClient } from '../../services/wsClient';
import { useSyncRevalidation } from '../../utils/useSyncRevalidation';
import { getApiBaseUrl, fetchWithAuth } from '../../config/apiConfig';
import { useAppDispatch, useAppSelector } from '../../store/hooks';
import type { RootState } from '../../store/store';
import { fetchUserTrips, setTrips, upsertTrip, invalidateTrips } from '../../store/reducers/tripsSlice';
import {
  fetchTripDetail,
  fetchTripPackage,
  upsertTripDetail,
  selectTripDetail,
  type TripDetail,
} from '../../store/reducers/tripDetailsSlice';

interface TripContextType {
  trips: Trip[];
  currentTrip: Trip | null;
  currentTripId: string | null;
  currentItinerary: Itinerary | null;
  itineraryStatus: ItineraryStatus;
  stays: TripStay[];
  transports: TripTransport[];
  expenses: TripExpense[];
  draft: TripDraft | null;
  isLoading: boolean;
  createTrip: (payload: CreateTripPayload) => Promise<Trip>;
  regenerateItinerary: (tripId: string) => Promise<void>;
  updateTripStatus: (tripId: string, status: TripStatus) => Promise<void>;
  deleteTrip: (tripId: string) => Promise<void>;
  cancelTrip: (tripId: string) => Promise<void>;
  archiveTrip: (tripId: string) => Promise<void>;
  setCurrentTripId: (tripId: string | null) => void;
  saveDraft: (draft: TripDraft) => void;
  discardDraft: () => void;
  addStay: (payload: Partial<TripStay>) => Promise<TripStay>;
  addTransport: (payload: Partial<TripTransport>) => Promise<TripTransport>;
  addExpense: (payload: Partial<TripExpense>) => Promise<TripExpense>;
  fetchPackageData: (tripId: string) => Promise<void>;
  swapActivity: (tripId: string, activityId: string, payload: { itineraryId?: string; dayId?: string; replacement: any }) => Promise<void>;
  refetchItinerary: (tripId?: string) => Promise<void>;
  optimizeDayItinerary: (tripId: string, dayId: string, goal?: string) => Promise<any>;
  optimizeBudget: (tripId: string) => Promise<any>;
  weatherReplan: (tripId: string) => Promise<any>;
  executeRefinement: (tripId: string, actions: any[]) => Promise<any>;
  setActivityDone: (tripId: string, activityId: string, done: boolean) => Promise<void>;
  /** The trip's total budget (rupees). WS trips:set_budget, REST fallback; throws with a message if not saved. */
  setTripBudget: (tripId: string, amount: number) => Promise<void>;
  readyNotice: ItineraryReadyNotice | null;
  dismissReadyNotice: () => void;
}

export interface ItineraryReadyNotice {
  tripId: string;
  tripTitle: string;
  status: 'READY' | 'FAILED';
}

const TripContext = createContext<TripContextType | undefined>(undefined);

// Stable references so consumers don't re-render when a trip has no package data yet.
const NO_STAYS: TripStay[] = [];
const NO_TRANSPORTS: TripTransport[] = [];
const NO_EXPENSES: TripExpense[] = [];

const withActivityDone = (itinerary: Itinerary, activityId: string, isDone: boolean): Itinerary => ({
  ...itinerary,
  days: itinerary.days.map(d => ({
    ...d,
    activities: d.activities.map(a => (a.id === activityId ? { ...a, isDone } : a)),
  })),
});

/**
 * Trip state lives in Redux (`trips`, `tripDetails` slices: cached, persisted, TTL-revalidated).
 * This provider keeps the public `useTrip()` API and owns only UI-level state: the selected trip,
 * the draft, the ready notice and the itinerary status.
 */
export const TripProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { authUser, isAuthenticated } = useAuth();
  const dispatch = useAppDispatch();
  const store = useStore<RootState>();

  const trips = useAppSelector(s => s.trips.data);
  const tripsInitialized = useAppSelector(s => s.trips.isInitialized);

  const [currentTripId, setCurrentTripIdState] = useState<string | null>(null);
  const [itineraryStatus, setItineraryStatus] = useState<ItineraryStatus>('READY');
  const [draft, setDraftState] = useState<TripDraft | null>(null);
  const [readyNotice, setReadyNotice] = useState<ItineraryReadyNotice | null>(null);
  const [bootstrapped, setBootstrapped] = useState(false);
  const [creating, setCreating] = useState(false);

  const userId = authUser?.id;

  const detail = useAppSelector(s => selectTripDetail(s, currentTripId));
  const currentItinerary = detail?.itinerary ?? null;
  const stays = detail?.stays ?? NO_STAYS;
  const transports = detail?.transports ?? NO_TRANSPORTS;
  const expenses = detail?.expenses ?? NO_EXPENSES;

  const tripsRef = useRef(trips);
  tripsRef.current = trips;

  // Mirror the server-reported itinerary status.
  useEffect(() => {
    if (currentItinerary?.status) setItineraryStatus(currentItinerary.status);
  }, [currentItinerary]);

  const refetchItinerary = useCallback(async (targetTripId?: string) => {
    const tid = targetTripId || currentTripId;
    if (!tid) return;
    // Callers invoke this after changing an itinerary, so list-level data (progress, counts) is stale too.
    dispatch(invalidateTrips());
    await dispatch(fetchTripDetail({ tripId: tid, force: true }));
  }, [currentTripId, dispatch]);

  const fetchPackageData = useCallback(async (tripId: string) => {
    if (!tripId) return;
    await dispatch(fetchTripPackage({ tripId, force: true }));
  }, [dispatch]);

  // Load the trip list when the user session changes. Cached data (hydrated from localStorage)
  // is shown immediately; the thunk only hits the network when the cache is stale.
  useEffect(() => {
    if (!isAuthenticated || !userId) {
      setCurrentTripIdState(null);
      setDraftState(null);
      setBootstrapped(false);
      return;
    }
    let cancelled = false;
    dispatch(fetchUserTrips({})).finally(() => {
      if (!cancelled) setBootstrapped(true);
    });
    return () => { cancelled = true; };
  }, [isAuthenticated, userId, dispatch]);

  // Keep the selection valid as the list changes (first load, deletion, a purge).
  useEffect(() => {
    if (!isAuthenticated || !userId) return;
    if (trips.length === 0) {
      if (tripsInitialized && currentTripId) setCurrentTripIdState(null);
      return;
    }
    if (currentTripId && trips.some(t => t.id === currentTripId)) return;
    const preferredId = tripRepository.getCurrentTripId(userId);
    setCurrentTripIdState(tripRepository.selectCurrentTripId(trips, preferredId));
  }, [trips, tripsInitialized, currentTripId, isAuthenticated, userId]);

  const currentTrip = useMemo(() => {
    if (!currentTripId) return null;
    return trips.find(t => t.id === currentTripId) ?? null;
  }, [trips, currentTripId]);

  // Load itinerary + package data for the selected trip (TTL-gated; instant when cached).
  useEffect(() => {
    if (!currentTripId) return;
    dispatch(fetchTripDetail({ tripId: currentTripId }));
    dispatch(fetchTripPackage({ tripId: currentTripId }));
  }, [currentTripId, dispatch]);

  // ── "Itinerary ready" notice: for any of the user's trips, wherever they are in the app ──
  useEffect(() => {
    if (!isAuthenticated) return;
    const handleReadyNotice = (payload: any) => {
      const tripId = payload?.trip_id || payload?.tripId;
      if (!tripId) return;
      const status: 'READY' | 'FAILED' = payload?.status === 'FAILED' ? 'FAILED' : 'READY';
      const trip = tripsRef.current.find(t => t.id === tripId);
      if (trip) dispatch(upsertTrip({ ...trip, itineraryStatus: status }));
      setReadyNotice(prev => ({
        tripId,
        tripTitle: trip?.title || prev?.tripTitle || 'Your trip',
        status,
      }));
    };
    return wsClient.on('ITINERARY_READY', handleReadyNotice);
  }, [isAuthenticated, dispatch]);

  const dismissReadyNotice = useCallback(() => setReadyNotice(null), []);

  // ── Reactive WebSocket event listeners for the selected trip ──
  useEffect(() => {
    if (!currentTripId) return;

    const handleItineraryReady = (payload: any) => {
      const payloadTripId = payload?.trip_id || payload?.tripId || payload?.id;
      if (!payloadTripId || payloadTripId === currentTripId) {
        const finalStatus = payload?.status === 'FAILED' ? 'FAILED' : 'READY';
        setItineraryStatus(finalStatus);
        const trip = tripsRef.current.find(t => t.id === currentTripId);
        if (trip) dispatch(upsertTrip({ ...trip, itineraryStatus: finalStatus }));
        if (finalStatus === 'READY') dispatch(fetchTripDetail({ tripId: currentTripId, force: true }));
      }
    };

    const handleTripUpdated = (payload: any) => {
      const payloadTripId = payload?.trip_id || payload?.tripId || payload?.id;
      if (!payloadTripId || payloadTripId === currentTripId) {
        dispatch(fetchTripDetail({ tripId: currentTripId, force: true }));
      }
    };

    const unsubscribeReady = wsClient.on('ITINERARY_READY', handleItineraryReady);
    const unsubscribeUpdated = wsClient.on('TRIP_UPDATED', handleTripUpdated);
    const unsubscribeGenCompleted = wsClient.on('trips:generation_completed', handleItineraryReady);

    return () => {
      unsubscribeReady();
      unsubscribeUpdated();
      unsubscribeGenCompleted();
    };
  }, [currentTripId, dispatch]);

  // ── Debounced window-focus revalidation of the selected itinerary ──
  useEffect(() => {
    let timeoutId: any;
    const onFocus = () => {
      clearTimeout(timeoutId);
      timeoutId = setTimeout(() => {
        if (!isAuthenticated || !userId || !currentTripId) return;
        dispatch(fetchTripDetail({ tripId: currentTripId, force: true }));
      }, 1000);
    };

    window.addEventListener('focus', onFocus);
    return () => {
      window.removeEventListener('focus', onFocus);
      clearTimeout(timeoutId);
    };
  }, [isAuthenticated, userId, currentTripId, dispatch]);

  // ── Window focus revalidation of the trip list (throttled to 30s) ──
  useSyncRevalidation({
    throttleMs: 30000,
    onFocus: useCallback(() => {
      if (!isAuthenticated || !userId) return;
      dispatch(fetchUserTrips({ force: true }));
    }, [isAuthenticated, userId, dispatch]),
  });

  /** Re-fetch the selected trip's package data after a stay/transport/expense is saved. */
  const reconcilePackage = useCallback((tripId: string) => {
    dispatch(fetchTripPackage({ tripId, force: true }));
  }, [dispatch]);

  const prependToDetail = useCallback((
    tripId: string,
    key: 'stays' | 'transports' | 'expenses',
    item: TripStay | TripTransport | TripExpense,
  ) => {
    const existing = selectTripDetail(store.getState(), tripId);
    const list = (existing?.[key] as Array<TripStay | TripTransport | TripExpense> | undefined) ?? [];
    dispatch(upsertTripDetail({
      fetchedAt: 0,
      ...existing,
      tripId,
      [key]: [item, ...list],
    } as TripDetail));
  }, [dispatch, store]);

  const addStay = useCallback(async (payload: Partial<TripStay>): Promise<TripStay> => {
    if (!currentTripId) throw new Error('No active trip selected');
    let newStay: TripStay;
    try {
      newStay = await wsClient.sendRequest('trips:add_stay', { ...payload, trip_id: currentTripId });
    } catch (err) {
      console.error('Could not save stay:', err);
      throw err instanceof Error ? err : new Error('Could not save stay. Please try again.');
    }
    prependToDetail(currentTripId, 'stays', newStay);
    reconcilePackage(currentTripId);
    return newStay;
  }, [currentTripId, prependToDetail, reconcilePackage]);

  const addTransport = useCallback(async (payload: Partial<TripTransport>): Promise<TripTransport> => {
    if (!currentTripId) throw new Error('No active trip selected');
    let newTransport: TripTransport;
    try {
      newTransport = await wsClient.sendRequest('trips:add_transport', { ...payload, trip_id: currentTripId });
    } catch (err) {
      console.error('Could not save transport:', err);
      throw err instanceof Error ? err : new Error('Could not save transport. Please try again.');
    }
    prependToDetail(currentTripId, 'transports', newTransport);
    reconcilePackage(currentTripId);
    return newTransport;
  }, [currentTripId, prependToDetail, reconcilePackage]);

  const addExpense = useCallback(async (payload: Partial<TripExpense>): Promise<TripExpense> => {
    if (!currentTripId) throw new Error('No active trip selected');
    let newExpense: TripExpense;
    try {
      newExpense = await wsClient.sendRequest('trips:add_expense', { ...payload, trip_id: currentTripId });
    } catch (err) {
      console.error('Could not save expense:', err);
      throw err instanceof Error ? err : new Error('Could not save expense. Please try again.');
    }
    prependToDetail(currentTripId, 'expenses', newExpense);
    reconcilePackage(currentTripId);
    return newExpense;
  }, [currentTripId, prependToDetail, reconcilePackage]);

  const setCurrentTripId = useCallback((id: string | null) => {
    setCurrentTripIdState(id);
    tripRepository.setCurrentTripId(id, userId);
  }, [userId]);

  const saveDraft = useCallback((draftData: TripDraft) => {
    setDraftState(draftData);
    tripRepository.saveDraft(draftData, userId);
  }, [userId]);

  const discardDraft = useCallback(() => {
    setDraftState(null);
    tripRepository.clearDraft(userId);
  }, [userId]);

  const createTrip = useCallback(async (payload: CreateTripPayload): Promise<Trip> => {
    const clientRequestId = payload.clientRequestId || `req_${Date.now()}`;

    const todayStr = new Date().toISOString().split('T')[0];
    if (payload.startDate < todayStr) {
      throw new Error('Trip start date cannot be in the past.');
    }
    if (payload.endDate < payload.startDate) {
      throw new Error('Trip end date cannot be earlier than start date.');
    }

    setCreating(true);
    let createdTrip: Trip;

    try {
      try {
        createdTrip = await wsClient.sendRequest('trips:create', { ...payload, clientRequestId });
      } catch (wsErr) {
        console.warn('WebSocket trip creation failed, retrying over HTTP.', wsErr);
        try {
          const res = await fetchWithAuth(`${getApiBaseUrl()}/api/trips`, {
            method: 'POST',
            body: JSON.stringify({ ...payload, clientRequestId }),
          });
          if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            throw new Error(errData.detail || 'Could not create the trip. Please try again.');
          }
          createdTrip = await res.json();
        } catch (httpErr) {
          throw httpErr instanceof Error ? httpErr : new Error('Could not create the trip. Please try again.');
        }
      }

      // Reconcile: show the new trip now, then confirm against the server in the background.
      const existing = store.getState().trips.data.filter(t => t.id !== createdTrip.id);
      dispatch(setTrips([createdTrip, ...existing]));
      setCurrentTripIdState(createdTrip.id);
      tripRepository.setCurrentTripId(createdTrip.id, userId);
      discardDraft();
      dispatch(fetchUserTrips({ force: true }));

      return createdTrip;
    } finally {
      setCreating(false);
    }
  }, [userId, dispatch, store, discardDraft]);

  const regenerateItinerary = useCallback(async (tripId: string) => {
    setItineraryStatus('GENERATING');
    const trip = store.getState().trips.data.find(t => t.id === tripId);
    if (trip) dispatch(upsertTrip({ ...trip, itineraryStatus: 'GENERATING' }));

    try {
      await wsClient.sendRequest('trips:regenerate_itinerary', { trip_id: tripId, instruction: 'Re-generate package itinerary' });
    } catch (err) {
      console.warn('WebSocket regeneration request failed:', err);
    }
  }, [dispatch, store]);

  // Status changes are local-only (there is no backend endpoint for them).
  const updateTripStatus = useCallback(async (tripId: string, status: TripStatus) => {
    const existing = store.getState().trips.data.find(t => t.id === tripId);
    if (!existing) return;

    if (!tripRepository.validateStatusTransition(existing.status, status)) {
      console.warn(`Invalid status transition from ${existing.status} to ${status}`);
      return;
    }

    dispatch(upsertTrip({ ...existing, status, updatedAt: new Date().toISOString() }));
  }, [dispatch, store]);

  const deleteTrip = useCallback(async (tripId: string) => {
    const previous = store.getState().trips.data;
    if (!previous.some(t => t.id === tripId)) return;

    // Optimistic removal; restored if the server rejects it.
    dispatch(setTrips(previous.filter(t => t.id !== tripId)));

    try {
      try {
        await wsClient.sendRequest('trips:delete', { trip_id: tripId });
      } catch (wsErr) {
        console.warn('WebSocket trips:delete failed, trying HTTP fallback...', wsErr);
        const res = await fetchWithAuth(`${getApiBaseUrl()}/api/trips/${tripId}`, { method: 'DELETE' });
        if (!res.ok) throw new Error('Could not delete the trip. Please try again.');
      }
    } catch (err) {
      console.error('Failed to delete trip from backend database:', err);
      // Only restore if the store still belongs to this session (a purge would have emptied it).
      if (store.getState().trips.isInitialized) dispatch(setTrips(previous));
      throw err instanceof Error ? err : new Error('Could not delete the trip. Please try again.');
    }

    // The selection effect picks the next trip if the deleted one was selected.
    if (currentTripId === tripId) {
      tripRepository.setCurrentTripId(null, userId);
      setCurrentTripIdState(null);
    }
  }, [currentTripId, userId, dispatch, store]);

  const cancelTrip = useCallback(async (tripId: string) => {
    await updateTripStatus(tripId, 'CANCELLED');
  }, [updateTripStatus]);

  const archiveTrip = useCallback(async (tripId: string) => {
    await updateTripStatus(tripId, 'ARCHIVED');
  }, [updateTripStatus]);

  /** After an itinerary-changing mutation: refresh the itinerary and mark the trip list stale. */
  const reconcileItinerary = useCallback(async (tripId: string) => {
    dispatch(invalidateTrips());
    await dispatch(fetchTripDetail({ tripId, force: true }));
  }, [dispatch]);

  const swapActivity = useCallback(async (
    tripId: string,
    activityId: string,
    payload: { itineraryId?: string; dayId?: string; replacement: any }
  ): Promise<void> => {
    try {
      await wsClient.sendRequest('trips:swap_activity', { trip_id: tripId, activity_id: activityId, ...payload });
    } catch (wsErr) {
      console.warn('WebSocket swap_activity failed, trying HTTP PATCH fallback...', wsErr);
      try {
        const res = await fetchWithAuth(`${getApiBaseUrl()}/api/trips/${tripId}/itinerary/activities/${activityId}`, {
          method: 'PATCH',
          body: JSON.stringify(payload),
        });
        if (!res.ok) {
          // e.g. place_outside_trip_area: the caller shows the server's words, never "swapped".
          const detail = (await res.json().catch(() => null))?.detail;
          throw new Error(typeof detail === 'string' ? detail : "Couldn't swap this activity. Please try again.");
        }
      } catch (httpErr) {
        console.error('HTTP swap_activity fallback failed:', httpErr);
        throw httpErr;
      }
    }
    await reconcileItinerary(tripId);
  }, [reconcileItinerary]);

  const optimizeDayItinerary = useCallback(async (tripId: string, dayId: string, goal: string = 'MINIMIZE_TRAVEL_TIME'): Promise<any> => {
    const data = await wsClient.sendRequest('trips:optimize_day', { trip_id: tripId, day_id: dayId, goal });
    await reconcileItinerary(tripId);
    return data;
  }, [reconcileItinerary]);

  const optimizeBudget = useCallback(async (tripId: string): Promise<any> => {
    return wsClient.sendRequest('trips:optimize_budget', { trip_id: tripId });
  }, []);

  const weatherReplan = useCallback(async (tripId: string): Promise<any> => {
    return wsClient.sendRequest('trips:weather_replan', { trip_id: tripId });
  }, []);

  const setActivityDone = useCallback(async (tripId: string, activityId: string, done: boolean): Promise<void> => {
    const before = selectTripDetail(store.getState(), tripId);
    // Optimistic toggle; reverted below if the server call fails.
    if (before?.itinerary) {
      dispatch(upsertTripDetail({ ...before, itinerary: withActivityDone(before.itinerary, activityId, done) }));
    }

    let res: any;
    try {
      res = await wsClient.sendRequest('trips:set_activity_done', { trip_id: tripId, activity_id: activityId, done });
    } catch (err) {
      const current = selectTripDetail(store.getState(), tripId);
      if (before?.itinerary && current) {
        dispatch(upsertTripDetail({ ...current, itinerary: before.itinerary }));
      }
      throw err;
    }

    // Server is the source of truth for the final value and the trip's progress.
    const current = selectTripDetail(store.getState(), tripId);
    if (current?.itinerary && typeof res?.isDone === 'boolean' && res.isDone !== done) {
      dispatch(upsertTripDetail({ ...current, itinerary: withActivityDone(current.itinerary, activityId, res.isDone) }));
    }
    const trip = store.getState().trips.data.find(t => t.id === tripId);
    if (trip && res?.progress) {
      dispatch(upsertTrip({ ...trip, progress: res.progress }));
    } else {
      dispatch(invalidateTrips());
    }
  }, [dispatch, store]);

  const setTripBudget = useCallback(async (tripId: string, amount: number): Promise<void> => {
    let res: any;
    try {
      res = await wsClient.sendRequest('trips:set_budget', { trip_id: tripId, amount });
    } catch {
      // WS down or refused: the REST route gives the same answer (a refusal comes back as a 400 with the reason).
      const http = await fetchWithAuth(`${getApiBaseUrl()}/api/trips/${tripId}/budget`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ amount }),
      });
      const body = await http.json().catch(() => ({}));
      if (!http.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'Could not save the budget. Please try again.');
      res = body;
    }
    const trip = store.getState().trips.data.find(t => t.id === tripId);
    if (res?.trip?.id === tripId) dispatch(upsertTrip(res.trip));
    else if (trip && res?.budget) dispatch(upsertTrip({ ...trip, budget: res.budget }));
    else dispatch(fetchUserTrips({ force: true }));
  }, [dispatch, store]);

  const executeRefinement = useCallback(async (tripId: string, actions: any[]): Promise<any> => {
    const data = await wsClient.sendRequest('trips:refine', { trip_id: tripId, actions });
    await reconcileItinerary(tripId);
    return data;
  }, [reconcileItinerary]);

  const isLoading = creating || (isAuthenticated && !bootstrapped && trips.length === 0);

  return (
    <TripContext.Provider value={{
      trips,
      currentTrip,
      currentTripId,
      currentItinerary,
      itineraryStatus,
      stays,
      transports,
      expenses,
      draft,
      isLoading,
      createTrip,
      regenerateItinerary,
      updateTripStatus,
      deleteTrip,
      cancelTrip,
      archiveTrip,
      setCurrentTripId,
      saveDraft,
      discardDraft,
      addStay,
      addTransport,
      addExpense,
      fetchPackageData,
      swapActivity,
      refetchItinerary,
      optimizeDayItinerary,
      optimizeBudget,
      weatherReplan,
      executeRefinement,
      setActivityDone,
      setTripBudget,
      readyNotice,
      dismissReadyNotice,
    }}>
      {children}
    </TripContext.Provider>
  );
};

export const useTrip = () => {
  const ctx = useContext(TripContext);
  if (!ctx) throw new Error('useTrip must be used within a TripProvider');
  return ctx;
};
