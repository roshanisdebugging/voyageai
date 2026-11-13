import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Download, AlertTriangle, X } from 'lucide-react';
import { useTrip } from '../../features/trip/TripContext';

/**
 * In-app notice when the server finishes an itinerary (ITINERARY_READY over the WebSocket).
 * READY offers to open the itinerary page, where the PDF download lives.
 */
export const ItineraryReadyNotice: React.FC = () => {
  const navigate = useNavigate();
  const { readyNotice, dismissReadyNotice, setCurrentTripId } = useTrip();

  if (!readyNotice) return null;
  const isReady = readyNotice.status === 'READY';

  const openTrip = () => {
    setCurrentTripId(readyNotice.tripId);
    dismissReadyNotice();
    navigate('/trip/itinerary');
  };

  return (
    <div
      role="alertdialog"
      aria-labelledby="itinerary-ready-title"
      className="fixed top-[calc(env(safe-area-inset-top,0px)+12px)] left-1/2 -translate-x-1/2 z-[65] w-[calc(100%-32px)] max-w-sm bg-white border border-[#D9DEDA] rounded-3xl shadow-2xl p-4 space-y-3 animate-fadeIn"
    >
      <div className="flex items-start gap-3">
        <div className={`w-10 h-10 rounded-2xl flex items-center justify-center shrink-0 ${isReady ? 'bg-[#E8F0EE] text-[#355F58]' : 'bg-rose-50 text-rose-600'}`}>
          {isReady ? <Download className="w-5 h-5" /> : <AlertTriangle className="w-5 h-5" />}
        </div>
        <div className="flex-1 min-w-0">
          <h2 id="itinerary-ready-title" className="text-sm font-extrabold text-[#1F2522]">
            {isReady ? 'Your itinerary is ready to download.' : "We couldn't make your itinerary."}
          </h2>
          <p className="text-xs text-[#5F6863] mt-0.5 truncate">
            {isReady ? `${readyNotice.tripTitle}. Shall I take you to the page?` : `${readyNotice.tripTitle}. Open the trip to try again.`}
          </p>
        </div>
        <button
          type="button"
          aria-label="Dismiss"
          onClick={dismissReadyNotice}
          className="w-8 h-8 rounded-full bg-[#F0F2EF] text-[#5F6863] hover:text-[#1F2522] flex items-center justify-center shrink-0"
        >
          <X className="w-4 h-4" />
        </button>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <button
          type="button"
          onClick={dismissReadyNotice}
          className="py-2.5 rounded-2xl bg-[#F0F2EF] border border-[#D9DEDA] text-[#1F2522] text-xs font-bold"
        >
          Not now
        </button>
        <button
          type="button"
          onClick={openTrip}
          className="py-2.5 rounded-2xl bg-[#355F58] hover:bg-[#2C504A] text-white text-xs font-extrabold"
        >
          {isReady ? 'Yes, take me there' : 'Open trip'}
        </button>
      </div>
    </div>
  );
};
