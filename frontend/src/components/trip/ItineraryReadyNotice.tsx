import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Download, AlertTriangle, X } from 'lucide-react';
import { useTrip } from '../../features/trip/TripContext';
import { Portal } from '../common/Portal';

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
    <Portal>
    <div
      role="alertdialog"
      aria-labelledby="itinerary-ready-title"
      aria-describedby="itinerary-ready-description"
      className="fixed left-1/2 top-[calc(var(--header-h)+var(--safe-top)+10px)] z-[var(--z-notice)] max-h-[calc(100dvh-var(--header-h)-var(--safe-top)-var(--safe-bottom)-20px)] w-[calc(100%-32px)] max-w-sm -translate-x-1/2 space-y-3 overflow-y-auto overscroll-contain rounded-3xl border border-(--itinerary-border) bg-(--color-surface) p-4 text-(--color-text-primary) shadow-2xl animate-fadeIn [&_button:focus-visible]:outline-2 [&_button:focus-visible]:outline-offset-2 [&_button:focus-visible]:outline-(--itinerary-accent)"
    >
      <div className="flex items-start gap-3">
        <div className={`flex size-10 shrink-0 items-center justify-center rounded-2xl ${isReady ? 'bg-(--itinerary-accent-surface) text-(--itinerary-accent)' : 'bg-(--itinerary-error-surface) text-(--itinerary-error)'}`}>
          {isReady ? <Download className="size-5" aria-hidden="true" /> : <AlertTriangle className="size-5" aria-hidden="true" />}
        </div>
        <div className="min-w-0 flex-1 wrap-anywhere">
          <h2 id="itinerary-ready-title" className="text-sm font-extrabold">
            {isReady ? 'Your itinerary is ready to download.' : "We couldn't make your itinerary."}
          </h2>
          <p id="itinerary-ready-description" className="mt-0.5 text-xs text-(--itinerary-muted)">
            {isReady ? `${readyNotice.tripTitle}. Shall I take you to the page?` : `${readyNotice.tripTitle}. Open the trip to try again.`}
          </p>
        </div>
        <button
          type="button"
          aria-label="Dismiss"
          onClick={dismissReadyNotice}
          className="flex size-11 shrink-0 items-center justify-center rounded-full border border-(--itinerary-control-border) bg-(--color-surface-elevated) text-(--itinerary-muted) hover:text-(--color-text-primary)"
        >
          <X className="size-4" aria-hidden="true" />
        </button>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <button
          type="button"
          onClick={dismissReadyNotice}
          className="min-h-11 rounded-2xl border border-(--itinerary-control-border) bg-(--color-surface-elevated) px-2 py-2.5 text-xs font-bold text-(--itinerary-muted) hover:text-(--color-text-primary)"
        >
          Not now
        </button>
        <button
          type="button"
          onClick={openTrip}
          className="min-h-11 rounded-2xl bg-(--color-primary) px-2 py-2.5 text-xs font-extrabold text-white hover:brightness-[0.93] dark:text-[#092319]"
        >
          {isReady ? 'Yes, take me there' : 'Open trip'}
        </button>
      </div>
    </div>
    </Portal>
  );
};
