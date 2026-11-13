import React, { useState, useEffect } from 'react';
import { useApp } from '../../context/AppContext';
import { Search, MapPin, Navigation, AlertTriangle, CheckCircle2, X, Loader2, Crosshair } from 'lucide-react';
import { wsClient } from '../../services/wsClient';

interface LocationSearchResult {
  id: string;
  name: string;
  city?: string;
  region?: string;
  country?: string;
  latitude: number;
  longitude: number;
  displayName: string;
}

export const ManualLocationModal: React.FC = () => {
  const {
    isLocationModalOpen,
    setIsLocationModalOpen,
    userLocation,
    userLocationAccuracy,
    userLocationName,
    locationSource,
    syncUserLocation,
    retryGPS
  } = useApp();

  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<LocationSearchResult[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [isLocating, setIsLocating] = useState(false);

  // Debounced place search via WebSocket
  useEffect(() => {
    if (!searchQuery || searchQuery.trim().length < 2) {
      setSearchResults([]);
      return;
    }

    const timer = setTimeout(async () => {
      setIsSearching(true);
      try {
        const data = await wsClient.sendRequest('location:search', { query: searchQuery });
        if (Array.isArray(data)) {
          setSearchResults(data);
        }
      } catch (err) {
        console.warn('Location search WebSocket error:', err);
      } finally {
        setIsSearching(false);
      }
    }, 350);

    return () => clearTimeout(timer);
  }, [searchQuery]);

  if (!isLocationModalOpen) return null;

  const isLowAccuracy = locationSource === 'gps' && userLocationAccuracy !== null && userLocationAccuracy > 1000;
  const isNoLocation = !userLocation;

  const quickCities = [
    { name: 'Hawa Mahal, Jaipur', lat: 26.9239, lng: 75.8267, city: 'Jaipur, RJ' },
    { name: 'Connaught Place, Delhi', lat: 28.6315, lng: 77.2167, city: 'New Delhi' },
    { name: 'Bandra West, Mumbai', lat: 19.0596, lng: 72.8295, city: 'Mumbai, MH' },
    { name: 'Panaji, Goa', lat: 15.4909, lng: 73.8278, city: 'Goa' },
    { name: 'MG Road, Bengaluru', lat: 12.9716, lng: 77.5946, city: 'Bengaluru, KA' }
  ];

  const handleSelectLocation = async (lat: number, lng: number, name: string) => {
    await syncUserLocation(lat, lng, 10, name, 'manual');
    setIsLocationModalOpen(false);
    setSearchQuery('');
  };

  const handleRetryGPS = async () => {
    setIsLocating(true);
    await retryGPS();
    setIsLocating(false);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-md animate-fadeIn">
      <div className="w-full max-w-md bg-[#0D1117] border border-teal-500/40 rounded-3xl p-6 shadow-2xl space-y-5 text-white relative overflow-hidden">
        {/* Decorative Top Glow */}
        <div className="absolute -top-16 -left-16 w-32 h-32 bg-teal-500/20 rounded-full blur-3xl" />
        <div className="absolute -top-16 -right-16 w-32 h-32 bg-amber-500/20 rounded-full blur-3xl" />

        {/* Modal Header */}
        <div className="flex items-start justify-between relative z-10">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-xl bg-teal-500/20 border border-teal-500/30 flex items-center justify-center">
                <MapPin className="w-4 h-4 text-teal-400" />
              </div>
              <h3 className="font-black text-lg text-white tracking-tight">Confirm Your Exact Location</h3>
            </div>
            <p className="text-xs text-slate-400">
              Required for accurate route maps, navigation, and nearby recommendations.
            </p>
          </div>

          <button
            type="button"
            onClick={() => setIsLocationModalOpen(false)}
            className="p-1.5 rounded-full text-slate-400 hover:text-white bg-slate-800/80 hover:bg-slate-700 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Warning Banner if Accuracy > 1000m or missing */}
        {(isLowAccuracy || isNoLocation) && (
          <div className="p-3.5 rounded-2xl bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs space-y-1">
            <div className="flex items-center gap-2 font-bold">
              <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0" />
              <span>
                {isLowAccuracy
                  ? `Low GPS Accuracy (${(userLocationAccuracy! / 1000).toFixed(1)} km radius)`
                  : 'Location Required'}
              </span>
            </div>
            <p className="text-[11px] text-amber-200/80 leading-relaxed">
              {isLowAccuracy
                ? 'Your device returned a broad location (> 1 km radius). Please enter your exact city or area below for exact navigation.'
                : 'Automatic location is unavailable. Please select your exact location manually.'}
            </p>
          </div>
        )}

        {/* High Accuracy Current Location Badge (if accurate) */}
        {userLocation && !isLowAccuracy && (
          <div className="p-3 rounded-2xl bg-teal-500/10 border border-teal-500/30 flex items-center justify-between text-xs">
            <div className="flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-teal-400 shrink-0" />
              <div>
                <div className="font-bold text-teal-300 truncate">{userLocationName || 'Active GPS Location'}</div>
                <div className="text-[10px] text-slate-400 font-mono">
                  Accuracy: {userLocationAccuracy ? `${userLocationAccuracy.toFixed(0)}m` : 'Exact'} · GPS Active
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Location Search Input */}
        <div className="space-y-2 relative z-10">
          <label className="text-[11px] font-extrabold uppercase tracking-wider text-slate-400">
            Search Exact City, Area or Address
          </label>
          <div className="relative">
            <Search className="w-4 h-4 absolute left-3.5 top-3.5 text-slate-400" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="e.g. Patna Sahib, Connaught Place, Goa..."
              className="w-full bg-slate-900/90 border border-white/15 focus:border-teal-400 rounded-2xl pl-10 pr-10 py-3 text-xs text-white placeholder-slate-500 outline-none transition-all"
            />
            {isSearching && (
              <Loader2 className="w-4 h-4 absolute right-3.5 top-3.5 text-teal-400 animate-spin" />
            )}
          </div>
        </div>

        {/* Live Search Results */}
        {searchResults.length > 0 && (
          <div className="max-h-48 overflow-y-auto space-y-1.5 no-scrollbar bg-slate-900/90 p-2 rounded-2xl border border-white/10">
            {searchResults.map((item) => (
              <button
                key={item.id || item.displayName}
                type="button"
                onClick={() => handleSelectLocation(item.latitude, item.longitude, item.name || item.displayName)}
                className="w-full text-left p-2.5 rounded-xl hover:bg-teal-500/20 border border-transparent hover:border-teal-500/40 transition-all flex items-start gap-2.5"
              >
                <MapPin className="w-4 h-4 text-teal-400 shrink-0 mt-0.5" />
                <div className="min-w-0 flex-1">
                  <div className="text-xs font-bold text-white truncate">{item.name || item.city}</div>
                  <div className="text-[10px] text-slate-400 truncate">{item.displayName}</div>
                </div>
              </button>
            ))}
          </div>
        )}

        {/* Quick Popular Location Chips */}
        <div className="space-y-2 relative z-10">
          <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Quick Popular Locations:</span>
          <div className="flex flex-wrap gap-1.5">
            {quickCities.map((c) => (
              <button
                key={c.name}
                type="button"
                onClick={() => handleSelectLocation(c.lat, c.lng, c.name)}
                className="px-3 py-1.5 rounded-xl bg-slate-800/90 hover:bg-teal-500/20 text-slate-300 hover:text-teal-300 text-xs font-bold border border-white/10 hover:border-teal-500/40 transition-all flex items-center gap-1"
              >
                <Navigation className="w-3 h-3 text-teal-400" />
                <span>{c.city}</span>
              </button>
            ))}
          </div>
        </div>

        {/* Action Button: Retry Live GPS */}
        <div className="pt-2 flex gap-2">
          <button
            type="button"
            onClick={handleRetryGPS}
            disabled={isLocating}
            className="w-full py-3 rounded-2xl bg-teal-500 hover:bg-teal-400 text-slate-950 font-black text-xs shadow-lg transition-all flex items-center justify-center gap-2 disabled:opacity-50"
          >
            {isLocating ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Crosshair className="w-4 h-4" />
            )}
            <span>{isLocating ? 'Detecting GPS...' : 'Auto-Detect High Accuracy GPS'}</span>
          </button>
        </div>
      </div>
    </div>
  );
};
