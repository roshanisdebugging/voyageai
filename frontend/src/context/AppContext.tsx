import React, { createContext, useContext, useState, useMemo, useCallback, useEffect, useRef } from 'react';
import type {
  NavTab, TripView, AppUIState, Trip,
  Booking, Expense, NotificationItem, ActivityItem,
  SwapActivityPayload, NavigationTarget
} from '../types';

import { ManualLocationModal } from '../components/common/ManualLocationModal';
import { locationService, reverseGeocodeCoords, type NormalizedLocationPoint } from '../services/locationService';
import { locationSocket } from '../services/locationSocket';
import { wsClient } from '../services/wsClient';
import { sanitizeLocationName } from '../utils/locationSanitizer';


interface AppContextType {
  // Navigation State
  activeTab: NavTab;
  setActiveTab: (tab: NavTab) => void;
  tripView: TripView;
  setTripView: (view: TripView) => void;

  // UI State
  appUIState: AppUIState;
  setAppUIState: (state: AppUIState) => void;

  // Domain State (Persisted)
  activeTrip: Trip;
  setActiveTrip: React.Dispatch<React.SetStateAction<Trip>>;
  bookings: Booking[];
  expenses: Expense[];
  notifications: NotificationItem[];

  userLocation: [number, number] | null;
  userLocationAccuracy: number | null;
  userLocationName: string;
  locationSource: 'gps' | 'manual' | null;
  activeContextMode: 'local' | 'trip';
  setActiveContextMode: (mode: 'local' | 'trip') => void;
  isLocationModalOpen: boolean;
  setIsLocationModalOpen: (open: boolean) => void;
  syncUserLocation: (lat: number, lng: number, accuracyMeters?: number, addressName?: string, source?: 'gps' | 'manual') => Promise<void>;
  requestGPSLocation: () => Promise<void>;

  // Live GPS Tracking
  isLiveTracking: boolean;
  toggleLiveTracking: () => void;
  startLiveTracking: () => void;
  stopLiveTracking: () => void;
  liveTrackingLastUpdated: number | null;
  isFollowMode: boolean;
  setIsFollowMode: (follow: boolean) => void;
  toggleFollowMode: () => void;
  retryGPS: () => Promise<void>;

  // Overlays / Sheets State
  isAiOpen: boolean;
  setIsAiOpen: (open: boolean) => void;
  aiPromptQuery: string;
  setAiPromptQuery: (q: string) => void;
  aiContextLabel: string;

  swapContext: SwapActivityPayload | null;
  setSwapContext: (ctx: SwapActivityPayload | null) => void;
  isSwapModalOpen: boolean;
  setIsSwapModalOpen: (open: boolean) => void;
  openSwapAssistant: (payload: SwapActivityPayload) => void;
  closeSwapAssistant: () => void;

  navigationTarget: NavigationTarget | null;
  setNavigationTarget: (target: NavigationTarget | null) => void;
  openInAppNavigation: (target: NavigationTarget) => void;

  isCabModalOpen: boolean;
  setIsCabModalOpen: (open: boolean) => void;
  cabDestination: string;
  setCabDestination: (dest: string) => void;

  isProfileOpen: boolean;
  setIsProfileOpen: (open: boolean) => void;
  isNotificationsOpen: boolean;
  setIsNotificationsOpen: (open: boolean) => void;
  isFoodSheetOpen: boolean;
  setIsFoodSheetOpen: (open: boolean) => void;
  isEmergencyOpen: boolean;
  setIsEmergencyOpen: (open: boolean) => void;

  // Operations
  addBooking: (booking: Booking) => void;
  cancelBooking: (bookingId: string) => void;
  addExpense: (expense: Omit<Expense, 'id'>) => void;
  optimizeDayItinerary: (dayNumber: number) => void;
  removeActivity: (dayNumber: number, actId: string) => void;
  addActivityToItinerary: (dayNumber: number, activity: Omit<ActivityItem, 'id'>) => void;
  openCabModal: (destinationName?: string) => void;
  openAiAssistant: (query?: string) => void;
  markNotificationAsRead: (id: string) => void;
}

const AppContext = createContext<AppContextType | undefined>(undefined);

import { useTrip } from '../features/trip/TripContext';

