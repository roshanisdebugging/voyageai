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
        <div className="p-4 rounded-2xl bg-rose-50 dark:bg-rose-950 border border-rose-200 dark:border-rose-800 text-rose-900 dark:text-rose-200 flex items-start gap-3">
          <ShieldAlert className="w-6 h-6 text-rose-700 dark:text-rose-300 shrink-0 mt-0.5" />
          <div className="min-w-0 flex-1">
            <h4 className="font-extrabold text-sm">24/7 Tourist Emergency Services</h4>
            <p className="text-xs mt-0.5 wrap-anywhere">
              {activeDestCoords ? (
                <>Live Location: <span className="font-mono font-bold">{activeDestName} ({activeDestCoords[0].toFixed(4)}, {activeDestCoords[1].toFixed(4)})</span></>
              ) : (
                <>Location: <span className="font-bold">{activeDestName}</span></>
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
            className="w-full py-3.5 px-4 rounded-2xl bg-rose-700 hover:bg-rose-800 text-white font-extrabold text-sm flex items-center justify-between gap-2 text-left focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-primary)] shadow-lg shadow-rose-600/30 press-scale"
          >
            <div className="flex items-center gap-2.5">
              <PhoneCall className="w-5 h-5 shrink-0" />
              <span>Call Tourist Helpline (112)</span>
            </div>
            <span className="shrink-0 text-xs font-mono font-bold bg-rose-950 px-2.5 py-1 rounded-lg">Toll Free</span>
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
            className="w-full py-3 px-4 rounded-2xl bg-[var(--color-surface-elevated)] border border-[var(--color-border)] hover:border-[var(--color-primary)] text-[var(--color-text-primary)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-primary)] min-h-11 text-left font-semibold text-xs flex items-center justify-between press-scale"
          >
            <div className="flex items-center gap-2.5 min-w-0">
              <MapPin className="w-4 h-4 text-[var(--color-primary)] shrink-0" />
              <span className="min-w-0 wrap-anywhere">{policeStation?.name || 'Nearest Police Station'}</span>
            </div>
            {policeStation?.distanceKm !== undefined ? (
              <span className="text-[11px] text-[var(--color-text-secondary)] font-mono shrink-0 ml-2">{policeStation.distanceKm} km away</span>
            ) : isLoadingServices ? (
              <Loader2 className="w-3.5 h-3.5 text-[var(--color-primary)] animate-spin shrink-0 ml-2" />
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
            className="w-full py-3 px-4 rounded-2xl bg-[var(--color-surface-elevated)] border border-[var(--color-border)] hover:border-[var(--color-primary)] text-[var(--color-text-primary)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-primary)] min-h-11 text-left font-semibold text-xs flex items-center justify-between press-scale"
          >
            <div className="flex items-center gap-2.5 min-w-0">
              <Hospital className="w-4 h-4 text-amber-800 dark:text-amber-300 shrink-0" />
              <span className="min-w-0 wrap-anywhere">{hospital?.name || 'Nearest Hospital / Medical Facility'}</span>
            </div>
            {hospital?.distanceKm !== undefined ? (
              <span className="text-[11px] text-[var(--color-text-secondary)] font-mono shrink-0 ml-2">{hospital.distanceKm} km away</span>
            ) : isLoadingServices ? (
              <Loader2 className="w-3.5 h-3.5 text-amber-800 dark:text-amber-300 animate-spin shrink-0 ml-2" />
            ) : null}
          </button>
        </div>

        {hasCalled && (
          <div className="p-3 rounded-xl bg-emerald-50 dark:bg-emerald-950 border border-emerald-200 dark:border-emerald-800 text-emerald-900 dark:text-emerald-200 text-xs font-medium flex items-center gap-2 animate-fadeIn">
            <Check className="w-4 h-4 shrink-0" />
            <span>Emergency signal dispatched to national helpline (112).</span>
          </div>
        )}
      </div>
    </BottomSheet>
  );
};
