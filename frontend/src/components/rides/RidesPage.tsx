import React, { useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useApp } from '../../context/AppContext';
import { useTrip } from '../../features/trip/TripContext';
import { Car, ArrowLeft, Navigation, ExternalLink, MapPin } from 'lucide-react';
import { googleMapsDirectionsUrl, uberRideUrl } from '../../utils/rideLinks';

/**
 * Rides: pick one of the trip's stops and hand the ride over to a real app (Uber),
 * Google Maps directions, or in-app navigation. The app doesn't book cabs itself, so it
 * shows no fares, drivers or booking codes.
 */
export const RidesPage: React.FC = () => {
  const navigate = useNavigate();
  const { openInAppNavigation, setTripView, setActiveTab, userLocationName } = useApp();
  const { currentTrip, currentItinerary } = useTrip();

  const activeDestName = currentTrip?.destination?.name || 'your destination';
  const destLat = currentTrip?.destination?.latitude;
  const destLng = currentTrip?.destination?.longitude;

  // The trip's itinerary stops (with coordinates) are the drop-off choices.
  const tripStops = useMemo(() => {
    const list: Array<{ id: string; title: string; locationName: string; dayNumber: number; coordinates: [number, number] }> = [];
    currentItinerary?.days?.forEach(day => {
      (day.activities || []).forEach(act => {
        if (act.latitude && act.longitude) {
          list.push({
            id: act.id,
            title: act.title,
            locationName: act.locationName || activeDestName,
            dayNumber: day.dayNumber,
            coordinates: [act.latitude, act.longitude],
          });
        }
      });
    });
    if (list.length === 0 && currentTrip?.destination?.name && destLat && destLng) {
      list.push({
        id: 'trip-destination',
        title: currentTrip.destination.name,
        locationName: currentTrip.destination.name,
        dayNumber: 0,
        coordinates: [destLat, destLng],
      });
    }
    return list;
  }, [currentItinerary, activeDestName, currentTrip, destLat, destLng]);

  const [selectedStopId, setSelectedStopId] = useState<string>('');
  const stop = tripStops.find(s => s.id === selectedStopId) || tripStops[0];
  const target = stop ? { name: stop.title, coordinates: stop.coordinates } : null;

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
          <Car className="w-3.5 h-3.5" />
          <span>Rides</span>
        </div>
      </div>

      {/* Route */}
      <div className="relative rounded-3xl p-6 bg-white border border-[#D9DEDA] shadow-xs space-y-3 overflow-hidden">
        <h1 className="text-2xl font-black text-[#1F2522] tracking-tight">Get a ride in {activeDestName}</h1>
        <p className="text-xs text-[#5F6863] leading-relaxed">
          Choose a stop from your trip. We open Uber or Google Maps with it filled in; fares and drivers come from those apps.
        </p>

        {tripStops.length === 0 ? (
          <div className="p-4 rounded-2xl bg-[#F0F2EF] border border-[#D9DEDA] text-xs text-[#5F6863] space-y-3">
            <p>Open a trip with an itinerary to choose where to go.</p>
            <button
              type="button"
              onClick={() => navigate('/trips')}
              className="px-3.5 py-2 rounded-xl bg-[#355F58] hover:bg-[#2C504A] text-white font-bold text-xs"
            >
              My trips
            </button>
          </div>
        ) : (
          <div className="p-3.5 rounded-2xl bg-[#F0F2EF] border border-[#D9DEDA] space-y-2.5 text-xs">
            <div className="flex items-center gap-2">
              <div className="w-2.5 h-2.5 rounded-full bg-[#355F58] shrink-0 ring-4 ring-[#355F58]/20" />
              <div className="min-w-0 flex-1">
                <span className="text-[10px] text-[#5F6863] font-bold uppercase tracking-wider block">Pickup</span>
                <span className="font-extrabold text-[#1F2522] truncate block">{userLocationName || 'Your current location'}</span>
              </div>
            </div>

            <div className="w-full h-px bg-[#D9DEDA]" />

            <div className="flex items-center gap-2">
              <div className="w-2.5 h-2.5 rounded-full bg-amber-600 shrink-0 ring-4 ring-amber-500/20" />
              <div className="min-w-0 flex-1">
                <label htmlFor="ride-stop" className="text-[10px] text-[#5F6863] font-bold uppercase tracking-wider block">Drop-off</label>
                <select
                  id="ride-stop"
                  value={stop?.id || ''}
                  onChange={(e) => setSelectedStopId(e.target.value)}
                  className="w-full bg-white border border-[#D9DEDA] rounded-xl px-2.5 py-1.5 text-xs font-bold text-[#355F58] outline-none focus:border-[#355F58] transition-all cursor-pointer"
                >
                  {tripStops.map(s => (
                    <option key={s.id} value={s.id}>
                      {s.dayNumber > 0 ? `Day ${s.dayNumber}: ` : ''}{s.title}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </div>
        )}
      </div>

      {stop && target && (
        <div className="space-y-2.5">
          <a
            href={uberRideUrl(target)}
            target="_blank"
            rel="noopener noreferrer"
            className="w-full py-4 rounded-2xl bg-[#355F58] hover:bg-[#2C504A] text-white font-black text-sm shadow-xs transition-all flex items-center justify-center gap-2 press-scale min-h-[54px]"
          >
            <Car className="w-5 h-5 text-white" />
            <span>Book in Uber</span>
            <ExternalLink className="w-4 h-4 opacity-80" />
          </a>
          <div className="grid grid-cols-2 gap-2">
            <a
              href={googleMapsDirectionsUrl(target)}
              target="_blank"
              rel="noopener noreferrer"
              className="py-3.5 rounded-2xl bg-white border border-[#D9DEDA] text-[#1F2522] font-bold text-xs flex items-center justify-center gap-1.5 hover:border-[#355F58]/40 min-h-[48px]"
            >
              <MapPin className="w-4 h-4 text-[#355F58]" />
              <span>Google Maps</span>
            </a>
            <button
              type="button"
              onClick={() => openInAppNavigation({ title: stop.title, locationName: stop.locationName, coordinates: stop.coordinates })}
              className="py-3.5 rounded-2xl bg-white border border-[#D9DEDA] text-[#355F58] font-bold text-xs flex items-center justify-center gap-1.5 hover:border-[#355F58]/40 min-h-[48px]"
            >
              <Navigation className="w-4 h-4 text-[#355F58]" />
              <span>Navigate in app</span>
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