export const AppProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { currentTrip, expenses: tripExpenses } = useTrip();

  const [activeTab, setActiveTab] = useState<NavTab>('home');
  const [tripView, setTripView] = useState<TripView>('home');
  const [appUIState, setAppUIState] = useState<AppUIState>('ready');

  // Single Source of Truth: Derive activeTrip cleanly from TripContext's currentTrip
  const activeTrip = useMemo(() => {
    if (currentTrip) {
      return {
        ...currentTrip,
        id: currentTrip.id,
        title: currentTrip.title,
        destination: currentTrip.destination?.name || currentTrip.title,
        // Real numbers only: the trip's budget amount (0 if none) and the sum of its logged expenses.
        budgetTotal: currentTrip.budget?.targetAmount ?? 0,
        budgetSpent: tripExpenses.reduce((sum, e) => sum + (Number(e.amount) || 0), 0),
        // Real count only: adults + children, else the travellers list (0 when unknown).
        travellersCount: ((currentTrip.adultsCount ?? 0) + (currentTrip.childrenCount ?? 0)) || currentTrip.travelers?.length || 0,
        currentDay: currentTrip.progress?.currentDay || 1,
      } as unknown as Trip;
    }
    return null as unknown as Trip;
  }, [currentTrip, tripExpenses]);

  const setActiveTrip = useCallback(() => {
    console.warn('[AppContext] setActiveTrip called. TripContext is the single source of truth for active trip state.');
  }, []);

  // Start empty: no demo bookings, expenses or notifications. Real ones are added as they happen.
  const [bookings, setBookings] = useState<Booking[]>([]);
  const [expenses, setExpenses] = useState<Expense[]>([]);
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);

  const [userLocation, setUserLocation] = useState<[number, number] | null>(null);
  const [userLocationAccuracy, setUserLocationAccuracy] = useState<number | null>(null);
  const [userLocationName, setUserLocationName] = useState<string>('');
  const [locationSource, setLocationSource] = useState<'gps' | 'manual' | null>(null);
  const [activeContextMode, setActiveContextMode] = useState<'local' | 'trip'>('local');
  const [isLocationModalOpen, setIsLocationModalOpen] = useState(false);

  // ── Live Location Tracking State ──
  const [isLiveTracking, setIsLiveTracking] = useState(false);
  const [isFollowMode, setIsFollowMode] = useState(true);
  const [liveTrackingLastUpdated, setLiveTrackingLastUpdated] = useState<number | null>(null);

  const toggleFollowMode = useCallback(() => {
    setIsFollowMode(prev => !prev);
  }, []);

  const syncUserLocation = useCallback(async (
    lat: number,
    lng: number,
    accuracyMeters?: number,
    addressName?: string,
    source: 'gps' | 'manual' = 'gps'
  ) => {
    setUserLocation(prev => {
      if (prev && Math.abs(prev[0] - lat) < 0.0001 && Math.abs(prev[1] - lng) < 0.0001) {
        return prev;
      }
      return [lat, lng];
    });
    if (accuracyMeters !== undefined) setUserLocationAccuracy(accuracyMeters);

    let resolvedName = addressName ? sanitizeLocationName(addressName) : '';
    if (!addressName || addressName.includes('Live GPS') || addressName.includes('Local Area') || resolvedName === 'Madhubani') {
      resolvedName = await reverseGeocodeCoords(lat, lng);
    }
    setUserLocationName(resolvedName);
    setLocationSource(source);

    if (source === 'manual') {
      locationService.setManualOverride({
        latitude: lat,
        longitude: lng,
        accuracy: accuracyMeters || 10,
        heading: null,
        speed: null,
        timestamp: Date.now(),
        source: 'manual',
        addressName: resolvedName
      });
    }

    // Real-time WebSocket transmission as primary transport
    const sentViaWs = locationSocket.sendPosition({
      latitude: lat,
      longitude: lng,
      accuracy: accuracyMeters !== undefined ? accuracyMeters : 10
    });

    if (!sentViaWs) {
      wsClient.send('location:update', {
        latitude: lat,
        longitude: lng,
        accuracy_meters: accuracyMeters !== undefined ? accuracyMeters : 10,
        address_name: addressName || 'User Location',
        source,
        trip_id: currentTrip?.id || null
      }).catch(err => console.warn('[LOCATION SYNC WS ERROR]', err));
    }
  }, [currentTrip?.id]);

  const retryGPS = useCallback(async () => {
    locationService.clearManualOverride();
    setLocationSource('gps');
    if ('geolocation' in navigator) {
      navigator.geolocation.getCurrentPosition(
        async (pos) => {
          const lat = pos.coords.latitude;
          const lng = pos.coords.longitude;
          const accuracy = pos.coords.accuracy;
          await syncUserLocation(lat, lng, accuracy, 'Live GPS Position', 'gps');
          if (accuracy <= 1000) {
            setIsLocationModalOpen(false);
          }
        },
        (err) => {
          console.warn('[RETRY GPS ERROR]', err.message);
          setIsLocationModalOpen(true);
        },
        { enableHighAccuracy: false, timeout: 15000, maximumAge: 10000 }
      );
    }
  }, [syncUserLocation]);

  const requestGPSLocation = useCallback(() => {
    return retryGPS();
  }, [retryGPS]);

  const lastSyncedRef = useRef<{ lat: number; lng: number; time: number } | null>(null);

  // ── Unified Location Watcher Lifecycle ──
  const startLiveTracking = useCallback(() => {
    const success = locationService.startWatcher(
      async (point: NormalizedLocationPoint, shouldSyncBackend: boolean) => {
        const now = Date.now();
        let shouldUpdateState = false;

        if (!lastSyncedRef.current) {
          shouldUpdateState = true;
        } else {
          const dLat = Math.abs(lastSyncedRef.current.lat - point.latitude);
          const dLng = Math.abs(lastSyncedRef.current.lng - point.longitude);
          // ~0.0005 degrees is approx 50 meters
          const moved50m = dLat > 0.0005 || dLng > 0.0005;
          const timeElapsed30s = now - lastSyncedRef.current.time > 30000;
          if (moved50m || timeElapsed30s || shouldSyncBackend) {
            shouldUpdateState = true;
          }
        }

        if (shouldUpdateState) {
          lastSyncedRef.current = { lat: point.latitude, lng: point.longitude, time: now };
          setUserLocation([point.latitude, point.longitude]);
          setUserLocationAccuracy(point.accuracy);
          setLiveTrackingLastUpdated(point.timestamp);
          setLocationSource('gps');
          setIsLiveTracking(true);

          if (shouldSyncBackend) {
            console.log(`[LIVE TRACKING] Syncing position — Lat: ${point.latitude.toFixed(5)}, Lng: ${point.longitude.toFixed(5)}, Accuracy: ${point.accuracy.toFixed(0)}m`);
            await syncUserLocation(point.latitude, point.longitude, point.accuracy, 'Live GPS (Continuous)', 'gps');
          }
        }
      },
      (err) => {
        console.warn('[LIVE TRACKING ERROR]', err.message);
        if (err.code === err.PERMISSION_DENIED) {
          setIsLiveTracking(false);
          setIsLocationModalOpen(true);
        }
      }
    );

    if (success) {
      setIsLiveTracking(true);
    }
  }, [syncUserLocation]);

  const stopLiveTracking = useCallback(() => {
    locationService.stopWatcher();
    locationSocket.disconnect();
    setIsLiveTracking(false);
  }, []);

  const toggleLiveTracking = useCallback(() => {
    if (isLiveTracking) {
      stopLiveTracking();
    } else {
      startLiveTracking();
    }
  }, [isLiveTracking, startLiveTracking, stopLiveTracking]);

  // Unified single mount effect for ambient geolocation watcher & WebSocket connection
  useEffect(() => {
    const effectiveTripId = currentTrip?.id || null;
    locationSocket.setActiveTripId(effectiveTripId);

    // Immediately connect ambient WebSocket and request browser GPS permission on launch
    locationSocket.connect();
    startLiveTracking();
  }, [currentTrip?.id, startLiveTracking]);

  // Modals & Sheets
  const [isAiOpen, setIsAiOpen] = useState(false);
  const [aiPromptQuery, setAiPromptQuery] = useState('');
  const [isCabModalOpen, setIsCabModalOpen] = useState(false);
  const [cabDestination, setCabDestination] = useState('');
  const [isProfileOpen, setIsProfileOpen] = useState(false);
  const [isNotificationsOpen, setIsNotificationsOpen] = useState(false);
  const [isFoodSheetOpen, setIsFoodSheetOpen] = useState(false);
  const [isEmergencyOpen, setIsEmergencyOpen] = useState(false);

  // Contextual AI label
  const aiContextLabel = useMemo(() => {
    if (activeTab === 'home') return 'Plan my trip';
    if (activeTab === 'explore') return 'Discover packages';
    if (activeTab === 'trips') {
      if (tripView === 'map') return "What's nearby?";
      if (tripView === 'expenses') return 'Save money';
      if (tripView === 'reservations') return 'Manage bookings';
      return 'What should I do?';
    }
    return 'Ask Cruiser Copilot';
  }, [activeTab, tripView]);

  const [swapContext, setSwapContext] = useState<SwapActivityPayload | null>(null);
  const [isSwapModalOpen, setIsSwapModalOpen] = useState<boolean>(false);
  const [navigationTarget, setNavigationTarget] = useState<NavigationTarget | null>(null);

  const openSwapAssistant = useCallback((payload: SwapActivityPayload) => {
    setSwapContext(payload);
    setIsSwapModalOpen(true);
  }, []);

  const closeSwapAssistant = useCallback(() => {
    setIsSwapModalOpen(false);
    setSwapContext(null);
  }, []);

  const openInAppNavigation = useCallback((target: NavigationTarget, navigateFn?: (path: string) => void) => {
    setNavigationTarget(target);
    setActiveTab('trips');
    setTripView('map');
    if (navigateFn) {
      navigateFn('/trip/map');
    }
  }, []);

  // Operations
  const addBooking = useCallback((newBooking: Booking) => {
    setBookings(prev => [newBooking, ...prev]);
    setNotifications(prev => [{
      id: `notif-${Date.now()}`,
      title: 'Booking Confirmed!',
      message: `${newBooking.title} confirmed. Code: ${newBooking.confirmationCode}`,
      time: 'Just now',
      type: 'booking',
      read: false
    }, ...prev]);
  }, [setBookings, setNotifications]);

  const cancelBooking = useCallback((bookingId: string) => {
    setBookings(prev => prev.map(b => b.id === bookingId ? { ...b, status: 'cancelled', paymentStatus: 'refunded' } : b));
  }, [setBookings]);

  const addExpense = useCallback((newExpense: Omit<Expense, 'id'>) => {
    const item: Expense = { ...newExpense, id: `exp-${Date.now()}` };
    setExpenses(prev => [item, ...prev]);
  }, [setExpenses]);

  const optimizeDayItinerary = useCallback((_dayNumber: number) => {
    console.log('[AppContext] Day itinerary optimization delegated to TripContext.');
  }, []);

  const removeActivity = useCallback((_dayNumber: number, _actId: string) => {
    console.log('[AppContext] Activity removal delegated to TripContext.');
  }, []);

  const addActivityToItinerary = useCallback((_dayNumber: number, _actData: Omit<ActivityItem, 'id'>) => {
    console.log('[AppContext] Activity addition delegated to TripContext.');
  }, []);

  const openCabModal = useCallback((destName?: string) => {
    if (destName) setCabDestination(destName);
    setIsCabModalOpen(true);
  }, []);
  const openAiAssistant = useCallback((query?: string) => {
    if (query) setAiPromptQuery(query);
    setIsAiOpen(true);
  }, []);
  const markNotificationAsRead = useCallback((id: string) => {
    setNotifications(prev => prev.map(n => n.id === id ? { ...n, read: true } : n));
  }, [setNotifications]);

  return (
    <AppContext.Provider value={{
      activeTab, setActiveTab, tripView, setTripView,
      appUIState, setAppUIState,
      activeTrip, setActiveTrip,
      userLocation, userLocationAccuracy, userLocationName, locationSource,
      activeContextMode, setActiveContextMode,
      isLocationModalOpen, setIsLocationModalOpen,
      syncUserLocation, requestGPSLocation,
      isLiveTracking, toggleLiveTracking, startLiveTracking, stopLiveTracking, liveTrackingLastUpdated,
      isFollowMode, setIsFollowMode, toggleFollowMode, retryGPS,
      bookings, expenses, notifications,
      isAiOpen, setIsAiOpen, aiPromptQuery, setAiPromptQuery, aiContextLabel,
      swapContext, setSwapContext, isSwapModalOpen, setIsSwapModalOpen, openSwapAssistant, closeSwapAssistant,
      navigationTarget, setNavigationTarget, openInAppNavigation,
      isCabModalOpen, setIsCabModalOpen, cabDestination, setCabDestination,
      isProfileOpen, setIsProfileOpen,
      isNotificationsOpen, setIsNotificationsOpen,
      isFoodSheetOpen, setIsFoodSheetOpen,
      isEmergencyOpen, setIsEmergencyOpen,
      addBooking, cancelBooking, addExpense,
      optimizeDayItinerary, removeActivity, addActivityToItinerary,
      openCabModal, openAiAssistant, markNotificationAsRead
    }}>
      {children}
      <ManualLocationModal />
    </AppContext.Provider>
  );
};

export const useApp = () => {
  const context = useContext(AppContext);
  if (!context) throw new Error('useApp must be used within AppProvider');
  return context;
};
