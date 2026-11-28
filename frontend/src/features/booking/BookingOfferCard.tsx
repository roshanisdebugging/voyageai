import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Plane, TrainFront, BedDouble } from 'lucide-react';
import type { Trip } from '../trip/types';
import { isPastTrip } from '../trip/tripRepository';
import { BOOKING_CHANGED } from '../../voice/uiActions';
import { bookingApi, type BookingView } from './bookingApi';
import { bookingCardVisible, notifyPending, requestLine } from './bookingLogic';

const POLL_MS = 5000;
const POLL_MAX = 36;   // about 3 minutes: the email takes seconds, or ~1 minute with its one retry

/**
 * Booking stage 2: the offer on the trip page once the plan is ready. Tapping a service opens the step screen
 * (that service already ticked); voice "book karwana hai" starts the same flow. "Not now" hides the card until the
 * page opens again (no stored flag), and ends a half-done flow. Nothing is booked, saved or sent.
 */
export const BookingOfferCard: React.FC<{ trip: Trip }> = ({ trip }) => {
  const navigate = useNavigate();
  const [dismissed, setDismissed] = useState(false);
  const [flow, setFlow] = useState<BookingView | null>(null);
  const polls = useRef(0);
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

  // Stage 4: while the partner email is going out, re-read the request so the card turns to sent / failed.
  const sending = notifyPending(flow?.request);
  useEffect(() => {
    if (!sending) { polls.current = 0; return; }
    if (polls.current >= POLL_MAX) return;
    const t = window.setTimeout(() => { polls.current += 1; reload(); }, POLL_MS);
    return () => window.clearTimeout(t);
  }, [sending, flow, reload]);

  if (!visible) return null;
  const inProgress = Boolean(flow?.active);
  const request = flow?.request ?? null;
  const status = requestLine(request);

  const open = (services?: string[]) => navigate('/trip/booking', { state: { services } });
  const notNow = () => {
    setDismissed(true);
    if (inProgress) bookingApi.cancel(trip.id).catch(() => {});
  };

  // Stage 3: an open request (new / contacted): the status instead of the offer (shown to its owner only).
  if (!inProgress && request?.open && status) {
    return (
      <section aria-label="Booking request" className="bg-[var(--color-surface)] border border-[var(--color-border)] dark:border-zinc-700 rounded-3xl p-4 space-y-1 shadow-xs">
        <p className="wrap-anywhere text-sm font-extrabold text-[var(--color-text-primary)]">{status}</p>
        {(request.notifyText || flow?.testNote) && (
          <p role="status" className="wrap-anywhere text-xs font-medium text-[var(--color-text-secondary)]">{request.notifyText || flow?.testNote}</p>
        )}
      </section>
    );
  }

  const chip = 'flex min-h-12 flex-1 items-center justify-center gap-1.5 rounded-2xl border border-[#355F58]/30 bg-[#E8F0EE] px-2 text-sm font-extrabold text-(--color-primary) press-scale dark:border-emerald-800 dark:bg-[#12332B]';

  return (
    <section aria-label="Booking" className="bg-[var(--color-surface)] border border-[var(--color-border)] dark:border-zinc-700 rounded-3xl p-4 space-y-3 shadow-xs">
      {!inProgress && status && (
        <p className="wrap-anywhere text-xs font-bold text-[var(--color-text-secondary)]">{status}</p>
      )}
      <p className="text-sm font-extrabold text-[var(--color-text-primary)]">
        {inProgress ? `Booking in progress (${flow?.progress?.label ?? ''}).` : 'Need a flight, train, or hotel?'}
      </p>
      {inProgress ? (
        <div className="flex gap-2">
          <button type="button" className={chip} onClick={() => open()}>Resume booking</button>
        </div>
      ) : (
        <div className="flex gap-2">
          <button type="button" className={chip} onClick={() => open(['flight'])}><Plane className="size-4 shrink-0" aria-hidden="true" />Flight</button>
          <button type="button" className={chip} onClick={() => open(['train'])}><TrainFront className="size-4 shrink-0" aria-hidden="true" />Train</button>
          <button type="button" className={chip} onClick={() => open(['hotel'])}><BedDouble className="size-4 shrink-0" aria-hidden="true" />Hotel</button>
        </div>
      )}
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] font-medium text-[var(--color-text-secondary)]">{flow?.testNote ?? ''}</span>
        <button type="button" onClick={notNow} className="min-h-11 shrink-0 px-2 text-xs font-bold text-[var(--color-text-secondary)] hover:underline">
          Not now
        </button>
      </div>
    </section>
  );
};
