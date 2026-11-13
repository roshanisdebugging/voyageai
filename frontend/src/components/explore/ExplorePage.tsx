import React, { useState, useEffect, useRef } from 'react';
import { useToast } from '../common/UndoToast';
import { useNavigate } from 'react-router-dom';
import { useApp } from '../../context/AppContext';
import { useTrip } from '../../features/trip/TripContext';
import { useNavigation } from '../../context/NavigationContext';
import { getApiBaseUrl, DEFAULT_FETCH_OPTIONS, getAuthHeaders } from '../../config/apiConfig';
import {
  Compass, MapPin, Sparkles, Plus, Check, Calendar,
  Clock, Tag, Star, Navigation, Layers, Bookmark, AlertCircle
} from 'lucide-react';
import type { ActivityItem, EventItem } from '../../types';
import { AddToItineraryModal, type ItineraryDayOption } from '../itinerary/AddToItineraryModal';
import { sanitizeLocationName } from '../../utils/locationSanitizer';
import { isMockPayload } from '../../utils/mockIndicator';
import { MockCardAlert } from '../common/MockCardAlert';
import { getSavedPlaces, savePlace, removeSavedPlace } from '../../services/savedPlacesApi';

export const ExplorePage: React.FC = () => {
  const navigate = useNavigate();
  const { userLocationName, userLocation } = useApp();
  const { currentTrip, currentItinerary, refetchItinerary } = useTrip();
  const { navigateToMap, exploreFocusTarget, setExploreFocusTarget } = useNavigation();

  // Dynamic live location city name
  const liveLocationCity = sanitizeLocationName(userLocationName);
  const liveCityName = liveLocationCity;
  const hasActiveTrip = Boolean(currentTrip?.destination?.name);

  // Context switch state: 'gps' or 'trip'
  const [contextMode, setContextMode] = useState<'gps' | 'trip'>('gps');

  // Active Category filter
  const [activeCategory, setActiveCategory] = useState<string>('All');
  const { showToast } = useToast();
  const handleToggleSaveRef = useRef<(item: ActivityItem, fromUndo?: boolean) => Promise<void>>(async () => {});

  // Spotlight Data fetched from backend or dynamic fallback
  const activeDestinationName = (contextMode === 'trip' && currentTrip?.destination?.name)
    ? currentTrip.destination.name
    : liveLocationCity;

  const [spotlightDestination, setSpotlightDestination] = useState<string>(activeDestinationName);
  const [spotlightOverview, setSpotlightOverview] = useState<string>('');
  const [spotlightActivities, setSpotlightActivities] = useState<ActivityItem[]>([]);
  const [spotlightEvents, setSpotlightEvents] = useState<EventItem[]>([]);
  const [isLoadingSpotlight, setIsLoadingSpotlight] = useState<boolean>(false);

  // Day picker modal state & added item day map
  const [selectedPlaceForModal, setSelectedPlaceForModal] = useState<any | null>(null);
  const [addedItemDays, setAddedItemDays] = useState<Map<string, number>>(new Map());

  // Saved Places Management State & Handlers
  const [savedPlaceIds, setSavedPlaceIds] = useState<Set<string>>(new Set());

  useEffect(() => {
    let active = true;
    const fetchSavedPlaces = async () => {
      try {
        const data = await getSavedPlaces();
        if (active && Array.isArray(data)) {
          setSavedPlaceIds(new Set(data.map((p) => p.place_id)));
        }
      } catch (err) {
        console.warn('[FETCH SAVED PLACES WARN]', err);
      }
    };
    fetchSavedPlaces();
    return () => {
      active = false;
    };
  }, []);

  const handleToggleSave = async (item: ActivityItem, fromUndo = false) => {
    const isSaved = savedPlaceIds.has(item.id);
    setSavedPlaceIds(prev => {
      const next = new Set(prev);
      if (isSaved) next.delete(item.id);
      else next.add(item.id);
      return next;
    });

    try {
      if (isSaved) {
        await removeSavedPlace(item.id);
      } else {
        await savePlace({
          place_id: item.id,
          title: item.title,
          category: item.category,
          location_name: item.location,
          location: item.location,
          coordinates: item.coordinates,
          rating: item.rating,
          cost_text: item.cost ? `₹${item.cost}` : undefined,
          duration_text: item.duration,
          description: item.description,
        });
      }
      if (!fromUndo) {
        showToast({
          message: isSaved ? `Removed ${item.title} from saved places` : `Saved ${item.title}`,
          undo: () => handleToggleSaveRef.current(item, true),
        });
      }
    } catch (err) {
      console.warn('[SAVE PLACE ERROR]', err);
      setSavedPlaceIds(prev => {
        const next = new Set(prev);
        if (isSaved) next.add(item.id);
        else next.delete(item.id);
        return next;
      });
      showToast({ message: "Couldn't update saved places. Please try again.", tone: 'error' });
    }
  };
  useEffect(() => {
    handleToggleSaveRef.current = handleToggleSave;
  });

  const changeCategory = (cat: string) => {
    if (cat === activeCategory) return;
    const previous = activeCategory;
    setActiveCategory(cat);
    showToast({ message: `Showing ${cat}`, undo: () => setActiveCategory(previous) });
  };

  const handleNavigate = (item: ActivityItem) => {
    if (item.coordinates && item.coordinates.length === 2 && item.coordinates[0] !== 0) {
      const [lat, lng] = item.coordinates;
      window.open(`https://www.google.com/maps/dir/?api=1&destination=${lat},${lng}`, '_blank');
    } else {
      window.open(`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(item.title + ' ' + item.location)}`, '_blank');
    }
  };

  const handleAskAI = (item: ActivityItem) => {
    window.dispatchEvent(new CustomEvent('voyage:ai-query', {
      detail: { query: `Tell me more about ${item.title} in ${item.location}. What are the must-try items, best timings, and local tips?` }
    }));
  };

  // Highlight ref for deep-linked place
  const cardRefs = useRef<{ [key: string]: HTMLDivElement | null }>({});

  // 1. Fetch AI Destination Highlights from /api/trips/:destination/highlights
  useEffect(() => {
    let isMounted = true;
    const fetchHighlights = async () => {
      setIsLoadingSpotlight(true);
      const dest = activeDestinationName;

      const queryParams: string[] = [];
      if (contextMode === 'gps') {
        if (userLocation && userLocation[0] && userLocation[1]) {
          queryParams.push(`lat=${userLocation[0]}&lng=${userLocation[1]}`);
        }
        if (dest) {
          queryParams.push(`destination=${encodeURIComponent(dest)}`);
        }
      } else {
        if (dest) {
          queryParams.push(`destination=${encodeURIComponent(dest)}`);
        }
        if (currentTrip?.destination?.latitude && currentTrip?.destination?.longitude) {
          queryParams.push(`lat=${currentTrip.destination.latitude}&lng=${currentTrip.destination.longitude}`);
        }
      }

      const baseUrl = getApiBaseUrl();
      const endpoint = `${baseUrl}/api/trips/highlights?${queryParams.join('&')}`;

      try {
        const res = await fetch(endpoint, {
          ...DEFAULT_FETCH_OPTIONS,
        });

        if (res.ok) {
          const json = await res.json();

          if (isMounted) {
            const fetchedActs = Array.isArray(json?.activities)
              ? json.activities
              : Array.isArray(json?.famous_activities)
                ? json.famous_activities
                : [];

            const fetchedEvts = Array.isArray(json?.events)
              ? json.events
              : Array.isArray(json?.upcoming_events)
                ? json.upcoming_events
                : [];

            setSpotlightDestination(json?.destination || dest);
            setSpotlightOverview(json?.overview || '');
            setSpotlightActivities(fetchedActs);
            setSpotlightEvents(fetchedEvts);
            setIsLoadingSpotlight(false);
            return;
          }
        }
      } catch (err: any) {
        console.warn('[EXPLORE] Failed to fetch spotlight highlights:', err);
      }

      if (isMounted) {
        setSpotlightActivities([]);
        setSpotlightEvents([]);
        setIsLoadingSpotlight(false);
      }
    };

    fetchHighlights();

    return () => {
      isMounted = false;
    };
  }, [activeDestinationName, contextMode]);

  // 2. Handle deep link from Map mode
  useEffect(() => {
    if (exploreFocusTarget?.placeId) {
      if (exploreFocusTarget.category) {
        setActiveCategory(exploreFocusTarget.category);
      }
      const el = cardRefs.current[exploreFocusTarget.placeId];
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
      // Clear focus target after handling
      const timer = setTimeout(() => {
        setExploreFocusTarget(null);
      }, 2000);
      return () => clearTimeout(timer);
    }
  }, [exploreFocusTarget, setExploreFocusTarget]);

  const [isAddingToItinerary, setIsAddingToItinerary] = useState(false);
  const [exploreToast, setExploreToast] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  const modalDays: ItineraryDayOption[] = React.useMemo(() => {
    if (currentItinerary?.days && currentItinerary.days.length > 0) {
      return currentItinerary.days.map((d) => ({
        id: d.id,
        dayNumber: d.dayNumber,
        title: d.title || `Day ${d.dayNumber}`,
      }));
    }
    const totalDays = currentTrip?.totalDays || 3;
    return Array.from({ length: Math.max(totalDays, 1) }, (_, i) => ({
      id: `day_${i + 1}`,
      dayNumber: i + 1,
      title: `Day ${i + 1} Highlights`,
    }));
  }, [currentItinerary, currentTrip]);

  // Handle Add to Itinerary confirmation from modal
  const handleConfirmAddToItinerary = async (dayId: string, timeSlot: string) => {
    if (!selectedPlaceForModal) return;
    setIsAddingToItinerary(true);

    const targetDay = modalDays.find((d) => d.id === dayId);
    const dayNumber = targetDay?.dayNumber || 1;
    const priceStr = selectedPlaceForModal.price_approx || (selectedPlaceForModal.cost ? String(selectedPlaceForModal.cost) : 'Free Entry');
    const digits = priceStr.replace(/[^\d]/g, '');
    const costInt = digits ? parseInt(digits, 10) : 0;
    const loc = selectedPlaceForModal.location || selectedPlaceForModal.address || activeDestinationName;

    const payload = {
      trip_id: currentTrip?.id || 'active_trip',
      destination: activeDestinationName,
      item_id: selectedPlaceForModal.id,
      day_id: dayId,
      day_number: dayNumber,
      time_slot: timeSlot,
      title: selectedPlaceForModal.title || selectedPlaceForModal.name,
      location: loc,
      location_name: loc,
      tag: selectedPlaceForModal.tag || selectedPlaceForModal.category || 'spotlight',
      price: priceStr,
      estimated_cost_inr: costInt,
      activity_type: selectedPlaceForModal.item_type || 'spotlight',
      is_confirmed: true,
    };

    try {
      const baseUrl = getApiBaseUrl();
      const res = await fetch(`${baseUrl}/api/trips/itinerary/add`, {
        ...DEFAULT_FETCH_OPTIONS,
        method: 'POST',
        headers: {
          ...DEFAULT_FETCH_OPTIONS.headers,
          ...getAuthHeaders(),
        },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        let detail = `Failed to add item (Status: ${res.status})`;
        try {
          const errJson = await res.json();
          if (errJson.detail) detail = errJson.detail;
          else if (errJson.message) detail = errJson.message;
        } catch (_) {}
        throw new Error(detail);
      }

      setAddedItemDays((prev) => new Map(prev).set(selectedPlaceForModal.id, dayNumber));
      setSelectedPlaceForModal(null);
      setExploreToast({
        type: 'success',
        message: `Added "${payload.title}" to Day ${dayNumber} (${timeSlot})!`,
      });
      setTimeout(() => setExploreToast(null), 3500);

      if (refetchItinerary) {
        await refetchItinerary(currentTrip?.id || payload.trip_id);
      }
    } catch (err: any) {
      console.warn('[EXPLORE] Add to itinerary API error:', err);
      setExploreToast({
        type: 'error',
        message: err.message || 'Failed to add item to itinerary.',
      });
      setTimeout(() => setExploreToast(null), 4000);
    } finally {
      setIsAddingToItinerary(false);
    }
  };

  const categories = ['All', 'Food', 'Sights', 'Events', 'Nightlife', 'Culture', 'Adventure'];

  const filteredActivities = spotlightActivities.filter((act) => {
    if (activeCategory === 'All') return true;
    if (activeCategory === 'Events') return false;
    const catLower = (act.category || '').toLowerCase();
    const tagLower = (act.tag || '').toLowerCase();
    const filterLower = activeCategory.toLowerCase();
    return catLower.includes(filterLower) || tagLower.includes(filterLower);
  });

  return (
    <div className="w-full max-w-xl mx-auto px-4 pb-28 space-y-6 bg-white text-gray-900 overflow-x-hidden animate-fadeIn min-h-screen">

      {/* ── 1. Top Header ── */}
      <div className="space-y-3 pt-2 w-full max-w-full overflow-hidden">
        <div className="flex items-center justify-between">
          <div className="min-w-0 flex-1">
            <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2 tracking-tight truncate">
              <Compass className="w-6 h-6 text-[#1F5A3F] shrink-0" />
              Explore &amp; Discover
            </h1>
            <p className="text-xs font-medium text-gray-500 mt-0.5 truncate">
              Curated experiences, AI spot highlights &amp; itinerary builder
            </p>
          </div>

          <button
            onClick={() => {
              const coords = userLocation || (currentTrip?.destination?.latitude && currentTrip?.destination?.longitude ? [currentTrip.destination.latitude, currentTrip.destination.longitude] as [number, number] : null);
              if (coords) {
                navigateToMap({
                  id: 'user-live',
                  name: liveCityName,
                  coordinates: coords,
                  zoom: 16
                });
              } else {
                navigateToMap();
              }
            }}
            className="px-3.5 py-1.5 rounded-xl bg-white hover:bg-gray-50 border border-gray-200 text-[#1F5A3F] text-xs font-semibold flex items-center gap-1.5 shadow-sm transition-all press-scale shrink-0"
          >
            <Navigation className="w-3.5 h-3.5 fill-[#1F5A3F]" />
            Map Mode
          </button>
        </div>

        {/* ── 2. Context Switcher (Near Me vs Trip) ── */}
        <div className="p-1 rounded-2xl bg-gray-50 border border-gray-200 flex gap-1 w-full max-w-full">
          <button
            onClick={() => setContextMode('gps')}
            className={`flex-1 min-w-0 py-2 px-3 rounded-xl text-xs font-semibold transition-all flex items-center justify-center gap-1.5 ${contextMode === 'gps' || !hasActiveTrip
                ? 'bg-[#1F5A3F] text-white shadow-sm'
                : 'text-gray-500 hover:text-gray-900'
              }`}
          >
            <MapPin className="w-3.5 h-3.5 shrink-0" />
            <span className="truncate">Near Me ({liveCityName})</span>
          </button>

          {hasActiveTrip ? (
            <button
              onClick={() => setContextMode('trip')}
              className={`flex-1 min-w-0 py-2 px-3 rounded-xl text-xs font-semibold transition-all flex items-center justify-center gap-1.5 ${contextMode === 'trip'
                  ? 'bg-[#1F5A3F] text-white shadow-sm'
                  : 'text-gray-500 hover:text-gray-900'
                }`}
            >
              <Sparkles className="w-3.5 h-3.5 shrink-0" />
              <span className="truncate">Trip ({currentTrip?.destination?.name})</span>
            </button>
          ) : (
            <button
              onClick={() => navigate('/trips')}
              className="flex-1 min-w-0 py-2 px-3 rounded-xl text-xs font-semibold text-gray-400 hover:text-gray-600 border border-dashed border-gray-300 flex items-center justify-center gap-1.5"
            >
              <Plus className="w-3.5 h-3.5 shrink-0" />
              <span className="truncate">Plan a Trip</span>
            </button>
          )}
        </div>
      </div>

      {/* ── 2. AI Destination Spotlight Banner ── */}
      <div className="relative overflow-hidden rounded-3xl bg-[#1F5A3F] p-5 shadow-lg w-full max-w-full">
        <div className="absolute top-0 right-0 w-64 h-64 bg-white/5 rounded-full blur-3xl pointer-events-none" />
        <div className="absolute bottom-0 left-0 w-48 h-48 bg-black/10 rounded-full blur-3xl pointer-events-none" />

        <div className="relative z-10 space-y-3 w-full max-w-full">
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <span className="px-3 py-1 rounded-full bg-white/10 border border-white/15 text-white/90 text-[11px] font-semibold flex items-center gap-1 shrink-0">
              <Sparkles className="w-3 h-3" /> AI Destination Spotlight
            </span>
            <span className="text-xs font-semibold text-amber-200 flex items-center gap-1 shrink-0">
              <Star className="w-3.5 h-3.5 fill-amber-200" /> 4.9 Superb
            </span>
          </div>

          <div className="w-full max-w-full">
            <h2 className="text-xl font-semibold text-white tracking-tight break-words">
              {spotlightDestination} Highlights
            </h2>
            <p className="text-xs text-white/75 mt-1 leading-relaxed break-words">
              {spotlightOverview}
            </p>
          </div>

          <div className="pt-2 flex items-center gap-4 text-xs font-medium text-white/70 border-t border-white/15 flex-wrap">
            <div className="flex items-center gap-1 text-white">
              <Check className="w-3.5 h-3.5" /> {spotlightActivities.length} Top Places
            </div>
            <div className="flex items-center gap-1 text-white">
              <Calendar className="w-3.5 h-3.5" /> {spotlightEvents.length} Live Events
            </div>
          </div>
        </div>
      </div>

      {/* ── 3. Category Filter Pills ── */}
      <div className="w-full max-w-full flex items-center gap-5 overflow-x-auto no-scrollbar border-b border-gray-200">
        {categories.map((cat) => {
          const isActive = activeCategory === cat;
          return (
            <button
              key={cat}
              onClick={() => changeCategory(cat)}
              className={`press-scale shrink-0 pb-2.5 text-xs font-semibold transition-all relative ${isActive ? 'text-gray-900' : 'text-gray-400 hover:text-gray-600'
                }`}
            >
              {cat}
              {isActive && (
                <span className="absolute left-0 right-0 -bottom-px h-0.5 bg-[#1F5A3F] rounded-full" />
              )}
            </button>
          );
        })}
      </div>

      {/* ── 4. Upcoming Events Carousel (Shown when 'All' or 'Events' selected) ── */}
      {(activeCategory === 'All' || activeCategory === 'Events') && spotlightEvents.length > 0 && (
        <div className="space-y-3 w-full max-w-full overflow-hidden">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Calendar className="w-4 h-4 text-[#1F5A3F] shrink-0" />
              Upcoming Events &amp; Festivals
            </h3>
            <span className="text-xs text-[#1F5A3F] font-semibold truncate">Live in {spotlightDestination}</span>
          </div>

          <div className="w-full max-w-full flex gap-4 overflow-x-auto no-scrollbar pb-2">
            {spotlightEvents.map((evt) => (
              <div
                key={evt.id}
                className="shrink-0 w-64 rounded-2xl bg-white border border-gray-200 overflow-hidden shadow-sm space-y-2 p-3"
              >
                <div className="h-32 rounded-xl overflow-hidden relative bg-gray-100">
                  <img src={evt.image} alt={evt.title} className="w-full h-full object-cover" loading="lazy" decoding="async" />
                  <span className="absolute top-2 left-2 px-2 py-0.5 rounded-full bg-white/90 text-[10px] font-semibold text-[#1F5A3F] border border-gray-200">
                    {evt.tag || evt.category}
                  </span>
                </div>
                <div>
                  <h4 className="text-xs font-semibold text-gray-900 line-clamp-1">{evt.title}</h4>
                  <p className="text-[11px] text-gray-500 flex items-center gap-1 mt-0.5">
                    <Clock className="w-3 h-3 text-gray-400" /> {evt.date} • {evt.time}
                  </p>
                  <p className="text-[11px] text-[#1F5A3F] font-semibold mt-1">₹{evt.price} per ticket</p>
                  {contextMode === 'trip' && (
                    <button
                      type="button"
                      onClick={() => setSelectedPlaceForModal(evt)}
                      className={`w-full mt-2 py-1.5 px-3 rounded-xl font-semibold text-xs flex items-center justify-center gap-1.5 transition-all press-scale ${
                        addedItemDays.has(evt.id)
                          ? 'bg-[#1F5A3F]/10 text-[#1F5A3F] border border-[#1F5A3F]/30'
                          : 'bg-[#1F5A3F] hover:bg-[#194B34] text-white shadow-xs'
                      }`}
                    >
                      {addedItemDays.has(evt.id) ? (
                        <>
                          <Check className="w-3.5 h-3.5 stroke-[3]" /> Added to Day {addedItemDays.get(evt.id)}
                        </>
                      ) : (
                        <>
                          <Plus className="w-3.5 h-3.5 stroke-[3]" />
                          <span>Add to Itinerary</span>
                        </>
                      )}
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── 5. Filtered Activity Cards List ── */}
      {activeCategory !== 'Events' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Layers className="w-4 h-4 text-[#1F5A3F]" />
              Must-Visit Places &amp; Activities ({filteredActivities.length})
            </h3>
          </div>

          {isLoadingSpotlight ? (
            <div className="py-12 text-center text-xs font-medium text-gray-400 animate-pulse">
              Loading AI-curated destination highlights...
            </div>
          ) : filteredActivities.length === 0 ? (
            <div className="py-12 text-center text-xs font-medium text-gray-400 bg-gray-50 rounded-3xl border border-gray-200 p-6">
              No active spotlights found in this immediate area. Expand your radius or search nearby hubs.
            </div>
          ) : (
            filteredActivities.map((act) => {
              if (isMockPayload(act)) {
                return (
                  <MockCardAlert
                    key={act.id}
                    title={act.title}
                    location={act.location}
                    headsUp={act.description || 'MOCK: Live data failed to fetch from backend'}
                  />
                );
              }

              const isFocusTarget = exploreFocusTarget?.placeId === act.id;

              return (
                <div
                  key={act.id}
                  ref={(el) => { cardRefs.current[act.id] = el; }}
                  className={`group rounded-3xl overflow-hidden bg-white border transition-all duration-300 shadow-sm ${isFocusTarget
                      ? 'border-[#1F5A3F] ring-2 ring-[#1F5A3F]/30'
                      : 'border-gray-200 hover:border-[#1F5A3F]/40'
                    }`}
                >
                  {/* Card Cover Image with Gradient Overlay */}
                  <div className="h-48 relative overflow-hidden bg-gray-100">
                    <img
                      src={act.photos?.[0] || getFallbackImage(act.category)}
                      alt={act.title}
                      className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500"
                      loading="lazy"
                      decoding="async"
                    />
                    <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-black/20 to-transparent" />

                    {/* Tag Pill */}
                    <span className="absolute top-3 left-3 px-3 py-1 rounded-full bg-white/90 backdrop-blur-md text-[11px] font-semibold text-[#1F5A3F] border border-white/40 flex items-center gap-1">
                      <Tag className="w-3 h-3" />
                      {act.tag || act.category}
                    </span>

                    {/* Duration & Rating */}
                    <div className="absolute top-3 right-3 flex items-center gap-1.5">
                      <span className="px-2.5 py-1 rounded-lg bg-white/90 backdrop-blur-md text-[11px] font-semibold text-gray-600 border border-white/40 flex items-center gap-1">
                        <Clock className="w-3 h-3 text-gray-500" /> {act.duration}
                      </span>
                      <span className="px-2.5 py-1 rounded-lg bg-white/90 backdrop-blur-md text-[11px] font-semibold text-amber-600 border border-white/40 flex items-center gap-1">
                        <Star className="w-3 h-3 fill-amber-500" /> {act.rating || 4.8}
                      </span>
                    </div>

                    {/* Title & Location Overlay */}
                    <div className="absolute bottom-3 left-3 right-3">
                      <h3 className="text-lg font-semibold text-white leading-tight drop-shadow-md">
                        {act.title}
                      </h3>
                      <p className="text-xs text-white/85 mt-0.5 flex items-center gap-1">
                        <MapPin className="w-3.5 h-3.5 shrink-0" />
                        <span className="truncate">{act.location}</span>
                      </p>
                    </div>
                  </div>

                  {/* Card Content & Action CTAs */}
                  <div className="p-4 space-y-3">
                    <p className="text-xs text-gray-500 line-clamp-2 leading-relaxed">
                      {act.description}
                    </p>

                    <div className="flex items-center justify-between pt-3 border-t border-gray-100 text-xs gap-2">
                      <span className="font-semibold text-[#1F5A3F]">
                        {act.cost > 0 ? `Est. ₹${act.cost}` : 'Free Entry'}
                      </span>

                      <div className="flex items-center gap-1.5">
                        {/* 1. Navigate / Directions (Both Modes) */}
                        <button
                          onClick={() => handleNavigate(act)}
                          className="p-2 rounded-xl bg-gray-50 hover:bg-gray-100 text-gray-500 hover:text-gray-900 border border-gray-200 transition-all press-scale"
                          title="Get Directions in Google Maps"
                        >
                          <Navigation className="w-3.5 h-3.5 text-[#1F5A3F]" />
                        </button>

                        {/* 2. Save Place / Bookmark (Both Modes) */}
                        <button
                          onClick={() => handleToggleSave(act)}
                          className={`p-2 rounded-xl border transition-all press-scale ${savedPlaceIds.has(act.id)
                              ? 'bg-[#1F5A3F]/10 text-[#1F5A3F] border-[#1F5A3F]/30'
                              : 'bg-gray-50 hover:bg-gray-100 text-gray-500 hover:text-gray-900 border-gray-200'
                            }`}
                          title={savedPlaceIds.has(act.id) ? 'Saved' : 'Save Place'}
                        >
                          <Bookmark className={`w-3.5 h-3.5 ${savedPlaceIds.has(act.id) ? 'fill-[#1F5A3F] text-[#1F5A3F]' : ''}`} />
                        </button>

                        {/* 3. Ask AI (Both Modes) */}
                        <button
                          onClick={() => handleAskAI(act)}
                          className="p-2 rounded-xl bg-gray-50 hover:bg-gray-100 text-gray-500 hover:text-gray-900 border border-gray-200 transition-all press-scale flex items-center gap-1"
                          title="Ask AI Concierge"
                        >
                          <Sparkles className="w-3.5 h-3.5 text-amber-500" />
                        </button>

                        {/* 4. Add to Itinerary (ONLY IN TRIP MODE) */}
                        {contextMode === 'trip' && (
                          <button
                            onClick={() => setSelectedPlaceForModal(act)}
                            className={`px-3 py-2 rounded-xl font-semibold text-xs flex items-center gap-1.5 transition-all press-scale ${addedItemDays.has(act.id)
                                ? 'bg-[#1F5A3F]/10 text-[#1F5A3F] border border-[#1F5A3F]/30'
                                : 'bg-[#1F5A3F] hover:bg-[#194B34] text-white shadow-sm'
                              }`}
                          >
                            {addedItemDays.has(act.id) ? (
                              <>
                                <Check className="w-3.5 h-3.5 stroke-[3]" /> Added to Day {addedItemDays.get(act.id)}
                              </>
                            ) : (
                              <>
                                <Plus className="w-3.5 h-3.5 stroke-[3]" />
                                <span>Add to Itinerary</span>
                              </>
                            )}
                          </button>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              );
            })
          )}
        </div>
      )}

      {/* Day Picker Bottom Sheet Modal */}
      <AddToItineraryModal
        isOpen={Boolean(selectedPlaceForModal)}
        onClose={() => {
          if (!isAddingToItinerary) setSelectedPlaceForModal(null);
        }}
        itemTitle={selectedPlaceForModal?.title || selectedPlaceForModal?.name || ''}
        days={modalDays}
        isSubmitting={isAddingToItinerary}
        onConfirm={handleConfirmAddToItinerary}
        category={selectedPlaceForModal?.tag || selectedPlaceForModal?.category}
        location={selectedPlaceForModal?.location || selectedPlaceForModal?.address}
        price={selectedPlaceForModal?.cost ?? selectedPlaceForModal?.price}
      />

      {/* Floating Feedback Toast Notification */}
      {exploreToast && (
        <div
          role="alert"
          className={`fixed bottom-6 left-1/2 -translate-x-1/2 z-[10000] px-4 py-2.5 rounded-2xl text-xs font-black flex items-center gap-2 shadow-2xl animate-bounce ${
            exploreToast.type === 'success'
              ? 'bg-emerald-500 text-slate-950 shadow-emerald-500/25'
              : 'bg-rose-500 text-white shadow-rose-500/25'
          }`}
        >
          {exploreToast.type === 'success' ? (
            <Check className="w-4 h-4 stroke-[3]" />
          ) : (
            <AlertCircle className="w-4 h-4" />
          )}
          <span>{exploreToast.message}</span>
        </div>
      )}

    </div>
  );
};

// Fallback image provider
function getFallbackImage(category: string): string {
  const cat = (category || '').toLowerCase();
  if (cat.includes('food') || cat.includes('culinary')) {
    return 'https://images.unsplash.com/photo-1555396273-367ea4eb4db5?auto=format&fit=crop&w=600&q=80';
  }
  if (cat.includes('beach') || cat.includes('sights')) {
    return 'https://images.unsplash.com/photo-1512343879784-a960bf40e7f2?auto=format&fit=crop&w=600&q=80';
  }
  if (cat.includes('culture') || cat.includes('heritage')) {
    return 'https://images.unsplash.com/photo-1548013146-72479768bada?auto=format&fit=crop&w=600&q=80';
  }
  return 'https://images.unsplash.com/photo-1507525428034-b723cf961d3e?auto=format&fit=crop&w=600&q=80';
}


