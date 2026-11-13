import React, { useState, useEffect, useMemo } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { type RootState, type AppDispatch } from '../../store';
import { fetchNearbyPlaces } from '../../store';
import { useAuth } from '../../auth/AuthContext';
import { useTrip } from '../../features/trip/TripContext';
import { useApp } from '../../context/AppContext';
import { TripSpotlightBanner } from './TripSpotlightBanner';
import { formatDateRange } from './tripDates';
import { AskVoyageAICard } from '../ai/AskVoyageAICard';
import { PlaceDetailSheet, type PlaceDetailItem } from '../common/PlaceDetailSheet';
import { Navigation, Star } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { formatDistance } from '../../services/tourGuideApi';
import { isMockPayload } from '../../utils/mockIndicator';

export const HomePage: React.FC = () => {
  const dispatch = useDispatch<AppDispatch>();
  const { userProfile } = useAuth();
  const { currentTrip } = useTrip();
  const { userLocation, userLocationName, openInAppNavigation, requestGPSLocation } = useApp();
  const navigate = useNavigate();

  const [selectedPlace, setSelectedPlace] = useState<PlaceDetailItem | null>(null);

  const { places: rawNearbyPlaces } = useSelector(
    (state: RootState) => state.nearby
  );

  const firstName = userProfile?.firstName || 'Traveler';

  // Greeting based on time of day
  const getGreeting = () => {
    const hour = new Date().getHours();
    if (hour < 12) return 'Good morning';
    if (hour < 18) return 'Good afternoon';
    return 'Good evening';
  };

  const userLat = userLocation ? Number(userLocation[0].toFixed(4)) : null;
  const userLng = userLocation ? Number(userLocation[1].toFixed(4)) : null;

  // Dispatch Redux fetch on coordinates available (thunk condition automatically guards against <500m refetches)
  useEffect(() => {
    if (!userLat && !userLng && navigator.geolocation) {
      requestGPSLocation().catch(() => { });
    }

    if (userLat !== null && userLng !== null) {
      dispatch(fetchNearbyPlaces({ lat: userLat, lng: userLng, radius: 5000 }));
    }
  }, [userLat, userLng, requestGPSLocation, dispatch]);

  // Transform raw Redux places to UI PlaceDetailItem shape
  const nearbyPlaces: PlaceDetailItem[] = useMemo(() => {
    if (!rawNearbyPlaces || rawNearbyPlaces.length === 0) return [];
    return rawNearbyPlaces.slice(0, 6).map((p, idx) => ({
      id: p.id || `poi-${idx}`,
      name: p.name,
      category: (p.category || 'ATTRACTION').toUpperCase().replace('_', ' '),
      rating: 4.5 + (idx % 4) * 0.1,
      distanceText: p.distanceMeters ? formatDistance(p.distanceMeters) : 'Near you',
      durationText: '45 mins',
      estimatedCost: 0,
      address: p.address || p.description || `${p.category || 'POI'} in ${userLocationName || 'Current Location'}`,
      description: p.description || `Popular ${p.category || 'attraction'} located near your physical coordinates.`,
      latitude: p.latitude || userLocation?.[0] || 0,
      longitude: p.longitude || userLocation?.[1] || 0,
      is_mock: Boolean(p.is_mock || p._isMock),
    }));
  }, [rawNearbyPlaces, userLocation, userLocationName]);

  const sentenceCase = (s: string) => (s ? s.charAt(0).toUpperCase() + s.slice(1).toLowerCase() : s);
  const tripRange = currentTrip ? formatDateRange(currentTrip.startDate, currentTrip.endDate) : null;

  return (
    <div className="w-full max-w-xl mx-auto space-y-6 pb-28 animate-fadeIn overflow-x-hidden">
      {/* Greeting */}
      <div className="space-y-1 pt-1">
        <h1 className="text-2xl sm:text-3xl font-extrabold text-[#1F2522] tracking-tight">
          {getGreeting()}, {firstName}
        </h1>
        <p className="text-sm font-medium text-[#5F6863]">Where would you like to explore today?</p>
      </div>

      {/* Destination and highlights */}
      {(currentTrip || userLocation) && (
        <TripSpotlightBanner
          destination={currentTrip ? (currentTrip.destination?.name || currentTrip.title) : userLocationName}
          latitude={currentTrip?.destination?.latitude ?? userLocation?.[0]}
          longitude={currentTrip?.destination?.longitude ?? userLocation?.[1]}
          startDate={currentTrip?.startDate}
          endDate={currentTrip?.endDate}
          isLocalMode={!currentTrip}
        />
      )}

      <AskVoyageAICard />

      {/* Near you */}

      <div className="relative">
        <div
          className="flex gap-4 overflow-x-auto overflow-y-hidden pb-4
               snap-x snap-mandatory scroll-smooth
               [scrollbar-width:thin]
               [scrollbar-color:#A8C4BB_transparent]
               motion-reduce:scroll-auto"
        >
          {nearbyPlaces.map((poi) => {
            const isMock = isMockPayload(poi);

            return (
              <article
                key={poi.id}
                className="group relative flex w-[82%] min-w-[280px] max-w-[340px]
                     shrink-0 snap-start flex-col overflow-hidden
                     rounded-3xl border border-[#D9DEDA]
                     bg-gradient-to-br from-white via-white to-[#EAF3EF]
                     p-4 shadow-sm transition-all duration-300
                     hover:-translate-y-1 hover:border-[#A8C4BB]
                     hover:shadow-lg sm:w-[320px]"
              >
                {/* Decorative accent */}
                <div className="absolute right-0 top-0 h-24 w-24 rounded-bl-full
                          bg-gradient-to-bl from-[#C7E5D9]/60 to-transparent
                          pointer-events-none" />

                <div className="relative flex flex-1 flex-col">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="mb-2 flex flex-wrap items-center gap-2">
                        <span className="rounded-full bg-[#E8F0EE] px-2.5 py-1
                                   text-[11px] font-bold uppercase tracking-wide
                                   text-[#355F58]">
                          {sentenceCase(poi.category || "Attraction")}
                        </span>

                        {isMock && (
                          <span className="rounded-full border border-amber-200
                                     bg-amber-50 px-2 py-1 text-[10px]
                                     font-bold text-amber-700">
                            Demo Spot
                          </span>
                        )}
                      </div>

                      <h3 className="truncate text-lg font-extrabold text-[#1F2522]">
                        {poi.name}
                      </h3>

                      <p className="mt-1 line-clamp-2 min-h-9 text-xs leading-5
                              text-[#5F6863]">
                        {poi.address || "Address unavailable"}
                      </p>
                    </div>

                    <div className="shrink-0 rounded-2xl bg-white/90 px-3 py-2
                              text-right shadow-sm ring-1 ring-[#D9DEDA]">
                      <p className="text-sm font-extrabold text-[#355F58]">
                        {poi.distanceText}
                      </p>

                      {poi.rating ? (
                        <p className="mt-1 flex items-center justify-end gap-1
                                text-xs font-bold text-[#8A5A00]">
                          <Star
                            className="h-3.5 w-3.5 fill-amber-500 text-amber-500"
                            aria-hidden="true"
                          />
                          {Number(poi.rating).toFixed(1)}
                        </p>
                      ) : null}
                    </div>
                  </div>

                  <div className="mt-5 grid grid-cols-2 gap-2">
                    <button
                      type="button"
                      disabled={typeof poi.latitude !== 'number' || typeof poi.longitude !== 'number'}
                      onClick={() => {
                        if (typeof poi.latitude === 'number' && typeof poi.longitude === 'number') {
                          openInAppNavigation({
                            title: poi.name,
                            locationName: poi.address || poi.name,
                            coordinates: [poi.latitude, poi.longitude],
                          });
                        }
                      }}
                      className="flex min-h-12 items-center justify-center gap-2
                           rounded-xl bg-[#355F58] px-3 text-sm font-bold
                           text-white shadow-sm transition-all
                           hover:bg-[#264A44] active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed
                           focus-visible:outline focus-visible:outline-2
                           focus-visible:outline-offset-2
                           focus-visible:outline-[#355F58]"
                    >
                      <Navigation className="h-4 w-4" aria-hidden="true" />
                      Directions
                    </button>

                    <button
                      type="button"
                      onClick={() => setSelectedPlace(poi)}
                      className="min-h-12 rounded-xl border border-[#C9D8D1]
                           bg-white/80 px-3 text-sm font-bold text-[#1F2522]
                           transition-all hover:bg-[#DCE9E5]
                           active:scale-95 focus-visible:outline
                           focus-visible:outline-2 focus-visible:outline-offset-2
                           focus-visible:outline-[#355F58]"
                    >
                      Details
                    </button>
                  </div>
                </div>
              </article>
            );
          })}
        </div>

        <p className="mt-1 flex items-center justify-center gap-2 text-xs
                font-medium text-[#5F6863] sm:hidden">
          <span aria-hidden="true">←</span>
          Swipe to explore more places
          <span aria-hidden="true">→</span>
        </p>
      </div>


      {/* Current trip */}
      {currentTrip && (
        <section className="rounded-3xl bg-white border border-[#D9DEDA] p-5">
          <p className="text-sm font-semibold text-[#355F58]">{currentTrip.destination.name}</p>
          <h3 className="mt-1 text-xl sm:text-2xl font-extrabold text-[#1F2522]">{currentTrip.title}</h3>
          <p className="mt-1 text-sm text-[#5F6863]">
            {tripRange ?? `${currentTrip.startDate} to ${currentTrip.endDate}`} ({currentTrip.totalDays} days)
          </p>

          <button
            type="button"
            onClick={() => navigate('/trip/itinerary')}
            className="mt-4 w-full min-h-[52px] rounded-2xl bg-[#355F58] hover:bg-[#2C504A] text-white text-base font-bold transition-colors press-scale focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#355F58]"
          >
            View trip plan
          </button>
        </section>
      )}

      {/* Place details bottom sheet */}
      <PlaceDetailSheet item={selectedPlace} onClose={() => setSelectedPlace(null)} />
    </div>
  );
};

