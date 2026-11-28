import React, { useState, useEffect, useLayoutEffect, useRef, useMemo, useCallback } from 'react';
import { useApp } from '../../context/AppContext';
import { useTrip } from '../../features/trip/TripContext';
import { useNavigation } from '../../context/NavigationContext';
import {
  Crosshair, Volume2, VolumeX, Loader2,
  ArrowLeft, Search, X, MapPin, Layers, Box, MapPinOff, Navigation
} from 'lucide-react';
import { MarkerClusterer, SuperClusterAlgorithm } from '@googlemaps/markerclusterer';
import './mapView.css';
import { getApiBaseUrl, DEFAULT_HEADERS } from '../../config/apiConfig';
import { useAudioGuide } from '../../hooks/useAudioGuide';
import { AddToItineraryModal } from '../itinerary/AddToItineraryModal';
import { usePlaceItineraryAdd } from '../itinerary/usePlaceItineraryAdd';
import { useCanAddToTrip } from '../../features/trip/useCanAddToTrip';
import { useSavedPlaceToggle } from '../places/useSavedPlaceToggle';
import { useNavigate } from 'react-router-dom';
import { getCanonicalCategory, type CanonicalCategoryKey } from './mapCategoryConfig';
import { useTheme } from '../../context/ThemeContext';
import { isInIndia, placeSubtitle } from '../../features/trip/components/PlaceSearchField';
import { mapSearchErrorMessage } from '../../utils/mapSearchError';
import { lookupPlace, resolvePlace, suggestPlaces, SUGGEST_MIN_CHARS, type PlaceSuggestion } from '../../services/placesApi';
import type { DestinationReference } from '../../features/trip/types';
import { MAP_ID, loadGoogleLibrary, onMapsAuthFailure, MapUnavailableError } from './googleMapsLoader';
import {
  CLUSTER_OPTIONS, MAP_TYPES, type MapTypeKey, easeInOutCubic, flyDurationMs, flyZoom, formatDistance,
  formatStraightLine, haversineMeters, pinStyle, shouldCluster,
  DEFAULT_ROUTE_MODE, ROUTE_MODES, type RouteMode, canRoute, formatRouteSummary,
} from './mapLogic';
import { RouteError, type RouteResult } from '../../services/routesApi';
import { deviceLocation, useDeviceLocation } from '../../services/useDeviceLocation';
import { farKm, noLocationReason, originLabel, travelPlan } from '../../services/deviceLocationLogic';
import { RouteOriginSheet } from '../common/RouteOriginSheet';
import { createClusterBubble, createPlacePin, createSearchPin, createUserDot, setPinSelected } from './mapPins';
import { GoogleMapsAttribution } from '../common/GoogleMapsAttribution';
import { PlaceCardActions } from './PlaceCardActions';

// Shown when there is no location and no trip yet, so search still works.
const INDIA_CENTER: [number, number] = [22.9734, 78.6569];
// Where the map was when the user opened a place's Details page; restored once on the way back.
let returnView: { center: [number, number]; zoom: number } | null = null;
const SEARCH_DEBOUNCE_MS = 300;
const formatSearchDistance = formatStraightLine;
const calculateDistance = haversineMeters;
/** Room for the search bar on top and the card row at the bottom when fitting markers. */
/** Room fitBounds leaves free: at the bottom, whatever lies over the map element from the floating mic down
 *  (phones: mic + attribution; desktop: also the cards, which overlay the map there). */
const fitPadding = (canvas: HTMLElement | null, side: number): google.maps.Padding => {
  const tools = canvas?.parentElement?.querySelector('.map-app-tools');
  const covered = canvas && tools ? canvas.getBoundingClientRect().bottom - tools.getBoundingClientRect().top + 14 : 0;
  return { top: 120, bottom: Math.max(90, Math.round(covered)), left: side, right: side };
};

export interface PlaceItem {
  id: string;
  name: string;
  category: string;
  canonicalCategory?: CanonicalCategoryKey;
  latitude: number;
  longitude: number;
  distanceMeters?: number;
  address?: string;
  rating?: number;
  price_approx?: string;
  description?: string;
  /** mock / sample data: never routed */
  isMock?: boolean;
}

const CATEGORY_FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'sights', label: 'Sights' },
  { key: 'food', label: 'Food' },
  { key: 'hotels', label: 'Stays' },
  { key: 'experiences', label: 'Experiences' },
] as const;

const sentenceCase = (s: string) => (s ? s.charAt(0).toUpperCase() + s.slice(1).toLowerCase() : s);

type MapStatus = 'loading' | 'ready' | 'unavailable';
interface MarkerRecord { marker: google.maps.marker.AdvancedMarkerElement; el: HTMLElement; place: PlaceItem }
/** The view kept across a theme switch (Google sets the colour scheme only when a map is created). */
interface SavedView { center: google.maps.LatLngLiteral; zoom: number; tilt: number; heading: number; mapType: MapTypeKey }

const prefersReducedMotion = () =>
  typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

