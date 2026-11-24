import React, { useEffect, useRef, useState } from 'react';
import { BrowserRouter, Routes, Route, useLocation, useParams, useNavigate } from 'react-router-dom';
import { AppProvider, useApp } from './context/AppContext';
import { AuthProvider } from './auth/AuthContext';
import { AuthGuard } from './auth/AuthGuard';
import { TripProvider, useTrip } from './features/trip/TripContext';
import { NavigationProvider } from './context/NavigationContext';
import { ErrorBoundary } from './components/common/ErrorBoundary';
import { ThemeProvider } from './context/ThemeContext';

import { LoginScreen } from './onboarding/LoginScreen';
import { OnboardingContainer } from './onboarding/OnboardingContainer';
import { TripCreationWizard } from './features/trip/screens/TripCreationWizard';

import { MobileHeader } from './components/layout/Navbar';
import { DesktopSidebar } from './components/layout/Sidebar';
import { MobileBottomNav } from './components/layout/BottomNav';
import { FloatingAIButton } from './components/ai/FloatingAIButton';
import { NotificationDrawer } from './components/common/NotificationDrawer';
import { AIAssistantSheet } from './components/ai/AIAssistantDrawer';
import { ProfileSheet } from './components/profile/ProfilePage';
import { CabBookingModal } from './components/cabs/CabBookingModal';
import { FoodSheet } from './components/food/FoodSheet';
import { EmergencyModal } from './components/common/EmergencyModal';
import { SwapActivityModal } from './components/itinerary/SwapActivityModal';
import { ItineraryReadyNotice } from './components/trip/ItineraryReadyNotice';
import { ToastProvider } from './components/common/UndoToast';
import { GlobalMicButton, MicLayoutProvider } from './voice/micLayout';
import { useMicLayout } from './voice/micLayoutContext';

import { HomePage } from './components/home/HomePage';
import { MyTripsPage } from './components/trips/MyTripsPage';
import { ExplorePage } from './components/explore/ExplorePage';
import { MorePage } from './components/more/MorePage';
import { FoodPage } from './components/food/FoodPage';
import { RidesPage } from './components/rides/RidesPage';
import { ExpensesPage } from './components/expenses/ExpensesPage';
import { TourGuidePage } from './components/tour-guide/TourGuidePage';
import { ItineraryView } from './components/itinerary/ItineraryView';
import { SavedPlacesPage } from './components/places/SavedPlacesPage';
import { RefreshCw, AlertTriangle } from 'lucide-react';

const PlaceDetailsPage = React.lazy(() => import('./components/places/PlaceDetailsPage'));
// DEV ONLY: Google Maps feature probe (/dev/map-lab). Not linked, and dropped from production builds.
const MapLab = import.meta.env.DEV ? React.lazy(() => import('./dev/MapLab')) : null;
const MapView = React.lazy(() =>
  import('./components/map/MapView').then((mod) => ({ default: mod.MapView }))
);

const MapLoadingFallback = () => (
  <div
    className="flex min-h-0 flex-1 items-center justify-center p-12 text-[color:var(--color-primary)] dark:text-[color:var(--color-primary-light)]"
    role="status"
  >
    <RefreshCw className="h-8 w-8 animate-spin motion-reduce:animate-none" aria-hidden="true" />
    <span className="sr-only">Loading map…</span>
  </div>
);

const TripRouteRedirect: React.FC = () => {
  const { tripId } = useParams<{ tripId: string }>();
  const { setCurrentTripId, currentTripId } = useTrip();
  const navigate = useNavigate();

  useEffect(() => {
    if (tripId) {
      const cleanId = tripId.trim();
      const normalizedId = cleanId.startsWith('trip_') ? cleanId : `trip_${cleanId}`;
      if (currentTripId !== normalizedId && currentTripId !== cleanId) {
        setCurrentTripId(normalizedId);
      }
      navigate('/trip/itinerary', { replace: true });
    }
  }, [tripId, currentTripId, setCurrentTripId, navigate]);

  return (
    <div className="py-16 text-center space-y-3">
      <RefreshCw className="w-8 h-8 text-[#355F58] animate-spin mx-auto" />
      <h2 className="text-base font-bold text-[#1F2522]">Loading trip details...</h2>
    </div>
  );
};

const LocaleRedirect: React.FC = () => {
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    // Slices off language prefixes like /en, /es, /hi from path (e.g. /en/home -> / or /en/trips -> /trips)
    const stripped = location.pathname.replace(/^\/[a-zA-Z]{2}(\/|$)/, '/');
    const target = stripped.startsWith('/') ? stripped : `/${stripped}`;
    navigate(target || '/', { replace: true });
  }, [location.pathname, navigate]);

  return null;
};

