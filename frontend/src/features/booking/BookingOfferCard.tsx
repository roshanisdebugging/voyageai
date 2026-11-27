import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Plane, TrainFront, BedDouble } from 'lucide-react';
import type { Trip } from '../trip/types';
import { isPastTrip } from '../trip/tripRepository';
import { BOOKING_CHANGED } from '../../voice/uiActions';
import { bookingApi, type BookingView } from './bookingApi';
import { bookingCardVisible } from './bookingLogic';

/**
 * Booking stage 2: the offer on the trip page once the plan is ready. Tapping a service opens the step screen
 * (that service already ticked); voice "book karwana hai" starts the same flow. "Abhi nahi" hides the card until the
 * page opens again (no stored flag), and ends a half-done flow. Nothing is booked, saved or sent.
 */
export const BookingOfferCard: React.FC<{ trip: Trip }> = ({ trip }) => {
  const navigate = useNavigate();
  const [dismissed, setDismissed] = useState(false);
  const [flow, setFlow] = useState<BookingView | null>(null);
  const visible = bookingCardVisible(trip.itineraryStatus, isPastTrip(trip), dismissed);

  const reload = useCallback(() => {
    if (!visible) return;
    bookingApi.get(trip.id).then(setFlow).catch(() => setFlow(null));
  }, [trip.id, visible]);

  useEffect(() => {
    reload();
    window.addEventListener(BOOKING_CHANGED, reload);
    window.addEventListener('focus', reload);
    return () => {
      window.removeEventListener(BOOKING_CHANGED, reload);
      window.removeEventListener('focus', reload);
    };
  }, [reload]);

  if (!visible) return null;
  const inProgress = Boolean(flow?.active);

  const open = (services?: string[]) => navigate('/trip/booking', { state: { services } });
  const notNow = () => {
    setDismissed(true);
    if (inProgress) bookingApi.cancel(trip.id).catch(() => {});
  };

  const chip = 'flex min-h-12 flex-1 items-center justify-center gap-1.5 rounded-2xl border border-[#355F58]/30 bg-[#E8F0EE] px-2 text-sm font-extrabold text-(--color-primary) press-scale dark:border-emerald-800 dark:bg-[#12332B]';

  return (
    <section aria-label="Booking" className="bg-[var(--color-surface)] border border-[var(--color-border)] dark:border-zinc-700 rounded-3xl p-4 space-y-3 shadow-xs">
      <p className="text-sm font-extrabold text-[var(--color-text-primary)]">
        {inProgress ? `Booking adhoori hai (${flow?.progress?.label ?? ''}). Jaari rakhein?` : 'Train, flight ya hotel book karwana hai?'}
      </p>
      {inProgress ? (
        <div className="flex gap-2">
          <button type="button" className={chip} onClick={() => open()}>Jaari rakhein</button>
        </div>
      ) : (
        <div className="flex gap-2">
          <button type="button" className={chip} onClick={() => open(['flight'])}><Plane className="size-4 shrink-0" aria-hidden="true" />Flight</button>
          <button type="button" className={chip} onClick={() => open(['train'])}><TrainFront className="size-4 shrink-0" aria-hidden="true" />Train</button>
          <button type="button" className={chip} onClick={() => open(['hotel'])}><BedDouble className="size-4 shrink-0" aria-hidden="true" />Hotel</button>
        </div>
      )}
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] font-medium text-[var(--color-text-secondary)]">Test version: kuch bheja nahi jayega</span>
        <button type="button" onClick={notNow} className="min-h-11 shrink-0 px-2 text-xs font-bold text-[var(--color-text-secondary)] hover:underline">
          Abhi nahi
        </button>
      </div>
    </section>
  );
};
