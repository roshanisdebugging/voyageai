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
      <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
        <button
          type="button"
          onClick={() => {
            setTripView('home');
            setActiveTab('trips');
            navigate('/');
          }}
          className="px-3 py-1.5 rounded-xl bg-[var(--color-surface)] hover:bg-[var(--color-surface-elevated)] text-[var(--color-primary)] text-xs font-black flex items-center gap-1.5 border border-[var(--color-border)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-primary)] transition-all press-scale"
        >
          <ArrowLeft className="w-4 h-4 text-[var(--color-primary)]" />
          <span>Back to Trip</span>
        </button>

        <div className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-[var(--color-surface-elevated)] text-[var(--color-primary)] border border-[var(--color-border)] text-xs font-bold">
          <UtensilsCrossed className="w-3.5 h-3.5" />
          <span>Food</span>
        </div>
      </div>

      {/* Hero */}
      <div className="relative rounded-3xl p-6 bg-[var(--color-surface)] border border-[var(--color-border)] shadow-xs space-y-3 overflow-hidden">
        <h1 className="text-2xl font-black text-[var(--color-text-primary)] tracking-tight">
          Where to eat{placeName ? ` in ${placeName}` : ''}
        </h1>
        <p className="text-xs text-[var(--color-text-secondary)] leading-relaxed">
          Restaurants and cafes near {currentTrip ? 'your trip destination' : 'you'}, from Google Maps.
        </p>
        <button
          type="button"
          onClick={() => openAiAssistant(`Recommend must-try local dishes and good places to eat${placeName ? ` in ${placeName}` : ' near me'}`)}
          className="px-3.5 py-1.5 rounded-xl bg-[var(--color-primary)] text-white dark:text-zinc-950 hover:brightness-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-primary)] font-black text-xs shadow-xs transition-all flex items-center gap-1.5 press-scale"
        >
          <Sparkles className="w-3.5 h-3.5" />
          <span>Ask AI what to eat</span>
        </button>
      </div>

      {/* Nearby restaurants */}
      <div className="space-y-3">
        <h2 className="text-sm font-black uppercase tracking-wider text-[var(--color-primary)] flex items-center gap-1.5">
          <Compass className="w-4 h-4" />
          Restaurants nearby
        </h2>

        {lat == null || lng == null ? (
          <div className="p-6 text-center bg-[var(--color-surface)] rounded-2xl border border-[var(--color-border)] text-xs text-[var(--color-text-secondary)]">
            Turn on location or open a trip to see restaurants nearby.
          </div>
        ) : isLoading ? (
          <div className="p-8 text-center bg-[var(--color-surface)] rounded-2xl border border-[var(--color-border)] space-y-2">
            <RefreshCw className="w-6 h-6 text-[var(--color-primary)] animate-spin mx-auto" />
            <p className="text-xs text-[var(--color-text-secondary)] font-bold">Finding restaurants…</p>
          </div>
        ) : loadError ? (
          <div className="p-6 text-center bg-[var(--color-surface)] rounded-2xl border border-rose-200 text-xs text-rose-700 dark:text-rose-300 dark:border-rose-900 font-semibold">{loadError}</div>
        ) : restaurants.length === 0 ? (
          <div className="p-6 text-center bg-[var(--color-surface)] rounded-2xl border border-[var(--color-border)] text-xs text-[var(--color-text-secondary)]">No restaurants found nearby.</div>
        ) : (
          <div className="space-y-3">
            {restaurants.slice(0, 10).map((rst, idx) => {
              const coords: [number, number] | null =
                rst.latitude != null && rst.longitude != null ? [rst.latitude, rst.longitude] : null;
              const distance = formatDistance(rst.distanceMeters);
              return (
                <div
                  key={rst.id || idx}
                  className="p-4 rounded-2xl bg-[var(--color-surface)] border border-[var(--color-border)] hover:border-[var(--color-primary)] transition-all space-y-2.5 shadow-xs"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <h3 className="font-extrabold text-sm wrap-anywhere text-[var(--color-text-primary)]">{rst.name}</h3>
                      {rst.address && (
                        <p className="text-xs text-[var(--color-text-secondary)] flex items-center gap-1 mt-0.5">
                          <MapPin className="w-3.5 h-3.5 text-[var(--color-primary)] shrink-0" />
                          <span className="min-w-0 wrap-anywhere">{rst.address}</span>
                        </p>
                      )}
                    </div>

                    {rst.rating != null && (
                      <span
                        className="px-2 py-0.5 rounded-md bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300 dark:border-amber-800 text-xs font-black flex items-center gap-1 border border-amber-200 shrink-0"
                        title={rst.userRatingCount ? `${rst.userRatingCount} Google ratings` : 'Google rating'}
                      >
                        <Star className="w-3 h-3 fill-current" />
                        {rst.rating}
                      </span>
                    )}
                  </div>

                  {(rst.category || distance) && (
                    <div className="flex flex-wrap gap-1.5 text-[10px] text-[var(--color-text-secondary)] font-semibold">
                      {rst.category && <span className="px-2 py-0.5 rounded-md bg-[var(--color-surface-elevated)] border border-[var(--color-border)]">{rst.category}</span>}
                      {distance && <span className="px-2 py-0.5 rounded-md bg-[var(--color-surface-elevated)] border border-[var(--color-border)]">{distance}</span>}
                    </div>
                  )}

                  <div className="flex flex-wrap items-center justify-between gap-2 pt-1 border-t border-[var(--color-border)]">
                    <button
                      type="button"
                      disabled={!coords}
                      onClick={() => {
                        if (coords) openInAppNavigation({ title: rst.name, locationName: rst.address || rst.name, coordinates: coords });
                      }}
                      className="px-3 py-1.5 rounded-xl bg-[var(--color-surface-elevated)] hover:bg-[var(--color-surface-elevated)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-primary)] disabled:opacity-50 disabled:cursor-not-allowed text-[var(--color-primary)] text-xs font-bold flex items-center gap-1 border border-[var(--color-border)] transition-all"
                    >
                      <Navigation className="w-3.5 h-3.5 text-[var(--color-primary)]" />
                      <span>Navigate</span>
                    </button>

                    <button
                      type="button"
                      onClick={() => openCabModal(rst.address ? `${rst.name}, ${rst.address}` : rst.name)}
                      className="px-3.5 py-1.5 rounded-xl bg-[var(--color-primary)] text-white dark:text-zinc-950 hover:brightness-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-primary)] font-black text-xs shadow-xs transition-all flex items-center gap-1.5 press-scale"
                    >
                      <Car className="w-3.5 h-3.5" />
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
