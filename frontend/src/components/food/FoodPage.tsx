import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useApp } from '../../context/AppContext';
import { useTrip } from '../../features/trip/TripContext';
import { UtensilsCrossed, ArrowLeft, Star, MapPin, Sparkles, Car, Navigation, Compass, RefreshCw } from 'lucide-react';
import { wsClient } from '../../services/wsClient';

/** A restaurant as returned by the backend place search. Only fields Google actually provides. */
interface NearbyRestaurant {
  id?: string;
  name: string;
  category?: string;
  address?: string;
  latitude?: number;
  longitude?: number;
  rating?: number | null;
  userRatingCount?: number;
  distanceMeters?: number;
}

const formatDistance = (m?: number) => (m == null ? null : m < 1000 ? `${Math.round(m)} m` : `${(m / 1000).toFixed(1)} km`);

export const FoodPage: React.FC = () => {
  const navigate = useNavigate();
  const { openCabModal, openAiAssistant, openInAppNavigation, setTripView, setActiveTab, userLocation, userLocationName } = useApp();
  const { currentTrip } = useTrip();

  const placeName = currentTrip?.destination?.name || userLocationName || '';
  // Search around the trip destination, else the user's location. Never a made-up default city.
  const lat = currentTrip?.destination?.latitude ?? userLocation?.[0];
  const lng = currentTrip?.destination?.longitude ?? userLocation?.[1];

  const [restaurants, setRestaurants] = useState<NearbyRestaurant[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    if (lat == null || lng == null) {
      setRestaurants([]);
      return;
    }
    let isMounted = true;
    setIsLoading(true);
    setLoadError(null);
    wsClient.sendRequest('places:nearby', { lat, lng, category: 'restaurant' })
      .then((data: NearbyRestaurant[]) => {
        if (isMounted) setRestaurants(Array.isArray(data) ? data : []);
      })
      .catch(() => {
        if (isMounted) setLoadError("Couldn't load restaurants right now. Please try again.");
      })
      .finally(() => {
        if (isMounted) setIsLoading(false);
      });
    return () => { isMounted = false; };
  }, [lat, lng]);

  return (
    <div className="space-y-6 pb-28 max-w-xl mx-auto animate-fadeIn">
      {/* Header Bar */}
      <div className="flex items-center justify-between pt-1">
        <button
          type="button"
          onClick={() => {
            setTripView('home');
            setActiveTab('trips');
            navigate('/');
          }}
          className="px-3 py-1.5 rounded-xl bg-white hover:bg-[#E8F0EE] text-[#355F58] text-xs font-black flex items-center gap-1.5 border border-[#D9DEDA] transition-all press-scale"
        >
          <ArrowLeft className="w-4 h-4 text-[#355F58]" />
          <span>Back to Trip</span>
        </button>

        <div className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-[#E8F0EE] text-[#355F58] border border-[#D9DEDA] text-xs font-bold">
          <UtensilsCrossed className="w-3.5 h-3.5" />
          <span>Food</span>
        </div>
      </div>

      {/* Hero */}
      <div className="relative rounded-3xl p-6 bg-white border border-[#D9DEDA] shadow-xs space-y-3 overflow-hidden">
        <h1 className="text-2xl font-black text-[#1F2522] tracking-tight">
          Where to eat{placeName ? ` in ${placeName}` : ''}
        </h1>
        <p className="text-xs text-[#5F6863] leading-relaxed">
          Restaurants and cafes near {currentTrip ? 'your trip destination' : 'you'}, from Google Maps.
        </p>
        <button
          type="button"
          onClick={() => openAiAssistant(`Recommend must-try local dishes and good places to eat${placeName ? ` in ${placeName}` : ' near me'}`)}
          className="px-3.5 py-1.5 rounded-xl bg-[#355F58] hover:bg-[#2C504A] text-white font-black text-xs shadow-xs transition-all flex items-center gap-1.5 press-scale"
        >
          <Sparkles className="w-3.5 h-3.5 text-white" />
          <span>Ask AI what to eat</span>
        </button>
      </div>

      {/* Nearby restaurants */}
      <div className="space-y-3">
        <h2 className="text-sm font-black uppercase tracking-wider text-[#355F58] flex items-center gap-1.5">
          <Compass className="w-4 h-4" />
          Restaurants nearby
        </h2>

        {lat == null || lng == null ? (
          <div className="p-6 text-center bg-white rounded-2xl border border-[#D9DEDA] text-xs text-[#5F6863]">
            Turn on location or open a trip to see restaurants nearby.
          </div>
        ) : isLoading ? (
          <div className="p-8 text-center bg-white rounded-2xl border border-[#D9DEDA] space-y-2">
            <RefreshCw className="w-6 h-6 text-[#355F58] animate-spin mx-auto" />
            <p className="text-xs text-[#5F6863] font-bold">Finding restaurants…</p>
          </div>
        ) : loadError ? (
          <div className="p-6 text-center bg-white rounded-2xl border border-rose-200 text-xs text-rose-700 font-semibold">{loadError}</div>
        ) : restaurants.length === 0 ? (
          <div className="p-6 text-center bg-white rounded-2xl border border-[#D9DEDA] text-xs text-[#5F6863]">No restaurants found nearby.</div>
        ) : (
          <div className="space-y-3">
            {restaurants.slice(0, 10).map((rst, idx) => {
              const coords: [number, number] | null =
                rst.latitude != null && rst.longitude != null ? [rst.latitude, rst.longitude] : null;
              const distance = formatDistance(rst.distanceMeters);
              return (
                <div
                  key={rst.id || idx}
                  className="p-4 rounded-2xl bg-white border border-[#D9DEDA] hover:border-[#355F58]/40 transition-all space-y-2.5 shadow-xs"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <h3 className="font-extrabold text-sm text-[#1F2522]">{rst.name}</h3>
                      {rst.address && (
                        <p className="text-xs text-[#5F6863] flex items-center gap-1 mt-0.5">
                          <MapPin className="w-3.5 h-3.5 text-[#355F58] shrink-0" />
                          <span className="truncate">{rst.address}</span>
                        </p>
                      )}
                    </div>

                    {rst.rating != null && (
                      <span
                        className="px-2 py-0.5 rounded-md bg-amber-100 text-amber-800 text-xs font-black flex items-center gap-1 border border-amber-200 shrink-0"
                        title={rst.userRatingCount ? `${rst.userRatingCount} Google ratings` : 'Google rating'}
                      >
                        <Star className="w-3 h-3 fill-amber-500 text-amber-500" />
                        {rst.rating}
                      </span>
                    )}
                  </div>

                  {(rst.category || distance) && (
                    <div className="flex flex-wrap gap-1.5 text-[10px] text-[#5F6863] font-semibold">
                      {rst.category && <span className="px-2 py-0.5 rounded-md bg-[#F0F2EF] border border-[#D9DEDA]">{rst.category}</span>}
                      {distance && <span className="px-2 py-0.5 rounded-md bg-[#F0F2EF] border border-[#D9DEDA]">{distance}</span>}
                    </div>
                  )}

                  <div className="flex items-center justify-between pt-1 border-t border-[#D9DEDA]">
                    <button
                      type="button"
                      disabled={!coords}
                      onClick={() => {
                        if (coords) openInAppNavigation({ title: rst.name, locationName: rst.address || rst.name, coordinates: coords });
                      }}
                      className="px-3 py-1.5 rounded-xl bg-[#F0F2EF] hover:bg-[#E8F0EE] disabled:opacity-50 disabled:cursor-not-allowed text-[#355F58] text-xs font-bold flex items-center gap-1 border border-[#D9DEDA] transition-all"
                    >
                      <Navigation className="w-3.5 h-3.5 text-[#355F58]" />
                      <span>Navigate</span>
                    </button>

                    <button
                      type="button"
                      onClick={() => openCabModal(rst.address ? `${rst.name}, ${rst.address}` : rst.name)}
                      className="px-3.5 py-1.5 rounded-xl bg-[#355F58] hover:bg-[#2C504A] text-white font-black text-xs shadow-xs transition-all flex items-center gap-1.5 press-scale"
                    >
                      <Car className="w-3.5 h-3.5 text-white" />
                      <span>Get a ride</span>
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};
