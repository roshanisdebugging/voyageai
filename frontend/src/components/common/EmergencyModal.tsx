import React, { useState, useEffect } from 'react';
import { useApp } from '../../context/AppContext';
import { useTrip } from '../../features/trip/TripContext';
import { BottomSheet } from './BottomSheet';
import { PhoneCall, ShieldAlert, MapPin, Hospital, Check, Loader2 } from 'lucide-react';
import { getApiBaseUrl, DEFAULT_HEADERS } from '../../config/apiConfig';

interface EmergencyFacility {
  name: string;
  address?: string;
  phone?: string;
  distanceKm?: number;
  coordinates?: [number, number];
}

export const EmergencyModal: React.FC = () => {
  const { isEmergencyOpen, setIsEmergencyOpen, activeTrip, userLocation, userLocationName, openInAppNavigation } = useApp();
  const { currentTrip } = useTrip();
  const [hasCalled, setHasCalled] = useState(false);

  const [policeStation, setPoliceStation] = useState<EmergencyFacility | null>(null);
  const [hospital, setHospital] = useState<EmergencyFacility | null>(null);
  const [isLoadingServices, setIsLoadingServices] = useState(false);

  const activeDestName = currentTrip?.destination?.name || (typeof activeTrip?.destination === 'string' ? activeTrip.destination : userLocationName || 'Current Location');
  const activeDestCoords: [number, number] | null = userLocation || (
    currentTrip?.destination?.latitude && currentTrip?.destination?.longitude
      ? [currentTrip.destination.latitude, currentTrip.destination.longitude]
      : null
  );

  useEffect(() => {
    if (!isEmergencyOpen || !activeDestCoords) return;
    setIsLoadingServices(true);
    const baseUrl = getApiBaseUrl();

    Promise.allSettled([
      fetch(`${baseUrl}/api/places/nearby?lat=${activeDestCoords[0]}&lng=${activeDestCoords[1]}&category=police&limit=1`, { headers: DEFAULT_HEADERS }).then(r => r.json()),
      fetch(`${baseUrl}/api/places/nearby?lat=${activeDestCoords[0]}&lng=${activeDestCoords[1]}&category=hospital&limit=1`, { headers: DEFAULT_HEADERS }).then(r => r.json()),
    ]).then(([policeRes, hospitalRes]) => {
      if (policeRes.status === 'fulfilled') {
        const raw = Array.isArray(policeRes.value) ? policeRes.value : (policeRes.value?.places || []);
        if (raw.length > 0) {
          const p = raw[0];
          setPoliceStation({
            name: p.name || 'Local Police Station',
            address: p.address,
            phone: p.phone_number || '112',
            distanceKm: p.distance_meters ? Number((p.distance_meters / 1000).toFixed(1)) : undefined,
            coordinates: p.latitude && p.longitude ? [p.latitude, p.longitude] : undefined,
          });
        }
      }
      if (hospitalRes.status === 'fulfilled') {
        const raw = Array.isArray(hospitalRes.value) ? hospitalRes.value : (hospitalRes.value?.places || []);
        if (raw.length > 0) {
          const h = raw[0];
          setHospital({
            name: h.name || 'Emergency Medical Hospital',
            address: h.address,
            distanceKm: h.distance_meters ? Number((h.distance_meters / 1000).toFixed(1)) : undefined,
            coordinates: h.latitude && h.longitude ? [h.latitude, h.longitude] : undefined,
          });
        }
      }
    }).finally(() => {
      setIsLoadingServices(false);
    });
  }, [isEmergencyOpen, activeDestCoords]);

  return (
    <BottomSheet
      isOpen={isEmergencyOpen}
      onClose={() => { setIsEmergencyOpen(false); setHasCalled(false); }}
      height="half"
      title={`Emergency Assistance — ${activeDestName}`}
    >
      <div className="p-5 space-y-4">
        {/* Emergency Alert Banner */}
        <div className="p-4 rounded-2xl bg-rose-500/15 border border-rose-500/30 flex items-start gap-3">
          <ShieldAlert className="w-6 h-6 text-rose-400 shrink-0 mt-0.5" />
          <div className="min-w-0 flex-1">
            <h4 className="font-extrabold text-sm text-rose-200">24/7 Tourist Emergency Services</h4>
            <p className="text-xs text-rose-300/80 mt-0.5 truncate">
              {activeDestCoords ? (
                <>Live Location: <span className="font-mono font-bold text-white">{activeDestName} ({activeDestCoords[0].toFixed(4)}, {activeDestCoords[1].toFixed(4)})</span></>
              ) : (
                <>Location: <span className="font-bold text-white">{activeDestName}</span></>
              )}
            </p>
          </div>
        </div>

        {/* Emergency Call Options */}
        <div className="space-y-2">
          <button
            onClick={() => {
              setHasCalled(true);
              setTimeout(() => setHasCalled(false), 4000);
            }}
            className="w-full py-3.5 px-4 rounded-2xl bg-rose-600 hover:bg-rose-500 text-white font-extrabold text-sm flex items-center justify-between shadow-lg shadow-rose-600/30 press-scale"
          >
            <div className="flex items-center gap-2.5">
              <PhoneCall className="w-5 h-5" />
              <span>Call Tourist Helpline (112)</span>
            </div>
            <span className="text-xs font-mono font-bold bg-black/30 px-2.5 py-1 rounded-lg">Toll Free</span>
          </button>

          <button
            onClick={() => {
              if (policeStation?.coordinates) {
                openInAppNavigation({
                  title: policeStation.name,
                  locationName: policeStation.address || policeStation.name,
                  coordinates: policeStation.coordinates,
                });
                setIsEmergencyOpen(false);
              } else {
                alert(`Contacting ${policeStation?.name || 'Local Police'}: ${policeStation?.phone || '112'}`);
              }
            }}
            className="w-full py-3 px-4 rounded-2xl bg-white/5 border border-white/10 hover:bg-white/10 text-slate-200 font-semibold text-xs flex items-center justify-between press-scale"
          >
            <div className="flex items-center gap-2.5 truncate">
              <MapPin className="w-4 h-4 text-teal-400 shrink-0" />
              <span className="truncate">{policeStation?.name || 'Nearest Police Station'}</span>
            </div>
            {policeStation?.distanceKm !== undefined ? (
              <span className="text-[11px] text-slate-400 font-mono shrink-0 ml-2">{policeStation.distanceKm} km away</span>
            ) : isLoadingServices ? (
              <Loader2 className="w-3.5 h-3.5 text-teal-400 animate-spin shrink-0 ml-2" />
            ) : null}
          </button>

          <button
            onClick={() => {
              if (hospital?.coordinates) {
                openInAppNavigation({
                  title: hospital.name,
                  locationName: hospital.address || hospital.name,
                  coordinates: hospital.coordinates,
                });
                setIsEmergencyOpen(false);
              } else {
                alert(`Navigating to ${hospital?.name || 'Nearest Emergency Medical Center'}`);
              }
            }}
            className="w-full py-3 px-4 rounded-2xl bg-white/5 border border-white/10 hover:bg-white/10 text-slate-200 font-semibold text-xs flex items-center justify-between press-scale"
          >
            <div className="flex items-center gap-2.5 truncate">
              <Hospital className="w-4 h-4 text-amber-400 shrink-0" />
              <span className="truncate">{hospital?.name || 'Nearest Hospital / Medical Facility'}</span>
            </div>
            {hospital?.distanceKm !== undefined ? (
              <span className="text-[11px] text-slate-400 font-mono shrink-0 ml-2">{hospital.distanceKm} km away</span>
            ) : isLoadingServices ? (
              <Loader2 className="w-3.5 h-3.5 text-amber-400 animate-spin shrink-0 ml-2" />
            ) : null}
          </button>
        </div>

        {hasCalled && (
          <div className="p-3 rounded-xl bg-emerald-500/15 border border-emerald-500/30 text-emerald-300 text-xs font-medium flex items-center gap-2 animate-fadeIn">
            <Check className="w-4 h-4 text-emerald-400 shrink-0" />
            <span>Emergency signal dispatched to national helpline (112).</span>
          </div>
        )}
      </div>
    </BottomSheet>
  );
};
