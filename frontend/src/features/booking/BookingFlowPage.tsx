import { useCallback, useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { ArrowLeft, Building2, Check, Info, Plane, RefreshCw, TrainFront } from 'lucide-react';
import { useTrip } from '../trip/TripContext';
import { BOOKING_CHANGED } from '../../voice/uiActions';
import { bookingApi, type BookingView, type TravelDetailsAnswer } from './bookingApi';
import { PreferenceProgress } from '../../components/preferences/PreferenceProgress';
import { AirlinePreference } from './AirlinePreference';
import { DepartureWindow, HotelRating, RoomCount, TravelerDetails } from './BookingFormControls';
import { BookingLiveCard } from './BookingLiveCard';
import { notifyPending, toggleService } from './bookingLogic';
import './booking-flow.css';

const serviceIcons = { flight: Plane, train: TrainFront, hotel: Building2 };

export function BookingFlowPage() {
  const { currentTrip } = useTrip();
  return <BookingFlow key={currentTrip?.id} tripId={currentTrip?.id} />;
}

function BookingFlow({ tripId }: { tripId?: string }) {
  const navigate = useNavigate();
  const { state } = useLocation() as { state?: { services?: string[] } };
  const [view, setView] = useState<BookingView | null>(null);
  const [busy, setBusy] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [editingDetails, setEditingDetails] = useState(false);
  const requestInProgress = useRef(false);
  const preselect = useRef<string[]>(state?.services ?? []);
  const lastQuestion = useRef<string | undefined>(undefined);

  const show = useCallback((v: BookingView) => {
    setView(v);
    setLoadError(null);
    if (v.question !== lastQuestion.current) {
      lastQuestion.current = v.question;
      setEditingDetails(false);
      if (v.question === 'services') {
        const fromCard = preselect.current;
        preselect.current = [];
        setPicked(v.selected?.length ? v.selected : fromCard);
      }
    }
  }, []);

  const run = useCallback(async (fn: () => Promise<BookingView>) => {
    if (requestInProgress.current) return;
    requestInProgress.current = true;
    setBusy(true);
    try {
      show(await fn());
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Booking couldn't load. Please try again.");
    } finally {
      requestInProgress.current = false;
      setBusy(false);
    }
  }, [show]);

  // Open: resume the flow for this trip, or start one.
  useEffect(() => {
    if (!tripId) return;
    bookingApi.start(tripId).then(show)
      .catch((err) => setLoadError(err instanceof Error ? err.message : "Booking couldn't load. Please try again."));
  }, [tripId, show]);

  // A voice answer changed the state, or the user came back to this window: reload (never starts a new flow).
  useEffect(() => {
    if (!tripId) return;
    const reload = () => { bookingApi.get(tripId).then(show).catch(() => {}); };
    window.addEventListener(BOOKING_CHANGED, reload);
    window.addEventListener('focus', reload);
    return () => {
      window.removeEventListener(BOOKING_CHANGED, reload);
      window.removeEventListener('focus', reload);
    };
  }, [tripId, show]);

  // Stage 4: after the confirm, re-read while the partner email is going out (the message turns to sent / failed).
  const sending = Boolean(view && !view.active && notifyPending(view.request));
  const polls = useRef(0);
  useEffect(() => {
    if (!tripId || !sending || polls.current >= 36) return;
    const t = window.setTimeout(() => { polls.current += 1; bookingApi.get(tripId).then(show).catch(() => {}); }, 5000);
    return () => window.clearTimeout(t);
  }, [tripId, sending, view, show]);

  if (!tripId) {
    return (
      <div className="max-w-xl mx-auto px-4 pt-10 pb-28 text-center space-y-4">
        <p className="text-sm font-bold text-[var(--color-text-primary)]">Open a trip to start booking.</p>
        <button type="button" onClick={() => navigate('/trips')} className="min-h-12 w-full rounded-2xl bg-[var(--color-primary)] text-white font-extrabold text-sm dark:text-zinc-950">My trips</button>
      </div>
    );
  }

  const answer = (value: string | string[]) => {
    if (!view?.question || busy) return;
    const q = view.question;
    void run(() => bookingApi.answer(tripId, q, value));
  };
  const submitDetails = (value: TravelDetailsAnswer) => {
    if (busy) return;
    void run(async () => {
      const result = await bookingApi.answer(tripId, 'traveler_details', value);
      if (result.question === 'review' && !result.error) setEditingDetails(false);
      return result;
    });
  };

  const notNow = async () => {
    try { await bookingApi.cancel(tripId); } catch { /* the 2-hour expiry removes it anyway */ }
    navigate('/trip');
  };

  const choiceCls = 'booking-choice';
  const primaryCls = 'booking-primary';
  const finishedOrGone = view && !view.active;
  const details = view?.travelDetails && (editingDetails || view.question !== 'review') ? view.travelDetails : undefined;
  const isReview = view?.kind === 'review' && !details;
  const showSummary = Boolean(view?.active && view.card && !isReview);
  const progress = view?.progress;
  const followsTravelerStep = ['phone', 'phone_ok', 'review', 'change'].includes(view?.question ?? '');
  const step = progress ? progress.step - Number(followsTravelerStep) - Number(editingDetails) : null;
  const rangeQuestion = view?.question === 'flight_time' || view?.question === 'train_time';
  const airlineQuestion = view?.question === 'flight_airline';
  const ratingQuestion = view?.question === 'hotel_type';
  const roomQuestion = view?.question === 'hotel_rooms';
  const currentAnswer = view?.currentAnswer == null ? undefined : String(view.currentAnswer);
  const anyLabel = view?.choices?.find(choice => choice.value === 'any')?.label ?? 'No preference';
  const prompt = details ? 'Traveler and contact details'
    : rangeQuestion ? (view?.question === 'flight_time' ? 'When would you like to fly?' : 'When would you like to take the train?')
    : airlineQuestion ? 'How should we choose your airline?'
    : ratingQuestion ? 'Choose a hotel rating'
    : roomQuestion ? 'How many rooms do you need?' : view?.prompt;

  const goBack = () => {
    if (editingDetails) {
      setEditingDetails(false);
    } else if (isReview) {
      setEditingDetails(true);
    } else if (details) {
      void run(() => bookingApi.answer(tripId, 'traveler_details_back', ''));
    } else {
      void run(() => bookingApi.back(tripId));
    }
  };

  return (
    <div className="booking-flow space-y-4">
      {view?.active && (
        <header className="booking-header space-y-2">
          {view.canBack && (
            <button type="button" disabled={busy} onClick={goBack} className="booking-back">
              <ArrowLeft className="size-4" aria-hidden="true" />Back
            </button>
          )}
          {progress && step && <PreferenceProgress currentStep={step} totalSteps={progress.total - 1} />}
        </header>
      )}

      {view?.testNote && (
        <p className="booking-test-note"><Info size={16} aria-hidden="true" />{view.testNote}</p>
      )}

      {loadError && (
        <div className="space-y-3">
          <p role="alert" className="text-sm font-bold text-red-700 dark:text-red-400">{loadError}</p>
          <button type="button" className={choiceCls} onClick={() => void run(() => bookingApi.start(tripId))}>Try again</button>
        </div>
      )}

      {!view && !loadError && (
        <div className="flex items-center justify-center gap-2 py-10 text-sm text-[var(--color-text-secondary)]">
          <RefreshCw className="size-4 animate-spin" aria-hidden="true" />Loading…
        </div>
      )}

      {finishedOrGone && (
        <div className="space-y-4 text-center">
          <p role="status" className="text-base font-extrabold text-[var(--color-text-primary)]">
            {view.finished || view.request?.open ? (view.message || `Request ${view.request?.requestNo}: ${view.request?.statusLabel}`) : 'This booking session has ended.'}
          </p>
          {!view.finished && !view.request?.open && (
            <button type="button" className={choiceCls} onClick={() => void run(() => bookingApi.start(tripId))}>Start again</button>
          )}
          <button type="button" className={primaryCls} onClick={() => navigate('/trip')}>Back to trip</button>
        </div>
      )}

      {view?.active && (
        <div className={showSummary ? 'booking-content booking-with-summary' : 'booking-content'}>
          <section className="booking-question space-y-4" aria-labelledby="booking-question-title" aria-busy={busy}>
            <h1 id="booking-question-title">{prompt}</h1>
            {view.error && <p role="alert" className="book-field-error">{view.error}</p>}

            {view.kind === 'services' && (
              <div className="space-y-2">
                {(view.choices || []).map((c) => {
                  const on = picked.includes(c.value);
                  const Icon = serviceIcons[c.value as keyof typeof serviceIcons];
                  return (
                    <button key={c.value} type="button" aria-pressed={on} disabled={busy} onClick={() => setPicked((p) => toggleService(p, c.value))}
                      className={choiceCls}>
                      <span className="flex items-center gap-2">{Icon && <Icon size={18} aria-hidden="true" />}{c.label}</span>{on && <Check className="size-4" aria-hidden="true" />}
                    </button>
                  );
                })}
                <button type="button" className={primaryCls} disabled={!picked.length || busy} onClick={() => answer(picked)}>Continue</button>
              </div>
            )}

            {rangeQuestion && <DepartureWindow key={view.question} answer={answer} busy={busy} primaryClass={primaryCls} anyLabel={anyLabel} initialValue={currentAnswer} />}
            {airlineQuestion && <AirlinePreference answer={answer} busy={busy} currentValue={currentAnswer} />}
            {ratingQuestion && <HotelRating answer={answer} busy={busy} primaryClass={primaryCls} anyLabel={anyLabel} initialValue={currentAnswer} />}
            {roomQuestion && <RoomCount answer={answer} busy={busy} primaryClass={primaryCls} anyLabel={anyLabel} initialValue={currentAnswer} />}
            {details && <TravelerDetails details={details} busy={busy} primaryClass={primaryCls} answer={submitDetails} />}

            {!details && !rangeQuestion && !airlineQuestion && !ratingQuestion && !roomQuestion &&
              (view.kind === 'choice' || view.kind === 'yesno' || view.kind === 'change') && (
                <div className="grid grid-cols-2 gap-2">
                  {(view.choices || []).map(choice => (
                    <button key={choice.value} type="button" disabled={busy} className={choiceCls} onClick={() => answer(choice.value)}>
                      {choice.label}
                    </button>
                  ))}
                </div>
              )}

            {isReview && (
              <div className="space-y-3">
                <ul className="booking-review-list">
                  {(view.summary || []).map((line) => (
                    <li key={line.part} className="flex items-start justify-between gap-3 py-2">
                      <div className="min-w-0">
                        <p className="text-xs font-extrabold text-[var(--color-text-secondary)]">{line.label}</p>
                        <p className="wrap-anywhere text-sm font-bold text-[var(--color-text-primary)]">{line.text}</p>
                        {line.note && <p className="wrap-anywhere mt-1 text-xs font-medium text-[var(--color-text-secondary)]">{line.note}</p>}
                      </div>
                      <button type="button" disabled={busy} onClick={() => {
                        if (line.part === 'phone' || line.part.startsWith('traveller:')) setEditingDetails(true);
                        else answer(`change:${line.part}`);
                      }}
                        className="min-h-11 shrink-0 px-2 text-xs font-bold text-[var(--color-primary)] hover:underline">Edit</button>
                    </li>
                  ))}
                </ul>
                {!view.testNote && view.consent && <p className="book-field-hint">{view.consent}</p>}
                <button type="button" disabled={busy} className={primaryCls} onClick={() => answer('yes')}>Confirm booking request</button>
              </div>
            )}

            <button type="button" disabled={busy} onClick={() => void notNow()} className="booking-not-now">
              Not now
            </button>
          </section>
          {showSummary && view.card && <BookingLiveCard card={view.card} />}
        </div>
      )}
    </div>
  );
}

export default BookingFlowPage;
