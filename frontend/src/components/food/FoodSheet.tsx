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
          <div className="p-2.5 rounded-xl bg-teal-500/10 border border-teal-500/30 text-teal-300 text-xs font-semibold flex items-center gap-2">
            <RefreshCw className="w-3.5 h-3.5 animate-spin text-teal-400" />
            <span>Fetching live nearby dining spots for {activeDestName}...</span>
          </div>
        )}
        {!isLoading && displayRestaurants.length === 0 && (
          <p className="py-6 text-center text-xs text-slate-400">
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
                      className="w-20 h-20 rounded-xl object-cover shrink-0 bg-slate-800"
                      loading="lazy"
                      decoding="async"
                    />
                  )}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-start justify-between">
                      <h4 className="font-bold text-base text-white truncate">{r.name}</h4>
                      <button
                        onClick={() => handleToggleSave(r)}
                        disabled={savingId === r.id}
                        className="p-1 rounded-lg hover:bg-white/10 text-slate-400 disabled:opacity-50"
                        aria-label={isSaved ? `Remove ${r.name} from saved places` : `Save ${r.name}`}
                        aria-pressed={isSaved}
                      >
                        <Heart className={`w-4 h-4 ${isSaved ? 'fill-rose-500 text-rose-500' : ''}`} />
                      </button>
                    </div>

                    <p className="text-xs text-slate-400 flex items-center gap-1 mt-0.5">
                      <MapPin className="w-3.5 h-3.5 text-teal-400 shrink-0" />
                      {r.location}{r.distanceKm != null && <> · <span className="font-mono text-teal-300">{r.distanceKm} km</span></>}
                    </p>

                    {(r.rating != null || r.cuisine.length > 0) && (
                      <div className="flex items-center gap-2 mt-1.5">
                        {r.rating != null && (
                          <span className="text-xs font-bold text-amber-400 flex items-center gap-1">
                            <Star className="w-3.5 h-3.5 fill-amber-400" /> {r.rating}
                          </span>
                        )}
                        {r.rating != null && r.cuisine.length > 0 && <span className="text-xs text-slate-400">•</span>}
                        {r.cuisine.length > 0 && <span className="text-xs text-slate-300 truncate">{r.cuisine.join(', ')}</span>}
                      </div>
                    )}
                  </div>
                </div>

                {/* 1-Tap Action Buttons */}
                <div className="flex gap-2 pt-1 border-t border-white/5">
                  <button
                    onClick={() => {
                      setIsFoodSheetOpen(false);
                      openCabModal(r.name);
                    }}
                    className="flex-1 touch-target press-scale py-2.5 rounded-xl bg-teal-500 text-slate-950 font-bold text-xs flex items-center justify-center gap-1.5 shadow-md shadow-teal-500/15"
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
                    className="flex-1 touch-target press-scale py-2.5 rounded-xl bg-white/5 border border-white/10 text-slate-200 font-semibold text-xs flex items-center justify-center gap-1.5"
                  >
                    <Navigation className="w-4 h-4 text-teal-400" /> Directions
                  </button>
                </div>
              </div>
            );
          })}

          {displayRestaurants.length === 0 && !isLoading && (
            <div className="p-8 text-center text-slate-400 text-xs">
              No dining spots found around this location.
            </div>
          )}
        </div>
      </div>
    </BottomSheet>
  );
};