/** `tools`: the floating mic (its slot), drawn over the map above Google's attribution. */
export const MapView: React.FC<{ tools?: React.ReactNode }> = ({ tools }) => {
  const { userLocation, isFollowMode, setIsFollowMode } = useApp();
  const { currentTrip } = useTrip();
  const { mapFocusTarget, setMapFocusTarget, navigateToExplore } = useNavigation();
  const navigate = useNavigate();
  const { theme } = useTheme();

  // Coordinates anchor - dynamically resolved exclusively from GPS or trip destination
  const activeCoords: [number, number] | null = useMemo(() => {
    if (userLocation && typeof userLocation[0] === 'number' && typeof userLocation[1] === 'number') {
      return [userLocation[0], userLocation[1]];
    }
    if (currentTrip?.destination?.latitude && currentTrip?.destination?.longitude) {
      return [currentTrip.destination.latitude, currentTrip.destination.longitude];
    }
    return null;
  }, [userLocation, currentTrip]);

  const [allPlaces, setAllPlaces] = useState<PlaceItem[]>([]);
  // Voice "Hawa Mahal ke paas restaurant": these replace the nearby places (markers + cards) until cleared.
  const [voiceResults, setVoiceResults] = useState<{ title: string; places: PlaceItem[] } | null>(null);
  const basePlaces = voiceResults ? voiceResults.places : allPlaces;
  const [selectedPlace, setSelectedPlace] = useState<PlaceItem | null>(null);
  /** The place shown in the slide-up sheet (a pin tap, or a place sent here from Explore). */
  const [sheetPlace, setSheetPlace] = useState<PlaceItem | null>(null);
  const [activeCategory, setActiveCategory] = useState<CanonicalCategoryKey>('all');
  const [isLoadingPlaces, setIsLoadingPlaces] = useState<boolean>(false);

  // Google map state
  const [mapStatus, setMapStatus] = useState<MapStatus>('loading');
  const [mapGen, setMapGen] = useState(0);           // bumps each time a map is (re)created
  const [isVector, setIsVector] = useState(false);   // tilt / 3D only on vector maps (weak GPUs get raster)
  const [mapType, setMapType] = useState<MapTypeKey>('roadmap');
  const [is3D, setIs3D] = useState(false);
  const [showTypes, setShowTypes] = useState(false);

  // Route for the place in the sheet: only fetched on a Route tap or a mode change (never per pin)
  const [routeMode, setRouteMode] = useState<RouteMode>(DEFAULT_ROUTE_MODE);
  const [route, setRoute] = useState<{
    placeId: string; status: 'loading' | 'ok' | 'error' | 'needs_location'; result?: RouteResult; message?: string;
  } | null>(null);
  // Route origin = the device's current location only (re-read when the map opens and on "Use my location again")
  const devLoc = useDeviceLocation();
  const [originSheetFor, setOriginSheetFor] = useState<PlaceItem | null>(null);
  const routeLinesRef = useRef<google.maps.Polyline[]>([]);
  const routeSeqRef = useRef(0);

  // Audio Guide hooks
  const { playBase64Audio, stopAudio } = useAudioGuide();
  const [playingPlaceId, setPlayingPlaceId] = useState<string | null>(null);
  const [audioLoadingId, setAudioLoadingId] = useState<string | null>(null);

  // "Add to Itinerary" day picker (shared with the place details page)
  const itineraryAdd = usePlaceItineraryAdd();
  const addedPlaceDays = itineraryAdd.addedPlaceDays;
  const addToTrip = useCanAddToTrip(); // "Add to Itinerary" only for places in the open trip's area; "Save" always
  const savedToggle = useSavedPlaceToggle();

  // Map search (India only, straight-line distance from the current location)
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [searchSuggestions, setSearchSuggestions] = useState<PlaceSuggestion[]>([]);
  const [isSearching, setIsSearching] = useState<boolean>(false);
  const [searchMessage, setSearchMessage] = useState<string | null>(null);
  const [searchResult, setSearchResult] = useState<DestinationReference | null>(null);
  const searchSeqRef = useRef(0);

  const isFollowModeRef = useRef(isFollowMode);
  const hasUserPannedRef = useRef(false);
  // Read once per mount into a ref, so React's dev double-run of effects restores it too.
  const restoreViewRef = useRef(returnView);
  const hadCoordsRef = useRef<boolean>(!!activeCoords);
  const isProgrammaticMoveRef = useRef(false);
  const fittedRef = useRef(false);

  useEffect(() => { isFollowModeRef.current = isFollowMode; }, [isFollowMode]);

  // Google map & marker refs (markers are created once and updated in place; React never re-renders per frame)
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<google.maps.Map | null>(null);
  const markerLibRef = useRef<google.maps.MarkerLibrary | null>(null);
  const clustererRef = useRef<MarkerClusterer | null>(null);
  const recordsRef = useRef<Map<string, MarkerRecord>>(new Map());
  const userMarkerRef = useRef<google.maps.marker.AdvancedMarkerElement | null>(null);
  const searchMarkerRef = useRef<google.maps.marker.AdvancedMarkerElement | null>(null);
  const savedViewRef = useRef<SavedView | null>(null);
  const flyRafRef = useRef<number | null>(null);
  const onPinTapRef = useRef<(place: PlaceItem) => void>(() => {});

  // Card scroller refs: lets a marker tap scroll its matching card into view
  const cardScrollRef = useRef<HTMLDivElement>(null);
  const cardRefs = useRef<Map<string, HTMLDivElement>>(new Map());

  // ── Camera ──
  const cancelFly = useCallback(() => {
    if (flyRafRef.current != null) cancelAnimationFrame(flyRafRef.current);
    flyRafRef.current = null;
    isProgrammaticMoveRef.current = false;
  }, []);

  /** Smooth fly-to (per-frame camera moves on the map itself, no React renders). Raster/reduced motion: jump. */
  const flyTo = useCallback((lat: number, lng: number, zoom: number) => {
    const map = mapRef.current;
    if (!map) return;
    cancelFly();
    const c = map.getCenter();
    const fromZoom = map.getZoom() ?? zoom;
    if (!c || prefersReducedMotion()) {
      map.moveCamera({ center: { lat, lng }, zoom });
      return;
    }
    const from = { lat: c.lat(), lng: c.lng() };
    const dist = haversineMeters(from.lat, from.lng, lat, lng);
    const duration = flyDurationMs(dist);
    const start = performance.now();
    isProgrammaticMoveRef.current = true;
    const step = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      const e = easeInOutCubic(t);
      map.moveCamera({
        center: { lat: from.lat + (lat - from.lat) * e, lng: from.lng + (lng - from.lng) * e },
        zoom: flyZoom(fromZoom, zoom, dist, t),
      });
      if (t < 1) flyRafRef.current = requestAnimationFrame(step);
      else { flyRafRef.current = null; isProgrammaticMoveRef.current = false; }
    };
    flyRafRef.current = requestAnimationFrame(step);
  }, [cancelFly]);

  const saveReturnView = useCallback(() => {
    const map = mapRef.current;
    const c = map?.getCenter();
    if (map && c) returnView = { center: [c.lat(), c.lng()], zoom: map.getZoom() ?? 15 };
  }, []);

  // Handle Play TTS Narration
  const handlePlayNarration = useCallback(async (place: PlaceItem, e?: React.MouseEvent) => {
    if (e) e.stopPropagation();

    if (playingPlaceId === place.id) {
      stopAudio();
      setPlayingPlaceId(null);
      return;
    }

    setAudioLoadingId(place.id);
    try {
      const baseUrl = getApiBaseUrl();
      const res = await fetch(`${baseUrl}/api/tts/speak`, {
        method: 'POST',
        headers: DEFAULT_HEADERS,
        body: JSON.stringify({
          place_name: place.name,
          category: place.category,
          address: place.address || '',
          place_id: place.id,
          language: 'hi-IN',
        })
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (data.audio_base64) {
        await playBase64Audio(data.audio_base64);
        setPlayingPlaceId(place.id);
      }
    } catch (err) {
      console.warn('[MAP TTS] Narration failed:', err);
    } finally {
      setAudioLoadingId(null);
    }
  }, [playingPlaceId, playBase64Audio, stopAudio]);

  // Fetch ALL nearby POIs once per location anchor (never on category filter click!)
  const fetchMapPlaces = useCallback(async (
    centerLat: number,
    centerLng: number
  ) => {
    setIsLoadingPlaces(true);
    try {
      const baseUrl = getApiBaseUrl();
      // Fetch all nearby POIs in one call so category filtering is completely client-side
      const url = `${baseUrl}/api/places/nearby?lat=${centerLat}&lng=${centerLng}&radius=5000&limit=40`;

      const res = await fetch(url, { headers: DEFAULT_HEADERS });

      if (res.ok) {
        const data = await res.json();
        const rawItems = Array.isArray(data)
          ? data
          : (data.places || data.results || []);

        if (Array.isArray(rawItems) && rawItems.length > 0) {
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          const fetchedPlaces: PlaceItem[] = rawItems.map((p: any) => {
            const rawCat = p.category || 'Sight';
            const canonical = getCanonicalCategory(rawCat, p.name || '');
            return {
              id: p.id || `poi-${p.latitude}-${p.longitude}`,
              name: p.name || 'Unnamed Spot',
              category: rawCat,
              canonicalCategory: canonical,
              latitude: p.latitude,
              longitude: p.longitude,
              distanceMeters: p.distance_meters || p.distanceMeters || Math.round(calculateDistance(centerLat, centerLng, p.latitude, p.longitude)),
              // Only real values from the place search; nothing invented.
              address: p.address || '',
              rating: typeof p.rating === 'number' ? p.rating : undefined,
              price_approx: p.price_approx || undefined,
              description: p.description || undefined,
              isMock: Boolean(p.is_mock || p._isMock),
            };
          });
          setAllPlaces(fetchedPlaces);
          return;
        }
      }
    } catch (err) {
      console.warn('[MAP] Failed to fetch nearby POIs:', err);
    } finally {
      setIsLoadingPlaces(false);
    }

    setAllPlaces([]);
  }, []);

  // Initial load: Only fetches when coordinates anchor changes
  useEffect(() => {
    if (!activeCoords) return;
    const [lat, lng] = activeCoords;
    fetchMapPlaces(lat, lng);
  }, [activeCoords, fetchMapPlaces]);

  // ── GOOGLE MAP: create (again on a theme switch, keeping the view) and clean up ──
  useEffect(() => {
    const container = mapContainerRef.current;
    if (!container) return;
    let cancelled = false;
    const listeners: google.maps.MapsEventListener[] = [];
    const records = recordsRef.current;

    const unsubscribeAuth = onMapsAuthFailure(() => {
      console.warn('[MAP] map unavailable: key refused or paused');
      setMapStatus('unavailable');
    });

    (async () => {
      try {
        const [mapsLib, markerLib, coreLib] = await Promise.all([
          loadGoogleLibrary('maps'), loadGoogleLibrary('marker'), loadGoogleLibrary('core'),
        ]);
        if (cancelled) return;

        // Back from a place's Details page: reopen exactly there (once); follow mode and the first GPS fix
        // leave it alone. A theme switch keeps the current view. Otherwise the location, or all of India.
        const kept = savedViewRef.current;
        const restore = restoreViewRef.current;
        returnView = null;
        restoreViewRef.current = null;
        if (restore) {
          hasUserPannedRef.current = true;
          hadCoordsRef.current = true;
          fittedRef.current = true;
        }
        const [lat0, lng0] = restore?.center || activeCoordsRef.current || INDIA_CENTER;
        const center = kept?.center || { lat: lat0, lng: lng0 };
        const zoom = kept?.zoom ?? restore?.zoom ?? (activeCoordsRef.current ? 15 : 5);

        const map = new mapsLib.Map(container, {
          center,
          zoom,
          tilt: kept?.tilt ?? 0,
          heading: kept?.heading ?? 0,
          mapId: MAP_ID,
          renderingType: mapsLib.RenderingType.VECTOR,
          colorScheme: theme === 'dark' ? coreLib.ColorScheme.DARK : coreLib.ColorScheme.LIGHT,
          mapTypeId: kept?.mapType || 'roadmap',
          disableDefaultUI: true,
          clickableIcons: false,
          gestureHandling: 'greedy',
          isFractionalZoomEnabled: true,
          tiltInteractionEnabled: true,
          headingInteractionEnabled: true,
          keyboardShortcuts: true,
        });
        mapRef.current = map;
        markerLibRef.current = markerLib;
        // DEV only: lets the browser checks read zoom/tilt/center. Not in production builds.
        if (import.meta.env.DEV) (window as unknown as { __vgMap?: google.maps.Map }).__vgMap = map;

        listeners.push(map.addListener('dragstart', () => {
          cancelFly();
          hasUserPannedRef.current = true;
          if (isFollowModeRef.current) setIsFollowMode(false);
        }));
        listeners.push(map.addListener('idle', () => {
          const c = map.getCenter();
          if (!c) return;
          savedViewRef.current = {
            center: { lat: c.lat(), lng: c.lng() }, zoom: map.getZoom() ?? zoom,
            tilt: map.getTilt() ?? 0, heading: map.getHeading() ?? 0,
            mapType: (map.getMapTypeId() as MapTypeKey) || 'roadmap',
          };
          setIs3D((map.getTilt() ?? 0) > 10);
        }));
        google.maps.event.addListenerOnce(map, 'tilesloaded', () => {
          if (cancelled) return;
          setIsVector(map.getRenderingType() === mapsLib.RenderingType.VECTOR);
        });
        setMapStatus('ready');
        setMapGen((g) => g + 1);
      } catch (err) {
        if (cancelled) return;
        console.warn('[MAP] map unavailable:', err instanceof MapUnavailableError ? err.code : 'error');
        setMapStatus('unavailable');
      }
    })();

    return () => {
      cancelled = true;
      unsubscribeAuth();
      listeners.forEach((l) => l.remove());
      cancelFly();
      clustererRef.current?.clearMarkers();
      clustererRef.current?.setMap(null);
      clustererRef.current = null;
      records.forEach((r) => { r.marker.map = null; });
      records.clear();
      if (userMarkerRef.current) userMarkerRef.current.map = null;
      userMarkerRef.current = null;
      if (searchMarkerRef.current) searchMarkerRef.current.map = null;
      searchMarkerRef.current = null;
      routeLinesRef.current.forEach((l) => l.setMap(null));
      routeLinesRef.current = [];
      if (mapRef.current) google.maps.event.clearInstanceListeners(mapRef.current);
      mapRef.current = null;
      container.replaceChildren();
    };
    // Re-created only when the theme changes; everything else updates the existing map in place.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [theme]);

  // Latest coordinates for the (theme-keyed) init effect without re-running it.
  const activeCoordsRef = useRef(activeCoords);
  useEffect(() => { activeCoordsRef.current = activeCoords; }, [activeCoords]);

  // Map type switch
  useEffect(() => {
    mapRef.current?.setMapTypeId(mapType);
  }, [mapType, mapGen]);

  // Pulsing user-location dot (one marker, moved in place)
  useEffect(() => {
    const map = mapRef.current;
    const lib = markerLibRef.current;
    if (!map || !lib || !activeCoords) return;

    const [lat, lng] = userLocation || activeCoords;
    if (!userMarkerRef.current) {
      userMarkerRef.current = new lib.AdvancedMarkerElement({
        map, position: { lat, lng }, content: createUserDot(), zIndex: 3000, title: 'Your location',
      });
    } else {
      userMarkerRef.current.position = { lat, lng };
      if (!userMarkerRef.current.map) userMarkerRef.current.map = map;
    }

    if (isFollowMode && !hasUserPannedRef.current) {
      isProgrammaticMoveRef.current = true;
      map.panTo({ lat, lng });
      setTimeout(() => { isProgrammaticMoveRef.current = false; }, 850);
    }
  }, [userLocation, activeCoords, isFollowMode, mapGen]);

  // The map may start before GPS answers: move to the location the first time it arrives.
  useEffect(() => {
    if (!mapRef.current || !activeCoords || hadCoordsRef.current) return;
    hadCoordsRef.current = true;
    if (searchResult) return; // don't pull the map away from a place the user searched for
    flyTo(activeCoords[0], activeCoords[1], 15);
  }, [activeCoords, searchResult, flyTo, mapGen]);

  // Suggestions while typing (debounced, 3+ characters): autocomplete only, no coordinates and no Place Details.
  // A picked suggestion is resolved with one Details call; Enter does one named lookup (Text Search).
  useEffect(() => {
    const q = searchQuery.trim();
    if (searchResult && q === searchResult.name) return; // the box shows the chosen place
    if (q.length < SUGGEST_MIN_CHARS) {
      setSearchSuggestions([]);
      setSearchMessage(null);
      setIsSearching(false);
      return;
    }
    const seq = ++searchSeqRef.current;
    const timer = setTimeout(async () => {
      setIsSearching(true);
      try {
        const data = await suggestPlaces(q);
        if (seq !== searchSeqRef.current) return;
        const list = Array.isArray(data) ? data : [];
        setSearchSuggestions(list);
        setSearchMessage(list.length === 0 ? 'No places found in India.' : null);
      } catch (err) {
        if (seq !== searchSeqRef.current) return;
        setSearchSuggestions([]);
        setSearchMessage(mapSearchErrorMessage(err, "Search isn't available right now. Please try again."));
      } finally {
        if (seq === searchSeqRef.current) setIsSearching(false);
      }
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [searchQuery, searchResult]);

  /** A chosen search result (or voice "X dikhao"): pin + fly there. Works without a map too (card + distance). */
  const selectSearchResult = useCallback((place: DestinationReference) => {
    if (place.latitude == null || place.longitude == null) return;
    searchSeqRef.current++; // ignore any search still in flight
    setSearchResult(place);
    setSearchQuery(place.name);
    setSearchSuggestions([]);
    setSearchMessage(null);
    setIsSearching(false);
    setSelectedPlace(null);
    setSheetPlace(null);
    setIsFollowMode(false);

    const map = mapRef.current;
    const lib = markerLibRef.current;
    if (!map || !lib) return;
    const position = { lat: place.latitude, lng: place.longitude };
    if (searchMarkerRef.current) {
      searchMarkerRef.current.position = position;
      searchMarkerRef.current.title = place.name;
      if (!searchMarkerRef.current.map) searchMarkerRef.current.map = map;
    } else {
      searchMarkerRef.current = new lib.AdvancedMarkerElement({
        map, position, content: createSearchPin(place.name), zIndex: 2500, title: place.name,
      });
    }
    flyTo(place.latitude, place.longitude, 15);
  }, [setIsFollowMode, flyTo]);

  const clearSearch = useCallback(() => {
    searchSeqRef.current++;
    setSearchQuery('');
    setSearchSuggestions([]);
    setSearchMessage(null);
    setIsSearching(false);
    setSearchResult(null);
    if (searchMarkerRef.current) searchMarkerRef.current.map = null;

    if (!mapRef.current) return;
    const home = userLocation || activeCoords;
    hasUserPannedRef.current = false;
    if (home) {
      setIsFollowMode(true);
      flyTo(home[0], home[1], 15);
    } else {
      flyTo(INDIA_CENTER[0], INDIA_CENTER[1], 5);
    }
  }, [userLocation, activeCoords, setIsFollowMode, flyTo]);

  /** A picked suggestion: one Place Details call for that place, then pin + fly there. */
  const pickSuggestion = useCallback(async (s: PlaceSuggestion) => {
    const seq = ++searchSeqRef.current;
    setIsSearching(true);
    try {
      const place = await resolvePlace(s.placeId);
      if (seq !== searchSeqRef.current) return;
      if (place && isInIndia(place)) selectSearchResult({ ...place, name: place.name || s.name });
      else setSearchMessage('No places found in India.');
    } catch (err) {
      if (seq !== searchSeqRef.current) return;
      setSearchMessage(mapSearchErrorMessage(err, "Search isn't available right now. Please try again."));
    } finally {
      if (seq === searchSeqRef.current) setIsSearching(false);
    }
  }, [selectSearchResult]);

  /** Enter: one named lookup (Text Search, landmark-first) and the top result. */
  const submitSearch = useCallback(async (raw: string) => {
    const seq = ++searchSeqRef.current;
    setIsSearching(true);
    try {
      const data = await lookupPlace(raw);
      if (seq !== searchSeqRef.current) return;
      const top = (Array.isArray(data) ? data : []).find(isInIndia);
      if (top) selectSearchResult(top);
      else { setSearchSuggestions([]); setSearchMessage('No places found in India.'); }
    } catch (err) {
      if (seq !== searchSeqRef.current) return;
      setSearchMessage(mapSearchErrorMessage(err, "Search isn't available right now. Please try again."));
    } finally {
      if (seq === searchSeqRef.current) setIsSearching(false);
    }
  }, [selectSearchResult]);

  const searchDistanceMeters = searchResult && userLocation && searchResult.latitude != null && searchResult.longitude != null
    ? calculateDistance(userLocation[0], userLocation[1], searchResult.latitude, searchResult.longitude)
    : null;

  // Count of places in each category
  const categoryCounts = useMemo(() => {
    const counts: Record<string, number> = { all: basePlaces.length };
    for (const p of basePlaces) {
      const cat = p.canonicalCategory || getCanonicalCategory(p.category, p.name);
      counts[cat] = (counts[cat] || 0) + 1;
    }
    return counts;
  }, [basePlaces]);

  // Instant client-side filter — NO network requests when category tab is selected
  const filteredPlaces = useMemo(() => {
    if (activeCategory === 'all') return basePlaces;
    return basePlaces.filter(p => (p.canonicalCategory || getCanonicalCategory(p.category, p.name)) === activeCategory);
  }, [basePlaces, activeCategory]);

  // Nearest-first order for the scrollable card row
  const sortedPlaces = useMemo(() => {
    return [...filteredPlaces].sort((a, b) => (a.distanceMeters ?? Infinity) - (b.distanceMeters ?? Infinity));
  }, [filteredPlaces]);

  // Selects a place from a card tap, and flies the map to it
  const focusPlace = useCallback((place: PlaceItem) => {
    setSelectedPlace(place);
    setIsFollowMode(false);
    flyTo(place.latitude, place.longitude, 17);
  }, [setIsFollowMode, flyTo]);

  // A pin tap also opens the slide-up sheet for that place.
  useEffect(() => {
    onPinTapRef.current = (place: PlaceItem) => {
      focusPlace(place);
      setSheetPlace(place);
    };
  }, [focusPlace]);

  // When a place is selected, scroll its card into view
  useEffect(() => {
    if (!selectedPlace) return;
    cardRefs.current.get(selectedPlace.id)?.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' });
  }, [selectedPlace]);

  // ── Place markers: created once per place, kept across filter changes, clustered when crowded ──
  useEffect(() => {
    const map = mapRef.current;
    const lib = markerLibRef.current;
    if (!map || !lib) return;
    const records = recordsRef.current;
    const nextIds = new Set(filteredPlaces.map((p) => p.id));

    if (!clustererRef.current) {
      clustererRef.current = new MarkerClusterer({
        map,
        markers: [],
        algorithm: new SuperClusterAlgorithm({ radius: CLUSTER_OPTIONS.radius, maxZoom: CLUSTER_OPTIONS.maxZoom }),
        renderer: {
          render: ({ count, position }) => new lib.AdvancedMarkerElement({
            position, content: createClusterBubble(count), zIndex: 1000 + count, title: `${count} places`,
          }),
        },
        onClusterClick: (_e, cluster, m) => {
          if (cluster.bounds) m.fitBounds(cluster.bounds, 80);
        },
      });
    }
    const clusterer = clustererRef.current;

    records.forEach((r, id) => {
      if (!nextIds.has(id)) { r.marker.map = null; records.delete(id); }
    });
    let created = 0;
    filteredPlaces.forEach((place) => {
      const existing = records.get(place.id);
      if (existing) { existing.place = place; return; }
      const el = createPlacePin(pinStyle(place.category, place.name), place.name, created++ * 30);
      const marker = new lib.AdvancedMarkerElement({
        position: { lat: place.latitude, lng: place.longitude }, content: el, title: place.name, gmpClickable: true,
      });
      const record: MarkerRecord = { marker, el, place };
      marker.addEventListener('gmp-click', () => onPinTapRef.current(record.place));
      records.set(place.id, record);
    });

    const markers = filteredPlaces.map((p) => records.get(p.id)!.marker);
    clusterer.clearMarkers(true);
    if (shouldCluster(markers.length)) {
      clusterer.addMarkers(markers);
    } else {
      clusterer.render();
      markers.forEach((m) => { m.map = map; });
    }
  }, [filteredPlaces, mapGen]);

  // Selected pin: larger and glowing (a class toggle; markers are not rebuilt)
  useEffect(() => {
    recordsRef.current.forEach((r, id) => {
      const sel = selectedPlace?.id === id;
      setPinSelected(r.el, sel);
      r.marker.zIndex = sel ? 2000 : null;
    });
  }, [selectedPlace, filteredPlaces, mapGen]);

  // First load: fit every place (and the user) on screen once, unless the view was restored or a place is focused.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || fittedRef.current || filteredPlaces.length === 0 || searchResult || mapFocusTarget) return;
    fittedRef.current = true;
    const bounds = new google.maps.LatLngBounds();
    filteredPlaces.forEach((p) => bounds.extend({ lat: p.latitude, lng: p.longitude }));
    if (userLocation) bounds.extend({ lat: userLocation[0], lng: userLocation[1] });
    map.fitBounds(bounds, fitPadding(mapContainerRef.current, 40));
  }, [filteredPlaces, mapGen, searchResult, mapFocusTarget, userLocation]);

  // ── BRIDGE LOGIC: Deep Link Target from Explore Mode / voice ──
  useEffect(() => {
    if (!mapFocusTarget || mapStatus === 'loading') return;
    const { coordinates, id, name, category, zoom, address } = mapFocusTarget;

    // Voice "X ke paas restaurant": show the places as the map's markers and cards, fit them on screen.
    if (mapFocusTarget.results) {
      const here = userLocation || activeCoords;
      const items: PlaceItem[] = mapFocusTarget.results.places.map((p) => {
        const cat = p.category || 'sights';
        return {
          id: p.placeId || `voice-${p.lat}-${p.lng}`,
          name: p.name,
          category: cat,
          canonicalCategory: getCanonicalCategory(cat, p.name),
          latitude: p.lat,
          longitude: p.lng,
          address: p.address || '',
          rating: p.rating,
          ...(here ? { distanceMeters: Math.round(calculateDistance(here[0], here[1], p.lat, p.lng)) } : {}),
        };
      });
      searchSeqRef.current++;
      setSearchResult(null);
      setSearchQuery('');
      setSearchSuggestions([]);
      if (searchMarkerRef.current) searchMarkerRef.current.map = null;
      setActiveCategory('all');
      setSelectedPlace(null);
      setSheetPlace(null);
      setIsFollowMode(false);
      setVoiceResults({ title: mapFocusTarget.results.title, places: items });
      fittedRef.current = true;   // the first-load fit must not zoom out to include the user
      const map = mapRef.current;
      if (map && items.length) {
        cancelFly();
        const bounds = new google.maps.LatLngBounds();
        items.forEach((p) => bounds.extend({ lat: p.latitude, lng: p.longitude }));
        if (items.length === 1) flyTo(items[0].latitude, items[0].longitude, 16);
        else map.fitBounds(bounds, fitPadding(mapContainerRef.current, 40));
      }
      setMapFocusTarget(null);
      return;
    }

    // Voice "Hawa Mahal dikhao": same as choosing a search result (pin + distance from the user).
    if (mapFocusTarget.pin) {
      selectSearchResult({
        id: id || `voice-${coordinates[0]}-${coordinates[1]}`,
        name: name || 'Place',
        country: 'India',
        latitude: coordinates[0],
        longitude: coordinates[1],
        ...(address ? { displayName: address } : {}),
      } as DestinationReference);
      setMapFocusTarget(null);
      return;
    }

    flyTo(coordinates[0], coordinates[1], zoom || 17);

    const targetPlace: PlaceItem = {
      id: id || `focus-${Date.now()}`,
      name: name || 'Target Place',
      category: (category || 'sights').toLowerCase(),
      latitude: coordinates[0],
      longitude: coordinates[1],
      address: address || '',
      distanceMeters: calculateDistance(
        (userLocation ? userLocation[0] : (activeCoords ? activeCoords[0] : coordinates[0])),
        (userLocation ? userLocation[1] : (activeCoords ? activeCoords[1] : coordinates[1])),
        coordinates[0],
        coordinates[1]
      ),
    };

    setSelectedPlace(targetPlace);
    setSheetPlace(targetPlace);
    setIsFollowMode(false);

    // Clear bridge state after focusing
    const timer = setTimeout(() => {
      setMapFocusTarget(null);
    }, 2500);

    return () => clearTimeout(timer);
  }, [mapFocusTarget, mapStatus, userLocation, activeCoords, setMapFocusTarget, setIsFollowMode, selectSearchResult, flyTo, cancelFly]);

  // Recenter handler
  const handleRecenter = () => {
    const targetCoords = userLocation || activeCoords;
    if (mapRef.current && targetCoords) {
      hasUserPannedRef.current = false;
      setIsFollowMode(true);
      flyTo(targetCoords[0], targetCoords[1], 16);
    }
  };

  const clearRouteLine = useCallback(() => {
    routeLinesRef.current.forEach((l) => l.setMap(null));
    routeLinesRef.current = [];
  }, []);

  /** Draw the route (decoded with the Maps geometry library) and fit the camera to it. */
  const drawRoute = useCallback(async (encoded: string) => {
    const map = mapRef.current;
    if (!map) return;
    try {
      const geometry = await loadGoogleLibrary('geometry');
      const path = geometry.encoding.decodePath(encoded);
      clearRouteLine();
      routeLinesRef.current = [
        new google.maps.Polyline({ map, path, strokeColor: '#FFFFFF', strokeOpacity: 0.95, strokeWeight: 9, zIndex: 1 }),
        new google.maps.Polyline({ map, path, strokeColor: '#1A73E8', strokeOpacity: 1, strokeWeight: 5, zIndex: 2 }),
      ];
      const bounds = new google.maps.LatLngBounds();
      path.forEach((pt) => bounds.extend(pt));
      cancelFly();
      map.fitBounds(bounds, fitPadding(mapContainerRef.current, 55));
    } catch {
      clearRouteLine(); // no line; the sheet still shows the time
    }
  }, [clearRouteLine, cancelFly]);

  const requestRoute = useCallback(async (place: PlaceItem, mode: RouteMode) => {
    const seq = ++routeSeqRef.current;
    setRouteMode(mode);
    // Only a usable device location (accuracy 1 km or better), 150 m - 300 km away, gets a Google call.
    if (travelPlan(deviceLocation.getState(), place).kind !== 'route') {
      clearRouteLine();
      setRoute({ placeId: place.id, status: 'needs_location' });
      return;
    }
    setRoute({ placeId: place.id, status: 'loading' });
    try {
      const result = await deviceLocation.route({ lat: place.latitude, lng: place.longitude }, mode, 'map');
      if (seq !== routeSeqRef.current) return;
      setRoute({ placeId: place.id, status: 'ok', result });
      setIsFollowMode(false);
      if (result.polyline) await drawRoute(result.polyline);
      else clearRouteLine();
    } catch (err) {
      if (seq !== routeSeqRef.current) return;
      clearRouteLine();
      setRoute({
        placeId: place.id, status: 'error',
        message: err instanceof RouteError && err.status === 503 ? err.message : 'The route is currently unavailable.',
      });
    }
  }, [clearRouteLine, drawRoute, setIsFollowMode]);

  // A different place in the sheet (or none): forget the old route and its line.
  const sheetPlaceId = sheetPlace?.id;
  useEffect(() => {
    routeSeqRef.current++;
    setRoute(null);
    clearRouteLine();
  }, [sheetPlaceId, clearRouteLine, mapGen]);

  const renderRouteSection = (place: PlaceItem) => {
    if (!canRoute(place)) return null;
    const mine = route && route.placeId === place.id ? route : null;
    const plan = travelPlan(devLoc, place);
    const straight = 'straightM' in plan ? plan.straightM : null;
    const usableOrigin = plan.kind === 'route' || plan.kind === 'here' || plan.kind === 'far';
    const fromLine = (
      <div className="flex items-center justify-between gap-2 text-[11px] font-semibold text-[color:var(--color-text-secondary)]">
        <button type="button" disabled={!devLoc.reading} onClick={() => setOriginSheetFor(place)}
          className="flex items-center gap-1.5 min-h-[32px] text-left min-w-0 disabled:cursor-default">
          <Navigation className="w-3.5 h-3.5 shrink-0 text-[#1A73E8]" aria-hidden="true" />
          <span className="truncate">{usableOrigin && devLoc.reading ? originLabel(devLoc.reading.accuracy_m)
            : plan.kind === 'poor' ? noLocationReason('poor')
            : plan.kind === 'no-location' ? noLocationReason(plan.reason) : ''}</span>
        </button>
        {!usableOrigin && (
          <button type="button" onClick={devLoc.retry} disabled={devLoc.status === 'loading'}
            className="shrink-0 min-h-[32px] px-3 rounded-full border border-gray-200 dark:border-zinc-700 text-[#1A73E8] font-bold disabled:opacity-60">
            Use my location again
          </button>
        )}
      </div>
    );
    // No Google call: near, far, or no usable location
    if (plan.kind !== 'route') {
      const msg = plan.kind === 'here' ? 'You’re here'
        : plan.kind === 'far' ? `You’re far from this place (${farKm(plan.straightM)})`
        : plan.kind === 'poor' ? `${formatStraightLine(plan.straightM)} (straight-line)`
        : 'Location needed';
      return (
        <div className="space-y-1 pt-1 border-t border-gray-100 dark:border-zinc-800">
          {fromLine}
          <p className="text-sm font-bold tabular-nums text-[color:var(--color-text-primary)]" role="status">{msg}</p>
        </div>
      );
    }
    if (!mine) {
      return (
        <div className="space-y-1">
        {fromLine}
        <button
          type="button"
          onClick={() => requestRoute(place, routeMode)}
          className="w-full min-h-[44px] rounded-xl bg-[#1A73E8] hover:bg-[#1765CC] text-white font-semibold text-sm flex items-center justify-center gap-2 press-scale"
        >
          <Navigation className="w-4 h-4" aria-hidden="true" /> Route
        </button>
        </div>
      );
    }
    return (
      <div className="space-y-2 pt-1 border-t border-gray-100 dark:border-zinc-800">
        {fromLine}
        <div role="radiogroup" aria-label="Travel mode" className="flex gap-2 pt-2">
          {ROUTE_MODES.map((m) => (
            <button
              key={m.key}
              type="button"
              role="radio"
              aria-checked={routeMode === m.key}
              disabled={mine.status === 'loading'}
              onClick={() => { if (m.key !== routeMode || mine.status !== 'ok') requestRoute(place, m.key); }}
              className={`flex-1 min-h-[36px] rounded-full text-xs font-semibold border transition-colors ${routeMode === m.key
                ? 'bg-[#1A73E8] text-white border-[#1A73E8]'
                : 'bg-white dark:bg-zinc-800 text-gray-700 dark:text-zinc-200 border-gray-200 dark:border-zinc-700'}`}
            >
              {m.label}
            </button>
          ))}
        </div>
        <div className="text-sm" role="status" aria-live="polite">
          {mine.status === 'loading' && (
            <span className="flex items-center gap-2 text-[color:var(--color-text-secondary)]">
              <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" aria-hidden="true" /> Finding the route…
            </span>
          )}
          {mine.status === 'ok' && mine.result && (
            <>
              <p className="font-bold tabular-nums text-[color:var(--color-text-primary)]">
                {formatRouteSummary(mine.result.distance_m, mine.result.duration_s, mine.result.mode)}
              </p>
              {mine.result.mode !== 'drive' && mine.result.warning && (
                <p className="mt-1 text-[11px] text-amber-700 dark:text-amber-300">{mine.result.warning}</p>
              )}
            </>
          )}
          {mine.status === 'error' && (
            <p className="text-[color:var(--color-text-secondary)]">
              {straight != null && <span className="font-bold tabular-nums text-[color:var(--color-text-primary)]">{formatStraightLine(straight)} (straight-line) · </span>}
              {mine.message}
            </p>
          )}
          {mine.status === 'needs_location' && (
            <p className="text-[color:var(--color-text-secondary)]">Turn on location to see directions.</p>
          )}
        </div>
      </div>
    );
  };

  /** 3D: tilt the vector map (3D buildings show from about zoom 17) or flatten it again. */
  const toggle3D = () => {
    const map = mapRef.current;
    if (!map || !isVector) return;
    cancelFly();
    const fromTilt = map.getTilt() ?? 0;
    const toTilt = fromTilt > 10 ? 0 : 60;
    const fromZoom = map.getZoom() ?? 15;
    const toZoom = toTilt ? Math.max(fromZoom, 17) : fromZoom;
    if (prefersReducedMotion()) { map.moveCamera({ tilt: toTilt, zoom: toZoom }); return; }
    const start = performance.now();
    const step = (now: number) => {
      const t = Math.min(1, (now - start) / 700);
      const e = easeInOutCubic(t);
      map.moveCamera({ tilt: fromTilt + (toTilt - fromTilt) * e, zoom: fromZoom + (toZoom - fromZoom) * e });
      if (t < 1) flyRafRef.current = requestAnimationFrame(step);
      else flyRafRef.current = null;
    };
    flyRafRef.current = requestAnimationFrame(step);
  };

  const renderCardBody = (place: PlaceItem, onClose?: () => void) => (
    <>
      {/* No Google map on screen (key missing/paused): the card itself carries the attribution. */}
      {mapStatus === 'unavailable' && <div className="flex justify-end -mt-1"><GoogleMapsAttribution /></div>}
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 space-y-0.5">
                    <div className="flex items-center gap-2">
                      <span className="px-2 py-0.5 rounded-md bg-[#1F5A3F]/10 dark:bg-emerald-950/60 text-[#1F5A3F] dark:text-emerald-400 border border-[#1F5A3F]/20 dark:border-emerald-800/40 text-[10px] font-semibold uppercase">
                        {sentenceCase(place.category)}
                      </span>
                      <span className="text-[11px] font-medium tabular-nums whitespace-nowrap text-[color:var(--color-text-secondary)]">
                        {formatDistance(place.distanceMeters)}
                      </span>
                    </div>
                    <h3 className="text-base font-semibold text-gray-900 dark:text-zinc-100 truncate">
                      {place.name}
                    </h3>
                    <p className="text-xs text-gray-500 dark:text-zinc-400 truncate">
                      {place.address}
                    </p>
                  </div>

                  <div className="flex shrink-0 items-center gap-2">
                  {/* Audio Narration TTS Control */}
                  <button
                    type="button"
                    onClick={(e) => handlePlayNarration(place, e)}
                    disabled={audioLoadingId === place.id}
                    aria-label={playingPlaceId === place.id ? 'Stop audio guide' : 'Play audio guide'}
                    className={`w-10 h-10 shrink-0 rounded-full border transition-colors press-scale flex items-center justify-center ${playingPlaceId === place.id
                        ? 'bg-amber-500 text-white border-amber-500'
                        : 'bg-gray-50 dark:bg-zinc-800 text-gray-500 dark:text-zinc-400 border-gray-200 dark:border-zinc-700 hover:border-[#1F5A3F]/40 dark:hover:border-zinc-600'
                      }`}
                  >
                    {audioLoadingId === place.id ? (
                      <Loader2 className="w-5 h-5 animate-spin motion-reduce:animate-none" aria-hidden="true" />
                    ) : playingPlaceId === place.id ? (
                      <VolumeX className="w-5 h-5" aria-hidden="true" />
                    ) : (
                      <Volume2 className="w-5 h-5 text-[#1F5A3F] dark:text-emerald-400" aria-hidden="true" />
                    )}
                  </button>
                  {onClose && (
                    <button
                      type="button"
                      onClick={onClose}
                      aria-label="Close"
                      className="w-10 h-10 shrink-0 rounded-full bg-white dark:bg-zinc-800 border border-gray-200 dark:border-zinc-700 flex items-center justify-center text-gray-600 dark:text-zinc-300 press-scale"
                    >
                      <X className="w-4 h-4" aria-hidden="true" />
                    </button>
                  )}
                  </div>
                </div>

                <PlaceCardActions
                  placeName={place.name}
                  add={addToTrip(place, addedPlaceDays.get(place.id))}
                  saved={savedToggle.isSaved(place.id)}
                  onAdd={() => itineraryAdd.open(place)}
                  onToggleSave={() => {
                    savedToggle.toggle({
                      place_id: place.id,
                      title: place.name,
                      category: place.category,
                      location_name: place.address,
                      location: place.address,
                      coordinates: [place.latitude, place.longitude],
                      rating: place.rating,
                      cost_text: place.price_approx,
                      description: place.description,
                    });
                  }}
                  onDetails={() => {
                    saveReturnView();
                    navigate(`/details/${encodeURIComponent(place.id)}`, {
                      state: {
                        place: {
                          id: place.id,
                          name: place.name,
                          category: place.category,
                          distanceText: place.distanceMeters != null ? formatDistance(place.distanceMeters) : undefined,
                          address: place.address,
                          latitude: place.latitude,
                          longitude: place.longitude,
                          description: place.description,
                          price_approx: place.price_approx,
                        },
                      },
                    });
                  }}
                />
    </>
  );

  // The card / sheet height drives where the map element ends (mapView.css), so Google's attribution strip always
  // sits fully visible just above it.
  const rootRef = useRef<HTMLDivElement>(null);
  const observedRef = useRef<Element | null>(null);
  const cardObserverRef = useRef<ResizeObserver | null>(null);
  const syncCardSpace = useCallback(() => {
    const root = rootRef.current;
    if (!root) return;
    const overlay = root.querySelector<HTMLElement>('.map-places-overlay');
    root.style.setProperty('--map-card-h', `${overlay?.offsetHeight ?? 0}px`);
    const canvas = mapContainerRef.current;
    const tools_ = root.querySelector<HTMLElement>('.map-app-tools');
    const controls = root.querySelector<HTMLElement>('.map-type-controls');
    // Two stacked 40 px type buttons + gaps must end above the floating mic.
    const free = tools_ && controls ? tools_.offsetTop - controls.offsetTop : Infinity;
    root.toggleAttribute('data-map-compact', free < 100);
    // The voice note is fixed to the screen: keep it above the floating mic, off the attribution.
    if (tools_ && canvas) {
      const bottom = window.innerHeight - tools_.getBoundingClientRect().top + 8;
      document.documentElement.style.setProperty('--mic-note-bottom', `${Math.round(bottom)}px`);
    }
  }, []);
  // Every render: the overlay may be a different element (cards, sheet, loading, empty).
  useLayoutEffect(() => {
    const overlay = rootRef.current?.querySelector('.map-places-overlay') ?? null;
    if (overlay !== observedRef.current) {
      cardObserverRef.current?.disconnect();
      observedRef.current = overlay;
      if (rootRef.current && typeof ResizeObserver !== 'undefined') {
        const observer = new ResizeObserver(syncCardSpace);
        observer.observe(rootRef.current);
        if (overlay) observer.observe(overlay);
        cardObserverRef.current = observer;
      }
    }
    syncCardSpace();
  });
  useEffect(() => () => {
    cardObserverRef.current?.disconnect();
    observedRef.current = null;
    document.documentElement.style.removeProperty('--mic-note-bottom');
  }, []);

  return (
    <div
      ref={rootRef}
      className="map-view relative isolate w-full min-h-0 flex-1 overflow-hidden bg-[#EFF1ED] dark:bg-zinc-950 select-none transition-colors"
      data-map-search-result={Boolean(searchResult) || undefined}
    >
      {/* Map (Google Maps JavaScript API) */}
      <div ref={mapContainerRef} className="map-canvas z-0" aria-label="Map" role="region" />

      {tools && <div className="map-app-tools">{tools}</div>}

      {mapStatus === 'unavailable' && (
        <div className="absolute inset-0 z-[1] flex items-center justify-center p-6 pointer-events-none">
          <div className="max-w-xs text-center rounded-2xl bg-[var(--color-surface)] border border-[var(--color-border)] shadow-sm p-5 space-y-2" role="status">
            <MapPinOff className="w-6 h-6 mx-auto text-[color:var(--color-text-secondary)]" aria-hidden="true" />
            <p className="text-sm font-semibold text-[color:var(--color-text-primary)]">Map isn&apos;t available right now</p>
            <p className="text-xs text-[color:var(--color-text-secondary)]">Search and the places list still work.</p>
          </div>
        </div>
      )}

      {/* Top controls: back + search + recenter */}
      <div className="map-overlay-controls absolute top-3 inset-x-3 z-[510] flex items-center justify-between pointer-events-none">
        <button
          type="button"
          aria-label="Back to Explore"
          onClick={() => navigateToExplore()}
          className="pointer-events-auto min-h-[40px] px-3.5 rounded-full bg-white dark:bg-zinc-900 hover:bg-gray-50 dark:hover:bg-zinc-800 text-[#1F2522] dark:text-zinc-100 border border-gray-200 dark:border-zinc-800 shadow-sm font-semibold text-xs flex items-center gap-1.5 press-scale transition-colors"
        >
          <ArrowLeft className="w-4 h-4 text-[#1F5A3F] dark:text-emerald-400" aria-hidden="true" />
          <span className="hidden sm:inline">Explore</span>
        </button>

        <div className="pointer-events-auto relative flex-1 min-w-0 mx-2">
          <div className="min-h-[40px] flex items-center gap-2 px-3 rounded-full bg-[var(--color-surface)] border border-[var(--color-text-tertiary)] shadow-sm outline-[var(--color-primary)] dark:outline-[var(--color-primary-light)] has-[input:focus-visible]:outline-2 has-[input:focus-visible]:-outline-offset-3">
            {isSearching
              ? <Loader2 className="w-4 h-4 shrink-0 animate-spin motion-reduce:animate-none text-[color:var(--color-primary)] dark:text-[color:var(--color-primary-light)]" aria-hidden="true" />
              : <Search className="w-4 h-4 shrink-0 text-[color:var(--color-text-secondary)]" aria-hidden="true" />}
            <span className="sr-only" role="status">{isSearching ? 'Searching for places…' : ''}</span>
            <input
              type="search"
              value={searchQuery}
              onChange={(e) => {
                setSearchQuery(e.target.value);
                if (searchResult) setSearchResult(null);
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && searchQuery.trim().length >= 2) void submitSearch(searchQuery);
                if (e.key === 'Escape') clearSearch();
              }}
              placeholder="Search a place in India"
              aria-label="Search a place on the map"
              className="flex-1 min-w-0 bg-transparent text-sm text-[color:var(--color-text-primary)] placeholder:text-[color:var(--color-text-secondary)] placeholder:opacity-100 caret-[var(--color-primary)] dark:caret-[var(--color-primary-light)] outline-none [&::-webkit-search-cancel-button]:hidden"
            />
            {(searchQuery || searchResult) && (
              <button
                type="button"
                onClick={clearSearch}
                aria-label="Clear search"
                className="w-7 h-7 shrink-0 rounded-full flex items-center justify-center text-[color:var(--color-text-secondary)] hover:bg-[var(--color-surface-elevated)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-primary)] dark:focus-visible:outline-[var(--color-primary-light)]"
              >
                <X className="w-4 h-4" aria-hidden="true" />
              </button>
            )}
          </div>

          {(searchSuggestions.length > 0 || searchMessage) && !searchResult && (
            <div className="absolute top-full left-0 right-0 mt-1.5 rounded-2xl bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 shadow-lg overflow-hidden" role="listbox" aria-label="Search suggestions">
              {searchSuggestions.map((s) => (
                <button
                  key={s.placeId}
                  type="button"
                  role="option"
                  aria-selected={false}
                  onClick={() => void pickSuggestion(s)}
                  className="w-full text-left px-3.5 py-2.5 flex items-start gap-2.5 hover:bg-gray-50 dark:hover:bg-zinc-800 border-b last:border-b-0 border-gray-100 dark:border-zinc-800 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--color-primary)] dark:focus-visible:outline-[var(--color-primary-light)]"
                >
                  <MapPin className="w-4 h-4 mt-0.5 shrink-0 text-[#1F5A3F] dark:text-emerald-400" aria-hidden="true" />
                  <span className="min-w-0">
                    <span className="block text-sm font-semibold text-[#1F2522] dark:text-zinc-100 truncate">{s.name}</span>
                    <span className="block text-[11px] text-[color:var(--color-text-secondary)] truncate">{s.secondary}</span>
                  </span>
                </button>
              ))}
              {searchSuggestions.length > 0 && (
                <div role="presentation" className="sticky bottom-0 px-3.5 py-1.5 flex justify-end border-t border-gray-100 dark:border-zinc-800 bg-white dark:bg-zinc-900"><GoogleMapsAttribution /></div>
              )}
              {searchMessage && (
                <div className="px-3.5 py-3 text-xs text-[color:var(--color-text-secondary)]">{searchMessage}</div>
              )}
            </div>
          )}
        </div>
        <button
          type="button"
          onClick={handleRecenter}
          aria-label="Recenter on my location"
          title="Recenter on my location"
          className={`pointer-events-auto w-10 h-10 shrink-0 rounded-full border shadow-sm transition-colors press-scale flex items-center justify-center ${isFollowMode
              ? 'bg-[#1F5A3F] dark:bg-emerald-600 text-white border-[#1F5A3F] dark:border-emerald-600'
              : 'bg-white dark:bg-zinc-900 text-gray-600 dark:text-zinc-300 border-gray-200 dark:border-zinc-800 hover:border-[#1F5A3F]/40'
            }`}
        >
          <Crosshair className="w-4 h-4" aria-hidden="true" />
        </button>
      </div>

      {/* Glass controls: map type switch + 3D (vector maps only) */}
      {mapStatus === 'ready' && (
        <div className="map-type-controls absolute right-3 z-[505] flex flex-col items-end gap-2 pointer-events-auto">
          <div className="relative">
            <button
              type="button"
              onClick={() => setShowTypes((v) => !v)}
              aria-expanded={showTypes}
              aria-label="Map type"
              title="Map type"
              className="map-glass w-10 h-10 rounded-full flex items-center justify-center text-[color:var(--color-text-primary)] press-scale"
            >
              <Layers className="w-4 h-4" aria-hidden="true" />
            </button>
            {showTypes && (
              <div role="radiogroup" aria-label="Map type" className="map-glass absolute right-12 top-0 rounded-2xl p-1 flex gap-1">
                {MAP_TYPES.map((t) => (
                  <button
                    key={t.key}
                    type="button"
                    role="radio"
                    aria-checked={mapType === t.key}
                    onClick={() => { setMapType(t.key); setShowTypes(false); }}
                    className={`min-h-[36px] px-3 rounded-xl text-xs font-semibold whitespace-nowrap transition-colors ${mapType === t.key
                      ? 'bg-[#1F5A3F] dark:bg-emerald-600 text-white'
                      : 'text-[color:var(--color-text-primary)] hover:bg-[var(--color-surface-elevated)]'}`}
                  >
                    {t.label}
                  </button>
                ))}
              </div>
            )}
          </div>
          {isVector && (
            <button
              type="button"
              onClick={toggle3D}
              aria-pressed={is3D}
              aria-label={is3D ? 'Flat map' : '3D view'}
              title={is3D ? 'Flat map' : '3D view'}
              className={`map-glass w-10 h-10 rounded-full flex items-center justify-center press-scale ${is3D ? 'text-[#1F5A3F] dark:text-emerald-400' : 'text-[color:var(--color-text-primary)]'}`}
            >
              <Box className="w-4 h-4" aria-hidden="true" />
            </button>
          )}
        </div>
      )}

      {searchResult && (
        <div className="map-secondary-overlay absolute top-[60px] inset-x-3 z-[500] pointer-events-auto rounded-2xl bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 shadow-md p-3.5 flex items-start gap-3 animate-fadeIn" role="status">
          <div className="w-9 h-9 rounded-xl bg-[#E8F0EE] dark:bg-emerald-950 text-[#1F5A3F] dark:text-emerald-400 flex items-center justify-center shrink-0">
            <MapPin className="w-4.5 h-4.5" aria-hidden="true" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-sm font-bold text-[#1F2522] dark:text-zinc-100 truncate">{searchResult.name}</div>
            <div className="text-[11px] text-[color:var(--color-text-secondary)] truncate">{(searchResult as any).displayName || placeSubtitle(searchResult)}</div>
            {searchDistanceMeters != null ? (
              <div className="text-xs font-bold tabular-nums text-[color:var(--color-text-secondary)] mt-1">{formatSearchDistance(searchDistanceMeters)} from you <span className="font-normal">(straight line)</span></div>
            ) : (
              <div className="text-xs text-[color:var(--color-text-secondary)] mt-1">Turn on location to see distance</div>
            )}
          </div>
        </div>
      )}
      {!activeCoords && !searchResult && (
        <div className="map-secondary-overlay absolute top-[60px] inset-x-3 z-[500] pointer-events-none flex justify-center">
          <span className="px-3 py-1.5 rounded-full bg-white/95 dark:bg-zinc-900/95 border border-gray-200 dark:border-zinc-800 text-[11px] font-medium text-gray-600 dark:text-zinc-300 shadow-sm">
            Turn on location to see places near you, or search above
          </span>
        </div>
      )}

      {/* Category filter row */}
      {!searchResult && (activeCoords || voiceResults) && (
      <div
        role="group"
        aria-label="Filter places by category"
        className="map-secondary-overlay absolute top-[60px] inset-x-3 z-[500] flex items-center gap-2 overflow-x-auto no-scrollbar pointer-events-auto py-1"
      >
        {voiceResults && (
          <button
            type="button"
            onClick={() => { setVoiceResults(null); setSelectedPlace(null); setSheetPlace(null); }}
            aria-label={`Clear: ${voiceResults.title}`}
            className="shrink-0 min-h-[32px] px-3.5 rounded-full text-xs font-semibold border shadow-sm flex items-center gap-1.5 press-scale bg-[#1A73E8] text-white border-[#1A73E8]"
          >
            <span className="max-w-[180px] truncate">{voiceResults.title}</span>
            <X className="w-3.5 h-3.5" aria-hidden="true" />
          </button>
        )}
        {CATEGORY_FILTERS.map(({ key, label }) => {
          const count = categoryCounts[key] ?? 0;
          return (
            <button
              key={key}
              type="button"
              onClick={() => {
                // Instant client-side filter — NO redundant network requests!
                setActiveCategory(key);
              }}
              aria-pressed={activeCategory === key}
              className={`shrink-0 min-h-[32px] px-3.5 rounded-full text-xs font-semibold transition-all border shadow-sm flex items-center gap-1.5 press-scale ${activeCategory === key
                  ? 'bg-[#1F5A3F] dark:bg-emerald-600 text-white border-[#1F5A3F] dark:border-emerald-600'
                  : 'bg-white dark:bg-zinc-900 text-gray-600 dark:text-zinc-300 border-gray-200 dark:border-zinc-800 hover:text-gray-900 dark:hover:text-zinc-100'
                }`}
            >
              <span>{label}</span>
              {count > 0 && (
                <span className={`text-[10px] px-1.5 py-0.2 rounded-full font-bold ${
                  activeCategory === key ? 'bg-white/20 text-white' : 'bg-gray-100 dark:bg-zinc-800 text-gray-500 dark:text-zinc-400'
                }`}>
                  {count}
                </span>
              )}
            </button>
          );
        })}
      </div>
      )}
      {/* Selected place (pin tap): slides up over the card row */}
      {sheetPlace ? (
        <div className="map-places-overlay absolute inset-x-3 z-[506] pointer-events-auto" role="dialog" aria-label={sheetPlace.name}>
          <div className="map-selected-sheet relative rounded-3xl bg-white dark:bg-zinc-900 border border-[#1F5A3F]/30 dark:border-emerald-800/50 p-4 shadow-2xl space-y-3">
            {renderCardBody(sheetPlace, () => setSheetPlace(null))}
            {renderRouteSection(sheetPlace)}
            {originSheetFor && originSheetFor.id === sheetPlace.id && devLoc.reading && (
              <RouteOriginSheet
                origin={devLoc.origin && devLoc.reading.accuracy_m <= 1000 ? devLoc.origin : devLoc.reading}
                dest={{ name: sheetPlace.name, lat: sheetPlace.latitude, lng: sheetPlace.longitude }}
                summary={route && route.placeId === sheetPlace.id && route.status === 'ok' && route.result
                  ? formatRouteSummary(route.result.distance_m, route.result.duration_s, route.result.mode) : null}
                onClose={() => setOriginSheetFor(null)}
              />
            )}
          </div>
        </div>
      ) : sortedPlaces.length > 0 ? (
        <div
          ref={cardScrollRef}
          className="map-places-overlay absolute inset-x-0 z-[500] flex gap-3 px-3 pb-1 snap-x snap-mandatory pointer-events-auto animate-slideUp"
        >
          {sortedPlaces.map((place) => {
            const isSelected = selectedPlace?.id === place.id;
            return (
              <div
                key={place.id}
                ref={(el) => {
                  if (el) cardRefs.current.set(place.id, el);
                  else cardRefs.current.delete(place.id);
                }}
                role="button"
                tabIndex={0}
                onClick={() => focusPlace(place)}
                onKeyDown={(e) => {
                  if (e.target !== e.currentTarget) return;
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    focusPlace(place);
                  }
                }}
                className={`w-[270px] sm:w-[300px] max-w-full shrink-0 snap-center rounded-3xl bg-white dark:bg-zinc-900 border p-4 shadow-lg space-y-3 cursor-pointer transition-colors ${isSelected ? 'border-[#1F5A3F] dark:border-emerald-500 ring-2 ring-[#1F5A3F]/20 dark:ring-emerald-500/20' : 'border-gray-200 dark:border-zinc-800'
                  }`}
              >
                {renderCardBody(place)}
              </div>
            );
          })}
        </div>
      ) : isLoadingPlaces ? (
        <div className="map-places-overlay absolute inset-x-3 z-[500] pointer-events-auto animate-slideUp">
          <div className="rounded-3xl bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 p-4 shadow-lg flex items-center justify-center gap-3" role="status">
            <Loader2 className="w-5 h-5 text-[color:var(--color-primary)] dark:text-[color:var(--color-primary-light)] animate-spin motion-reduce:animate-none" aria-hidden="true" />
            <p className="text-sm font-medium text-gray-700 dark:text-zinc-300">Finding nearby places...</p>
          </div>
        </div>
      ) : (
        <div className="map-places-overlay absolute inset-x-3 z-[500] pointer-events-auto animate-slideUp">
          <div className="rounded-3xl bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 p-4 shadow-lg text-center">
            <p className="text-sm font-semibold text-gray-900 dark:text-zinc-100">
              {activeCategory !== 'all' ? `No ${activeCategory} found nearby` : 'No places found here yet'}
            </p>
            <p className="mt-0.5 text-xs text-gray-500 dark:text-zinc-400">
              {activeCategory !== 'all'
                ? `There are no spots categorized under "${activeCategory}" within 5km.`
                : 'Pan the map or move closer to explore.'}
            </p>
            {activeCategory !== 'all' && basePlaces.length > 0 && (
              <button
                type="button"
                onClick={() => setActiveCategory('all')}
                className="mt-3 inline-flex items-center justify-center px-4 py-2 rounded-xl bg-[#1F5A3F] hover:bg-[#194B34] text-white text-xs font-semibold press-scale transition-colors"
              >
                View all {basePlaces.length} places
              </button>
            )}
          </div>
        </div>
      )}
      {/* Interactive Day Selection Modal */}
      <AddToItineraryModal {...itineraryAdd.modalProps} />
    </div>
  );
};