const MainContent: React.FC<{ guideMicSlotRef: React.Ref<HTMLDivElement>; mapTools: React.ReactNode }> = ({ guideMicSlotRef, mapTools }) => {
  const { appUIState, setAppUIState, navigationTarget, setNavigationTarget, tripView, setTripView } = useApp();
  const location = useLocation();

  useEffect(() => {
    if (location.pathname !== '/map' && location.pathname !== '/trip/map') {
      if (navigationTarget) setNavigationTarget(null);
      if (tripView === 'map') setTripView('home');
    }
  }, [location.pathname, navigationTarget, tripView, setNavigationTarget, setTripView]);

  if (appUIState === 'loading') {
    return (
      <div className="py-16 text-center space-y-3">
        <RefreshCw className="w-8 h-8 text-[#487C74] animate-spin mx-auto" />
        <h2 className="text-base font-bold text-[#1F2522]">Loading your trip context...</h2>
      </div>
    );
  }

  if (appUIState === 'error') {
    return (
      <div className="py-16 text-center space-y-3">
        <AlertTriangle className="w-10 h-10 text-rose-600 mx-auto" />
        <h2 className="text-lg font-bold text-[#1F2522]">Connection error</h2>
        <p className="text-meta text-[13px] max-w-xs mx-auto text-[#5F6863]">We couldn't connect. Your trip data is safe with us.</p>
        <button
          onClick={() => setAppUIState('ready')}
          className="px-5 py-2 rounded-xl bg-[#355F58] text-white font-bold text-xs"
        >
          Try again
        </button>
      </div>
    );
  }

  if ((navigationTarget || tripView === 'map') && (location.pathname === '/map' || location.pathname === '/trip/map' || location.pathname === '/')) {
    return (
      <React.Suspense fallback={<MapLoadingFallback />}>
        <MapView tools={mapTools} />
      </React.Suspense>
    );
  }

  if (tripView === 'food') {
    return <FoodPage />;
  }

  if (tripView === 'rides') {
    return <RidesPage />;
  }

  if (tripView === 'expenses') {
    return <ExpensesPage />;
  }

  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/home" element={<HomePage />} />
      <Route path="/home/trip/:tripId" element={<TripRouteRedirect />} />
      <Route path="/trip/:tripId" element={<TripRouteRedirect />} />
      <Route path="/:lang/home/trip/:tripId" element={<TripRouteRedirect />} />
      <Route path="/:lang/trip/:tripId" element={<TripRouteRedirect />} />
      <Route path="/:lang/home" element={<HomePage />} />
      <Route path="/:lang" element={<HomePage />} />
      <Route path="/:lang/*" element={<LocaleRedirect />} />
      <Route path="/details/:placeId" element={
        <React.Suspense fallback={<div className="h-full min-h-[350px] flex items-center justify-center p-12 text-[#355F58]"><RefreshCw className="w-8 h-8 animate-spin" /></div>}>
          <PlaceDetailsPage />
        </React.Suspense>
      } />
      <Route path="/map" element={
        <React.Suspense fallback={<MapLoadingFallback />}>
          <MapView tools={mapTools} />
        </React.Suspense>
      } />
      <Route path="/trip/map" element={
        <React.Suspense fallback={<MapLoadingFallback />}>
          <MapView tools={mapTools} />
        </React.Suspense>
      } />
      <Route path="/food" element={<FoodPage />} />
      <Route path="/trip/food" element={<FoodPage />} />
      <Route path="/rides" element={<RidesPage />} />
      <Route path="/trip/rides" element={<RidesPage />} />
      <Route path="/expenses" element={<ExpensesPage />} />
      <Route path="/trip/expenses" element={<ExpensesPage />} />
      <Route path="/trip/itinerary" element={<ItineraryView />} />
      <Route path="/trip/details" element={<ItineraryView />} />
      <Route path="/itinerary" element={<ItineraryView />} />
      <Route path="/trip" element={<ItineraryView />} />
      <Route path="/trips" element={<MyTripsPage />} />
      <Route path="/trips/*" element={<MyTripsPage />} />
      <Route path="/explore" element={<ExplorePage />} />
      <Route path="/tour-guide" element={<TourGuidePage micSlotRef={guideMicSlotRef} />} />
      <Route path="/guide" element={<TourGuidePage micSlotRef={guideMicSlotRef} />} />
      <Route path="/more" element={<MorePage />} />
      <Route path="/saved-places" element={<SavedPlacesPage />} />
      <Route path="*" element={<HomePage />} />
    </Routes>
  );
};
const AppShell: React.FC = () => {
  const location = useLocation();
  const { navigationTarget, tripView } = useApp();
  const isGuideView = /^\/(?:guide|tour-guide)\/?$/i.test(location.pathname);
  const isMapView = /^\/(?:trip\/)?map\/?$/i.test(location.pathname)
    || (location.pathname === '/' && (Boolean(navigationTarget) || tripView === 'map'));
  const shellRef = useRef<HTMLDivElement>(null);
  const [guideMicSlot, setGuideMicSlot] = useState<HTMLDivElement | null>(null);
  const [mapMicSlot, setMapMicSlot] = useState<HTMLDivElement | null>(null);
  // Voice: the mic button itself is mounted above the routes (it must survive the jump to /trips/new).
  useMicLayout(!isGuideView, isMapView ? mapMicSlot : guideMicSlot);

  useEffect(() => {
    const shell = shellRef.current;
    const viewport = window.visualViewport;
    if (!isGuideView || !shell || !viewport) return;

    const syncViewport = () => {
      // An overlay keyboard shrinks the visual viewport while the layout viewport stays tall.
      const keyboardOpen = viewport.scale === 1 && window.innerHeight - viewport.height > 80;
      shell.toggleAttribute('data-guide-keyboard', keyboardOpen);
      shell.toggleAttribute('data-guide-tight-viewport', keyboardOpen && viewport.height < 260);
      if (keyboardOpen) {
        shell.style.setProperty('--guide-viewport-height', `${Math.floor(viewport.height)}px`);
        shell.style.setProperty('--guide-viewport-top', `${viewport.offsetTop}px`);
      } else {
        shell.style.removeProperty('--guide-viewport-height');
        shell.style.removeProperty('--guide-viewport-top');
      }
    };

    syncViewport();
    viewport.addEventListener('resize', syncViewport);
    viewport.addEventListener('scroll', syncViewport);
    return () => {
      viewport.removeEventListener('resize', syncViewport);
      viewport.removeEventListener('scroll', syncViewport);
      shell.removeAttribute('data-guide-keyboard');
      shell.removeAttribute('data-guide-tight-viewport');
      shell.style.removeProperty('--guide-viewport-height');
      shell.style.removeProperty('--guide-viewport-top');
    };
  }, [isGuideView]);

  return (
    <div
      ref={shellRef}
      className={`${isGuideView ? 'guide-app-shell' : isMapView ? 'map-app-shell' : 'min-h-dvh'} bg-[#F6F7F5] dark:bg-zinc-950 text-[#1F2522] dark:text-zinc-100 flex flex-col antialiased overflow-x-hidden w-full max-w-full transition-colors`}
    >
      {/* Mobile Lightweight Header */}
      <MobileHeader />

      {/* Main Layout Area */}
      <div className={`${isGuideView ? 'guide-app-frame min-h-0' : isMapView ? 'map-app-frame min-h-0' : ''} flex-1 flex max-w-7xl w-full mx-auto overflow-hidden`}>
        <DesktopSidebar />

        <main className={`flex-1 min-w-0 flex flex-col max-w-full overflow-x-hidden ${isGuideView ? 'px-0 sm:px-4 py-0 sm:py-2 overflow-hidden' : isMapView ? 'min-h-0 overflow-hidden' : 'px-4 lg:px-8 py-4 lg:py-6 overflow-y-auto'}`}>
          <MainContent
            guideMicSlotRef={setGuideMicSlot}
            mapTools={<>
              <FloatingAIButton inFlow />
              <div ref={setMapMicSlot} />
            </>}
          />
        </main>
      </div>

      <MobileBottomNav inFlow={isGuideView || isMapView} />

      {/* On the map it floats inside the map view (mapTools) */}
      {!isGuideView && !(isMapView && mapMicSlot) && <FloatingAIButton />}

      {/* Bottom Sheets & Modals */}
      <NotificationDrawer />
      <AIAssistantSheet />
      <ProfileSheet />
      <CabBookingModal />
      <FoodSheet />
      <EmergencyModal />
      <SwapActivityModal />
      <ItineraryReadyNotice />
    </div>
  );
};

