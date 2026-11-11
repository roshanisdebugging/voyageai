import React, { createContext, useContext, useState, useEffect, useCallback, useMemo } from 'react';
import type { Trip, TripDraft, CreateTripPayload, TripStatus, Itinerary, ItineraryStatus, TripStay, TripTransport, TripExpense } from './types';
import { tripRepository } from './tripRepository';
import { useAuth } from '../../auth/AuthContext';
import { wsClient } from '../../services/wsClient';
import { useSyncRevalidation } from '../../utils/useSyncRevalidation';
import { getApiBaseUrl, DEFAULT_FETCH_OPTIONS, getAuthHeaders } from '../../config/apiConfig';

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
}

const TripContext = createContext<TripContextType | undefined>(undefined);

export const TripProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { userProfile, userPreferences, authUser, isAuthenticated } = useAuth();

  const [trips, setTrips] = useState<Trip[]>([]);
  const [currentTripId, setCurrentTripIdState] = useState<string | null>(null);
  const [currentItinerary, setCurrentItinerary] = useState<Itinerary | null>(null);
  const [itineraryStatus, setItineraryStatus] = useState<ItineraryStatus>('READY');

  const [stays, setStays] = useState<TripStay[]>([]);
  const [transports, setTransports] = useState<TripTransport[]>([]);
  const [expenses, setExpenses] = useState<TripExpense[]>([]);

  const [draft, setDraftState] = useState<TripDraft | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);

  const userId = authUser?.id;

  // Refetch itinerary helper function
  const refetchItinerary = useCallback(async (targetTripId?: string) => {
    const tid = targetTripId || currentTripId;
    if (!tid) return;
    try {
      const data: Itinerary = await wsClient.sendRequest('trips:get_itinerary', { trip_id: tid });
      if (data) {
        setCurrentItinerary(data);
        if (data.status) setItineraryStatus(data.status);
      }
    } catch (err) {
      console.warn('WebSocket failed to refetch itinerary, trying HTTP fallback...', err);
      try {
        const baseUrl = getApiBaseUrl();
        const res = await fetch(`${baseUrl}/api/trips/${tid}/itinerary`, {
          ...DEFAULT_FETCH_OPTIONS
        });
        if (res.ok) {
          const data = await res.json();
          if (data) {
            setCurrentItinerary(data);
            if (data.status) setItineraryStatus(data.status);
          }
        }
      } catch (httpErr) {
        console.error('HTTP refetch itinerary fallback failed:', httpErr);
      }
    }
  }, [currentTripId]);

  // Load user-specific trips when user session changes
  useEffect(() => {
    if (!isAuthenticated || !userId) {
      setTrips([]);
      setCurrentTripIdState(null);
      setCurrentItinerary(null);
      setStays([]);
      setTransports([]);
      setExpenses([]);
      setDraftState(null);
      setIsLoading(false);
      return;
    }

    setIsLoading(true);

    const applyTrips = (fetchedTrips: Trip[]) => {
      if (fetchedTrips && Array.isArray(fetchedTrips) && fetchedTrips.length > 0) {
        setTrips(fetchedTrips);
        const preferredId = tripRepository.getCurrentTripId(userId);
        const selectedId = tripRepository.selectCurrentTripId(fetchedTrips, preferredId);
        setCurrentTripIdState(selectedId);
        return true;
      }
      return false;
    };

    // 1. Immediately request trips via HTTP REST API (/api/trips)
    const baseUrl = getApiBaseUrl();
    fetch(`${baseUrl}/api/trips`, {
      ...DEFAULT_FETCH_OPTIONS,
      credentials: 'include',
      headers: {
        ...getAuthHeaders(),
        'Accept': 'application/json',
      }
    })
      .then(async (res) => {
        if (res.ok) {
          const restTrips = await res.json();
          if (applyTrips(restTrips)) {
            setIsLoading(false);
          }
        }
      })
      .catch((err) => {
        console.warn('[HTTP TRIPS] REST fetch /api/trips error:', err);
      });

    // 2. Fetch and synchronize user trips over WebSocket
    wsClient.sendRequest('trips:list', {})
      .then((fetchedTrips: Trip[]) => {
        if (!applyTrips(fetchedTrips)) {
          setTrips([]);
          setCurrentTripIdState(null);
        }
      })
      .catch((err) => {
        console.warn('[WS TRIPS] trips:list error:', err);
      })
      .finally(() => {
        setIsLoading(false);
      });
  }, [isAuthenticated, userId]);

  // Derived currentTrip state
  const currentTrip = useMemo(() => {
    if (!currentTripId) return null;
    return trips.find(t => t.id === currentTripId) ?? null;
  }, [trips, currentTripId]);

  // Fetch package dimensions (stays, transports, expenses) purely from Backend (WS + REST fallback, ZERO localStorage)
  const fetchPackageData = useCallback(async (tripId: string) => {
    if (!tripId) return;

    try {
      const [fetchedStays, fetchedTransports, fetchedExpenses] = await Promise.all([
        wsClient.sendRequest('trips:get_stays', { trip_id: tripId }),
        wsClient.sendRequest('trips:get_transports', { trip_id: tripId }),
        wsClient.sendRequest('trips:get_expenses', { trip_id: tripId }),
      ]);

      if (Array.isArray(fetchedStays)) {
        setStays(fetchedStays);
      }
      if (Array.isArray(fetchedTransports)) {
        setTransports(fetchedTransports);
      }
      if (Array.isArray(fetchedExpenses)) {
        setExpenses(fetchedExpenses);
      }
    } catch (err) {
      console.warn('[PACKAGE DATA] WebSocket fetch error, falling back to HTTP REST:', err);
      try {
        const baseUrl = getApiBaseUrl();
        const res = await fetch(`${baseUrl}/api/trips/${tripId}`, {
          ...DEFAULT_FETCH_OPTIONS,
          credentials: 'include',
          headers: {
            ...getAuthHeaders(),
            'Accept': 'application/json'
          }
        });
        if (res.ok) {
          const tripDetail = await res.json();
          if (Array.isArray(tripDetail.stays)) setStays(tripDetail.stays);
          if (Array.isArray(tripDetail.transports)) setTransports(tripDetail.transports);
          if (Array.isArray(tripDetail.expenses)) setExpenses(tripDetail.expenses);
        }
      } catch (httpErr) {
        console.error('[PACKAGE DATA] HTTP fallback error:', httpErr);
      }
    }
  }, []);

  useEffect(() => {
    if (currentTripId) {
      fetchPackageData(currentTripId);
    } else {
      setStays([]);
      setTransports([]);
      setExpenses([]);
    }
  }, [currentTripId, fetchPackageData]);

  // ── Reactive WebSocket Event Listeners (No 3-Second Polling) ──
  useEffect(() => {
    if (!currentTripId) return;

    // Fetch initial itinerary on selection
    refetchItinerary(currentTripId);

    const handleItineraryReady = (payload: any) => {
      const payloadTripId = payload?.trip_id || payload?.tripId || payload?.id;
      if (!payloadTripId || payloadTripId === currentTripId) {
        // The worker reports READY or FAILED.
        const finalStatus = payload?.status === 'FAILED' ? 'FAILED' : 'READY';
        setItineraryStatus(finalStatus);
        setTrips(prev => prev.map(t => t.id === currentTripId ? { ...t, itineraryStatus: finalStatus } : t));
        if (finalStatus === 'READY') refetchItinerary(currentTripId);
      }
    };

    const handleTripUpdated = (payload: any) => {
      const payloadTripId = payload?.trip_id || payload?.tripId || payload?.id;
      if (!payloadTripId || payloadTripId === currentTripId) {
        refetchItinerary(currentTripId);
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
  }, [currentTripId, refetchItinerary]);

  // ── Debounced Window Focus Revalidation Stability Shield ──
  useEffect(() => {
    let timeoutId: any;
    const onFocus = () => {
      clearTimeout(timeoutId);
      timeoutId = setTimeout(() => {
        if (!isAuthenticated || !userId || !currentTripId) return;
        console.log('[FOCUS STABILITY] Refreshing itinerary after 1s focus stability...');
        refetchItinerary(currentTripId);
      }, 1000);
    };

    window.addEventListener('focus', onFocus);
    return () => {
      window.removeEventListener('focus', onFocus);
      clearTimeout(timeoutId);
    };
  }, [isAuthenticated, userId, currentTripId, refetchItinerary]);

  // ── Window Focus & Cross-Tab Storage Revalidation (Throttled to 30s) ──
  useSyncRevalidation({
    throttleMs: 30000,
    onFocus: useCallback(() => {
      if (!isAuthenticated || !userId) return;
      console.log('[REVALIDATION] Window focused, refreshing trips & active itinerary...');
      
      const baseUrl = getApiBaseUrl();
      fetch(`${baseUrl}/api/trips`, {
        ...DEFAULT_FETCH_OPTIONS,
        credentials: 'include',
        headers: {
          ...getAuthHeaders(),
          'Accept': 'application/json'
        }
      })
        .then(async (res) => {
          if (res.ok) {
            const data = await res.json();
            if (Array.isArray(data) && data.length > 0) {
              setTrips(data);
            }
          }
        })
        .catch(() => {});

      wsClient.sendRequest('trips:list', {})
        .then((fetchedTrips: Trip[]) => {
          if (fetchedTrips && Array.isArray(fetchedTrips) && fetchedTrips.length > 0) {
            setTrips(fetchedTrips);
          }
        })
        .catch(err => console.warn('[REVALIDATION FOCUS ERROR]', err));

      if (currentTripId) {
        refetchItinerary(currentTripId);
      }
    }, [isAuthenticated, userId, currentTripId, refetchItinerary]),

    onStorageChange: useCallback((key: string | null) => {
      if (!userId) return;
      if (!key || key.includes('voyageai_user_trips') || key.includes('voyageai_current_trip_id')) {
        console.log('[REVALIDATION] Cross-tab storage change detected, syncing trips...');
        const stored = tripRepository.getStoredTrips(userId);
        if (stored.length > 0) {
          setTrips(stored);
        }
        const preferredId = tripRepository.getCurrentTripId(userId);
        if (preferredId && preferredId !== currentTripId) {
          setCurrentTripIdState(preferredId);
        }
      }
    }, [userId, currentTripId])
  });

  const addStay = useCallback(async (payload: Partial<TripStay>): Promise<TripStay> => {
    if (!currentTripId) throw new Error('No active trip selected');

    let newStay: TripStay;
    try {
      newStay = await wsClient.sendRequest('trips:add_stay', { ...payload, trip_id: currentTripId });
    } catch (err) {
      console.error('Could not save stay:', err);
      throw err instanceof Error ? err : new Error('Could not save stay. Please try again.');
    }

    setStays(prev => [newStay, ...prev]);
    return newStay;
  }, [currentTripId]);

  const addTransport = useCallback(async (payload: Partial<TripTransport>): Promise<TripTransport> => {
    if (!currentTripId) throw new Error('No active trip selected');

    let newTransport: TripTransport;
    try {
      newTransport = await wsClient.sendRequest('trips:add_transport', { ...payload, trip_id: currentTripId });
    } catch (err) {
      console.error('Could not save transport:', err);
      throw err instanceof Error ? err : new Error('Could not save transport. Please try again.');
    }

    setTransports(prev => [newTransport, ...prev]);
    return newTransport;
  }, [currentTripId]);

  const addExpense = useCallback(async (payload: Partial<TripExpense>): Promise<TripExpense> => {
    if (!currentTripId) throw new Error('No active trip selected');

    let newExpense: TripExpense;
    try {
      newExpense = await wsClient.sendRequest('trips:add_expense', { ...payload, trip_id: currentTripId });
    } catch (err) {
      console.error('Could not save expense:', err);
      throw err instanceof Error ? err : new Error('Could not save expense. Please try again.');
    }

    setExpenses(prev => [newExpense, ...prev]);
    return newExpense;
  }, [currentTripId]);

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
    setIsLoading(true);
    const clientRequestId = payload.clientRequestId || `req_${Date.now()}`;

    const todayStr = new Date().toISOString().split('T')[0];
    if (payload.startDate < todayStr) {
      setIsLoading(false);
      throw new Error('Trip start date cannot be in the past.');
    }
    if (payload.endDate < payload.startDate) {
      setIsLoading(false);
      throw new Error('Trip end date cannot be earlier than start date.');
    }

    let createdTrip: Trip;

    try {
      createdTrip = await wsClient.sendRequest('trips:create', { ...payload, clientRequestId });
    } catch (wsErr) {
      console.warn('WebSocket trip creation failed, retrying over HTTP.', wsErr);
      try {
        const res = await fetch(`${getApiBaseUrl()}/api/trips`, {
          method: 'POST',
          credentials: 'include',
          headers: getAuthHeaders(),
          body: JSON.stringify({ ...payload, clientRequestId }),
        });
        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.detail || 'Could not create the trip. Please try again.');
        }
        createdTrip = await res.json();
      } catch (httpErr) {
        setIsLoading(false);
        throw httpErr instanceof Error ? httpErr : new Error('Could not create the trip. Please try again.');
      }
    }

    const updatedTrips = [createdTrip, ...trips];
    setTrips(updatedTrips);
    setCurrentTripIdState(createdTrip.id);
    tripRepository.saveStoredTrips(updatedTrips, userId);
    tripRepository.setCurrentTripId(createdTrip.id, userId);
    discardDraft();
    setIsLoading(false);

    return createdTrip;
  }, [userId, userProfile, userPreferences, trips, discardDraft]);

  const regenerateItinerary = useCallback(async (tripId: string) => {
    setItineraryStatus('GENERATING');
    setTrips(prev => prev.map(t => t.id === tripId ? { ...t, itineraryStatus: 'GENERATING' } : t));

    try {
      await wsClient.sendRequest('trips:regenerate_itinerary', { trip_id: tripId, instruction: 'Re-generate package itinerary' });
    } catch (err) {
      console.warn('WebSocket regeneration request failed:', err);
    }
  }, []);

  const updateTripStatus = useCallback(async (tripId: string, status: TripStatus) => {
    const existing = trips.find(t => t.id === tripId);
    if (!existing) return;

    if (!tripRepository.validateStatusTransition(existing.status, status)) {
      console.warn(`Invalid status transition from ${existing.status} to ${status}`);
      return;
    }

    const updatedTrips = trips.map(t =>
      t.id === tripId ? { ...t, status, updatedAt: new Date().toISOString() } : t
    );

    setTrips(updatedTrips);
    tripRepository.saveStoredTrips(updatedTrips, userId);
  }, [trips, userId]);

  const deleteTrip = useCallback(async (tripId: string) => {
    try {
      await wsClient.sendRequest('trips:delete', { trip_id: tripId });
    } catch (err) {
      console.warn('WebSocket trips:delete failed, trying HTTP fallback...', err);
      try {
        const baseUrl = getApiBaseUrl();
        await fetch(`${baseUrl}/api/trips/${tripId}`, {
          ...DEFAULT_FETCH_OPTIONS,
          method: 'DELETE',
        });
      } catch (httpErr) {
        console.error('Failed to delete trip from backend database:', httpErr);
      }
    }

    const updatedTrips = trips.filter(t => t.id !== tripId);
    setTrips(updatedTrips);
    tripRepository.saveStoredTrips(updatedTrips, userId);

    if (currentTripId === tripId) {
      const nextId = tripRepository.selectCurrentTripId(updatedTrips, null);
      setCurrentTripIdState(nextId);
      tripRepository.setCurrentTripId(nextId, userId);
    }
  }, [trips, currentTripId, userId]);

  const cancelTrip = useCallback(async (tripId: string) => {
    await updateTripStatus(tripId, 'CANCELLED');
  }, [updateTripStatus]);

  const archiveTrip = useCallback(async (tripId: string) => {
    await updateTripStatus(tripId, 'ARCHIVED');
  }, [updateTripStatus]);

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
        const baseUrl = getApiBaseUrl();
        await fetch(`${baseUrl}/api/trips/${tripId}/itinerary/activities/${activityId}`, {
          ...DEFAULT_FETCH_OPTIONS,
          method: 'PATCH',
          body: JSON.stringify(payload),
        });
      } catch (httpErr) {
        console.error('HTTP swap_activity fallback failed:', httpErr);
      }
    }
    await refetchItinerary(tripId);
  }, [refetchItinerary]);

  const optimizeDayItinerary = useCallback(async (tripId: string, dayId: string, goal: string = 'MINIMIZE_TRAVEL_TIME'): Promise<any> => {
    const data = await wsClient.sendRequest('trips:optimize_day', { trip_id: tripId, day_id: dayId, goal });
    await refetchItinerary(tripId);
    return data;
  }, [refetchItinerary]);

  const optimizeBudget = useCallback(async (tripId: string): Promise<any> => {
    return wsClient.sendRequest('trips:optimize_budget', { trip_id: tripId });
  }, []);

  const weatherReplan = useCallback(async (tripId: string): Promise<any> => {
    return wsClient.sendRequest('trips:weather_replan', { trip_id: tripId });
  }, []);

  const executeRefinement = useCallback(async (tripId: string, actions: any[]): Promise<any> => {
    const data = await wsClient.sendRequest('trips:refine', { trip_id: tripId, actions });
    await refetchItinerary(tripId);
    return data;
  }, [refetchItinerary]);

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
