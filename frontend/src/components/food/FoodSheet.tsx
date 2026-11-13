import React, { useState, useEffect, useMemo, useRef } from 'react';
import { useApp } from '../../context/AppContext';
import { useTrip } from '../../features/trip/TripContext';
import { BottomSheet } from '../common/BottomSheet';
import { useToast } from '../common/UndoToast';
import type { RestaurantPlace } from '../../utils/destinationData';
import { Star, MapPin, Navigation, Car, Heart, RefreshCw } from 'lucide-react';
import { getApiBaseUrl, DEFAULT_HEADERS } from '../../config/apiConfig';
import { getSavedPlaces, savePlace, removeSavedPlace } from '../../services/savedPlacesApi';

export const FoodSheet: React.FC = () => {
  const { isFoodSheetOpen, setIsFoodSheetOpen, openCabModal, openInAppNavigation, activeTrip, userLocation, userLocationName } = useApp();
  const { currentTrip } = useTrip();
  const { showToast } = useToast();

  const activeDestName = currentTrip?.destination?.name || (typeof activeTrip?.destination === 'string' ? activeTrip.destination : userLocationName || 'Nearby');
  // Memoised on the numbers, so the fetch effect below doesn't re-run on every render.
  const lat = userLocation?.[0] ?? currentTrip?.destination?.latitude;
  const lng = userLocation?.[1] ?? currentTrip?.destination?.longitude;
  const activeDestCoords = useMemo<[number, number] | null>(
    () => (lat && lng ? [lat, lng] : null),
    [lat, lng]
  );

  // Saved state comes from the server (same store as Explore and Saved Places).
  const [savedIds, setSavedIds] = useState<Set<string>>(new Set());
  const [savingId, setSavingId] = useState<string | null>(null);
  const toggleSaveRef = useRef<(r: RestaurantPlace, fromUndo?: boolean) => Promise<void>>(async () => {});

  useEffect(() => {
    if (!isFoodSheetOpen) return;
    let active = true;
    getSavedPlaces()
      .then(list => {
        if (active) setSavedIds(new Set(list.map(p => p.place_id)));
      })
      .catch(() => { /* not logged in or offline: hearts start empty */ });
    return () => { active = false; };
  }, [isFoodSheetOpen]);

  const handleToggleSave = async (r: RestaurantPlace, fromUndo = false) => {
    if (savingId) return;
    const wasSaved = savedIds.has(r.id);
    const flip = (on: boolean) =>
      setSavedIds(prev => {
        const next = new Set(prev);
        if (on) next.add(r.id);
        else next.delete(r.id);
        return next;
      });
    setSavingId(r.id);
    flip(!wasSaved);
    try {
      if (wasSaved) {
        await removeSavedPlace(r.id);
      } else {
        await savePlace({
          place_id: r.id,
          title: r.name,
          category: 'food',
          rating: r.rating ?? undefined,
          location_name: r.location,
          coordinates: r.coordinates,
          distance_text: r.distanceKm != null ? `${r.distanceKm} km` : undefined,
        });
      }
      if (!fromUndo) {
        showToast({
          message: wasSaved ? `Removed ${r.name} from saved places` : `Saved ${r.name}`,
          undo: () => toggleSaveRef.current(r, true),
        });
      }
    } catch {
      flip(wasSaved);
      showToast({ message: "Couldn't update saved places. Please try again.", tone: 'error' });
    } finally {
      setSavingId(null);
    }
  };

  useEffect(() => {
    toggleSaveRef.current = handleToggleSave;
  });

  const [dynamicRestaurants, setDynamicRestaurants] = useState<RestaurantPlace[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(false);

  useEffect(() => {
    if (!isFoodSheetOpen) return;
    if (!activeDestCoords) {
      setDynamicRestaurants([]);
      return;
    }
    setIsLoading(true);

    const baseUrl = getApiBaseUrl();
    const url = `${baseUrl}/api/places/nearby?lat=${activeDestCoords[0]}&lng=${activeDestCoords[1]}&category=food&limit=25`;

    fetch(url, { headers: DEFAULT_HEADERS })
      .then(res => res.json())
      .then(data => {
        const rawItems = Array.isArray(data) ? data : (data.places || data.results || []);
        if (Array.isArray(rawItems) && rawItems.length > 0) {
          // Only what the place search returned: no made-up rating, price, hours, diet or photo.
          const formatted: RestaurantPlace[] = rawItems
            .filter((p: any) => p.name && p.latitude != null && p.longitude != null)
            .map((p: any, idx: number) => {
              const meters = p.distanceMeters ?? p.distance_meters;
              return {
                id: p.id || `food-${idx}`,
                name: p.name,
                rating: typeof p.rating === 'number' ? p.rating : null,
                cuisine: p.cuisine ? (Array.isArray(p.cuisine) ? p.cuisine : [p.cuisine]) : (p.category ? [p.category] : []),
                location: p.address || '',
                coordinates: [p.latitude, p.longitude] as [number, number],
                distanceKm: typeof meters === 'number' ? Number((meters / 1000).toFixed(1)) : null,
                photos: Array.isArray(p.photos) ? p.photos : [],
              };
            });
          setDynamicRestaurants(formatted);
        } else {
          setDynamicRestaurants([]);
        }
      })
      .catch(err => {
        console.warn("Dynamic food places fetch error:", err);
        setDynamicRestaurants([]);
      })
      .finally(() => setIsLoading(false));
  }, [isFoodSheetOpen, activeDestCoords, activeDestName]);

  const displayRestaurants = dynamicRestaurants;

  return (
    <BottomSheet
      isOpen={isFoodSheetOpen}
      onClose={() => setIsFoodSheetOpen(false)}
      height="expanded"
      title={`Food & Dining in ${activeDestName}`}
    >
      <div className="p-4 space-y-4">
        {isLoading && (
          <div className="p-2.5 rounded-xl bg-[var(--color-surface-elevated)] border border-[var(--color-border)] text-[var(--color-primary)] text-xs font-semibold flex items-center gap-2">
            <RefreshCw className="w-3.5 h-3.5 animate-spin shrink-0" />
            <span>Fetching live nearby dining spots for {activeDestName}...</span>
          </div>
        )}
        {!isLoading && displayRestaurants.length === 0 && (
          <p className="py-6 text-center text-xs text-[var(--color-text-secondary)]">
            {activeDestCoords ? 'No restaurants found nearby.' : 'Turn on location or open a trip to see restaurants nearby.'}
          </p>
        )}

        {/* Restaurant Cards List */}
        <div className="space-y-3">
          {displayRestaurants.map(r => {
            const isSaved = savedIds.has(r.id);
            return (
              <div key={r.id} className="surface-card p-4 space-y-3">
                <div className="flex gap-3">
                  {r.photos[0] && (
                    <img
                      src={r.photos[0]}
                      alt={r.name}
                      className="w-20 h-20 rounded-xl object-cover shrink-0 bg-[var(--color-surface-elevated)]"
                      loading="lazy"
                      decoding="async"
                    />
                  )}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-start justify-between gap-2">
                      <h4 className="font-bold text-base text-[var(--color-text-primary)] min-w-0 wrap-anywhere">{r.name}</h4>
                      <button
                        onClick={() => handleToggleSave(r)}
                        disabled={savingId === r.id}
                        className="size-11 shrink-0 grid place-items-center rounded-lg hover:bg-[var(--color-surface-elevated)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-primary)] text-[var(--color-text-secondary)] disabled:opacity-50"
                        aria-label={isSaved ? `Remove ${r.name} from saved places` : `Save ${r.name}`}
                        aria-pressed={isSaved}
                      >
                        <Heart className={`w-4 h-4 ${isSaved ? 'fill-current text-rose-700 dark:text-rose-300' : ''}`} />
                      </button>
                    </div>

                    <p className="text-xs text-[var(--color-text-secondary)] flex items-center gap-1 mt-0.5">
                      <MapPin className="w-3.5 h-3.5 text-[var(--color-primary)] shrink-0" />
                      <span className="min-w-0 wrap-anywhere">{r.location}{r.distanceKm != null && <> · <span className="font-mono text-[var(--color-primary)]">{r.distanceKm} km</span></>}</span>
                    </p>

                    {(r.rating != null || r.cuisine.length > 0) && (
                      <div className="flex flex-wrap items-center gap-2 mt-1.5">
                        {r.rating != null && (
                          <span className="text-xs font-bold text-amber-800 dark:text-amber-300 flex items-center gap-1">
                            <Star className="w-3.5 h-3.5 fill-current" /> {r.rating}
                          </span>
                        )}
                        {r.rating != null && r.cuisine.length > 0 && <span className="text-xs text-[var(--color-text-secondary)]">•</span>}
                        {r.cuisine.length > 0 && <span className="text-xs text-[var(--color-text-secondary)] wrap-anywhere">{r.cuisine.join(', ')}</span>}
                      </div>
                    )}
                  </div>
                </div>

                {/* 1-Tap Action Buttons */}
                <div className="flex flex-wrap gap-2 pt-1 border-t border-[var(--color-border)]">
                  <button
                    onClick={() => {
                      setIsFoodSheetOpen(false);
                      openCabModal(r.name);
                    }}
                    className="flex-1 touch-target press-scale py-2.5 rounded-xl bg-[var(--color-primary)] text-white dark:text-zinc-950 hover:brightness-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-primary)] font-bold text-xs flex items-center justify-center gap-1.5"
                  >
                    <Car className="w-4 h-4" /> Book Cab Ride
                  </button>
                  <button
                    onClick={() => {
                      if (r.coordinates && r.coordinates[0] && r.coordinates[1]) {
                        openInAppNavigation({
                          title: r.name,
                          locationName: r.location,
                          coordinates: r.coordinates,
                        });
                        setIsFoodSheetOpen(false);
                      }
                    }}
                    className="flex-1 touch-target press-scale py-2.5 rounded-xl bg-[var(--color-surface-elevated)] border border-[var(--color-border)] text-[var(--color-text-primary)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-primary)] font-semibold text-xs flex items-center justify-center gap-1.5"
                  >
                    <Navigation className="w-4 h-4 text-[var(--color-primary)]" /> Directions
                  </button>
                </div>
              </div>
            );
          })}

        </div>
      </div>
    </BottomSheet>
  );
};
