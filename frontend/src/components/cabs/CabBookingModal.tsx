import React from 'react';
import { useApp } from '../../context/AppContext';
import { X, Car, Navigation, ExternalLink } from 'lucide-react';
import { googleMapsDirectionsUrl, uberRideUrl } from '../../utils/rideLinks';

/**
 * "Book a ride" sheet. The app can't book cabs itself, so it hands the ride over to a real
 * app (Uber) or to directions. It never shows made-up fares, drivers or booking codes, and
 * never writes a transport or expense to the trip.
 */
export const CabBookingModal: React.FC = () => {
  const { isCabModalOpen, setIsCabModalOpen, cabDestination } = useApp();

  if (!isCabModalOpen) return null;

  const target = { name: cabDestination || 'your destination' };
  const close = () => setIsCabModalOpen(false);

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center p-4 bg-[#1F2522]/60 backdrop-blur-sm animate-fadeIn overflow-y-auto">
      <div className="w-full max-w-lg bg-white border border-[#D9DEDA] rounded-3xl p-6 space-y-5 shadow-2xl relative text-[#1F2522] my-auto">
        <button
          onClick={close}
          aria-label="Close"
          className="absolute top-4 right-4 p-2 rounded-xl bg-[#F0F2EF] text-[#5F6863] hover:text-[#1F2522] press-scale"
        >
          <X className="w-5 h-5" />
        </button>

        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-2xl bg-[#E8F0EE] text-[#355F58] border border-[#D9DEDA]">
            <Car className="w-6 h-6 text-[#355F58]" />
          </div>
          <div>
            <h3 className="font-extrabold text-xl text-[#1F2522]">Get a ride</h3>
            <p className="text-xs text-[#5F6863] font-medium">Opens your ride or maps app with the destination filled in</p>
          </div>
        </div>

        <div className="p-4 rounded-2xl bg-[#F0F2EF] border border-[#D9DEDA] text-xs">
          <span className="text-[#5F6863] font-bold block">Destination</span>
          <span className="text-sm font-extrabold text-[#355F58] break-words">{cabDestination || 'Not set'}</span>
        </div>

        <div className="space-y-2.5">
          <a
            href={uberRideUrl(target)}
            target="_blank"
            rel="noopener noreferrer"
            onClick={close}
            className="w-full py-4 rounded-2xl bg-[#355F58] hover:bg-[#2C504A] text-white font-extrabold text-base flex items-center justify-center gap-2 shadow-xs press-scale min-h-[54px]"
          >
            <Car className="w-5 h-5" />
            <span>Book in Uber</span>
            <ExternalLink className="w-4 h-4 opacity-80" />
          </a>
          <a
            href={googleMapsDirectionsUrl(target)}
            target="_blank"
            rel="noopener noreferrer"
            onClick={close}
            className="w-full py-3.5 rounded-2xl bg-[#F0F2EF] border border-[#D9DEDA] text-[#1F2522] font-bold text-sm flex items-center justify-center gap-2 hover:border-[#355F58]/40 min-h-[48px]"
          >
            <Navigation className="w-4 h-4 text-[#355F58]" />
            <span>Directions in Google Maps</span>
          </a>
        </div>

        <p className="text-[11px] text-[#7C8580] text-center">
          Fares and drivers come from the ride app. VoyageAI doesn't book or charge for rides.
        </p>
      </div>
    </div>
  );
};