export default function App() {
  return (
    <ErrorBoundary>
      <ThemeProvider>
        <BrowserRouter>
          <NavigationProvider>
            <AuthProvider>
              <TripProvider>
                <AppProvider>
                  <ToastProvider>
                  <MicLayoutProvider>
                  <Routes>
                    {MapLab && (
                      <Route path="/dev/map-lab" element={<React.Suspense fallback={null}><MapLab /></React.Suspense>} />
                    )}
                    {/* Public Auth Route */}
                    <Route path="/login" element={<LoginScreen />} />

                    {/* Protected Onboarding Flow */}
                    <Route
                      path="/onboarding"
                      element={
                        <AuthGuard>
                          <OnboardingContainer />
                        </AuthGuard>
                      }
                    />

                    {/* Protected Trip Creation Wizard Route */}
                    <Route
                      path="/trips/new"
                      element={
                        <AuthGuard>
                          <TripCreationWizard />
                        </AuthGuard>
                      }
                    />

                    {/* Protected Main App Shell */}
                    <Route
                      path="/*"
                      element={
                        <AuthGuard>
                          <AppShell />
                        </AuthGuard>
                      }
                    />
                  </Routes>
                  {/* Voice: one floating mic for every logged-in page, kept mounted across page changes */}
                  <GlobalMicButton />
                  </MicLayoutProvider>
                  </ToastProvider>
                </AppProvider>
              </TripProvider>
            </AuthProvider>
          </NavigationProvider>
        </BrowserRouter>
      </ThemeProvider>
    </ErrorBoundary>
  );
}
