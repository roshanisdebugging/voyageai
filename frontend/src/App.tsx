import React, { useEffect } from 'react';
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
import { HotelDetailModal } from './components/hotels/HotelDetailModal';
import { CabBookingModal } from './components/cabs/CabBookingModal';
import { FoodSheet } from './components/food/FoodSheet';
import { EmergencyModal } from './components/common/EmergencyModal';
import { SwapActivityModal } from './components/itinerary/SwapActivityModal';
import { ItineraryReadyNotice } from './components/trip/ItineraryReadyNotice';
import { ToastProvider } from './components/common/UndoToast';
import { MicButton } from './voice/MicButton';

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

const MapView = React.lazy(() =>
  import('./components/map/MapView').then((mod) => ({ default: mod.MapView }))
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

const MainContent: React.FC = () => {
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
      <React.Suspense fallback={<div className="h-full min-h-[350px] flex items-center justify-center p-12 text-[#355F58]"><RefreshCw className="w-8 h-8 animate-spin" /></div>}>
        <MapView />
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
      <Route path="/map" element={
        <React.Suspense fallback={<div className="h-full min-h-[350px] flex items-center justify-center p-12 text-[#355F58]"><RefreshCw className="w-8 h-8 animate-spin" /></div>}>
          <MapView />
        </React.Suspense>
      } />
      <Route path="/trip/map" element={
        <React.Suspense fallback={<div className="h-full min-h-[350px] flex items-center justify-center p-12 text-[#355F58]"><RefreshCw className="w-8 h-8 animate-spin" /></div>}>
          <MapView />
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
      <Route path="/tour-guide" element={<TourGuidePage />} />
      <Route path="/guide" element={<TourGuidePage />} />
      <Route path="/more" element={<MorePage />} />
      <Route path="/saved-places" element={<SavedPlacesPage />} />
      <Route path="*" element={<HomePage />} />
    </Routes>
  );
};
const AppShell: React.FC = () => {
  const location = useLocation();
  const isGuideView = location.pathname === '/guide' || location.pathname === '/tour-guide';

  return (
    <div className="min-h-dvh bg-[#F6F7F5] dark:bg-zinc-950 text-[#1F2522] dark:text-zinc-100 flex flex-col antialiased overflow-x-hidden w-full max-w-full transition-colors">
      {/* Mobile Lightweight Header */}
      <MobileHeader />

      {/* Main Layout Area */}
      <div className="flex-1 flex max-w-7xl w-full mx-auto overflow-hidden">
        <DesktopSidebar />

        <main className={`flex-1 min-w-0 flex flex-col max-w-full overflow-x-hidden ${isGuideView ? 'px-0 sm:px-4 py-0 sm:py-2 overflow-hidden' : 'px-4 lg:px-8 py-4 lg:py-6 overflow-y-auto'}`}>
          <MainContent />
        </main>
      </div>

      {/* Fixed 4-Tab Bottom Navigation */}
      <MobileBottomNav />

      {/* Floating Contextual AI Button (Omitted on Guide page) */}
      {!isGuideView && <FloatingAIButton />}

      {/* Voice (step 1): floating mic, logged-in users only */}
      <MicButton raised={!isGuideView} />

      {/* Bottom Sheets & Modals */}
      <NotificationDrawer />
      <AIAssistantSheet />
      <ProfileSheet />
      <HotelDetailModal />
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
                  <Routes>
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
