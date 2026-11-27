import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { ArrowLeft, Check, RefreshCw } from 'lucide-react';
import { useTrip } from '../trip/TripContext';
import { BOOKING_CHANGED } from '../../voice/uiActions';
import { bookingApi, type BookingView } from './bookingApi';
import { cleanAgeInput, cleanPhoneInput, looksLikeName, toggleService, NAME_MAX } from './bookingLogic';

/**
 * Booking stage 2: one question at a time (the server decides which), large tap choices, typed names / ages / phone,
 * "2 of 5", Back and "Abhi nahi". Voice answers the same questions: a voice reply fires BOOKING_CHANGED and this
 * screen reloads (also when the window regains focus). Nothing is saved to the database and nothing is sent.
 */
export const BookingFlowPage: React.FC = () => {
  const navigate = useNavigate();
  const { state } = useLocation() as { state?: { services?: string[] } };
  const { currentTrip } = useTrip();
  const tripId = currentTrip?.id;
  const [view, setView] = useState<BookingView | null>(null);
  const [busy, setBusy] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [text, setText] = useState('');
  const [localError, setLocalError] = useState<string | null>(null);
  const preselect = useRef<string[]>(state?.services ?? []);
  const lastQuestion = useRef<string | undefined>(undefined);

  const show = useCallback((v: BookingView) => {
    setView(v);
    setLoadError(null);
    setLocalError(null);
    if (v.question !== lastQuestion.current) {
      lastQuestion.current = v.question;
      setText('');
      if (v.question === 'services') {
        const fromCard = preselect.current;
        preselect.current = [];
        setPicked(v.selected?.length ? v.selected : fromCard);
      }
    }
  }, []);

  const run = useCallback(async (fn: () => Promise<BookingView>) => {
    setBusy(true);
    try {
      show(await fn());
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Booking couldn't load. Please try again.");
    } finally {
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

  if (!tripId) {
    return (
      <div className="max-w-xl mx-auto px-4 pt-10 pb-28 text-center space-y-4">
        <p className="text-sm font-bold text-[var(--color-text-primary)]">Pehle trip kholiye.</p>
        <button type="button" onClick={() => navigate('/trips')} className="min-h-12 w-full rounded-2xl bg-[var(--color-primary)] text-white font-extrabold text-sm dark:text-zinc-950">My trips</button>
      </div>
    );
  }

  const answer = (value: string | string[]) => {
    if (!view?.question || busy) return;
    const q = view.question;
    void run(() => bookingApi.answer(tripId, q, value));
  };
  const submitText = () => {
    const value = text.trim();
    if (view?.kind === 'name' && !looksLikeName(value)) {
      setLocalError('Naam mein sirf akshar ho sakte hain, 2 se 60 tak.');
      return;
    }
    if (!value) return;
    answer(value);
  };
  const notNow = async () => {
    try { await bookingApi.cancel(tripId); } catch { /* the 2-hour expiry removes it anyway */ }
    navigate('/trip');
  };

  const big = 'min-h-12 w-full rounded-2xl border px-3 py-2 text-sm font-extrabold press-scale disabled:opacity-50';
  const choiceCls = `${big} border-[#355F58]/30 bg-[#E8F0EE] text-(--color-primary) dark:border-emerald-800 dark:bg-[#12332B]`;
  const primaryCls = `${big} border-transparent bg-[var(--color-primary)] text-white dark:text-zinc-950`;
  const inputCls = 'min-h-12 w-full rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] px-4 text-base text-[var(--color-text-primary)] dark:border-zinc-700';

  const finishedOrGone = view && !view.active;

  return (
    <div className="max-w-xl mx-auto px-4 pt-4 pb-28 space-y-5 animate-fadeIn">
      <div className="flex items-center justify-between gap-2">
        {view?.active && view.canBack ? (
          <button type="button" disabled={busy} onClick={() => void run(() => bookingApi.back(tripId))}
            className="flex min-h-11 items-center gap-1 px-1 text-sm font-bold text-[var(--color-primary)]">
            <ArrowLeft className="size-4" aria-hidden="true" />Back
          </button>
        ) : <span />}
        {view?.active && <span className="text-xs font-bold text-[var(--color-text-secondary)]">{view.progress?.label}</span>}
      </div>

      <p className="rounded-xl bg-amber-50 px-3 py-2 text-xs font-bold text-amber-800 dark:bg-amber-950/40 dark:text-amber-300">
        Test version: kuch bheja nahi jayega
      </p>

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
          <p className="text-base font-extrabold text-[var(--color-text-primary)]">
            {view.finished ? view.message : 'Booking band hai.'}
          </p>
          {!view.finished && (
            <button type="button" className={choiceCls} onClick={() => void run(() => bookingApi.start(tripId))}>Phir se shuru karein</button>
          )}
          <button type="button" className={primaryCls} onClick={() => navigate('/trip')}>Trip par wapas</button>
        </div>
      )}

      {view?.active && (
        <div className="space-y-4">
          <h1 className="text-lg font-extrabold text-[var(--color-text-primary)]">{view.prompt}</h1>
          {(view.error || localError) && (
            <p role="alert" className="text-sm font-bold text-red-700 dark:text-red-400">{localError || view.error}</p>
          )}

          {view.kind === 'services' && (
            <div className="space-y-2">
              {(view.choices || []).map((c) => {
                const on = picked.includes(c.value);
                return (
                  <button key={c.value} type="button" aria-pressed={on} onClick={() => setPicked((p) => toggleService(p, c.value))}
                    className={`${choiceCls} flex items-center justify-between ${on ? 'ring-2 ring-[var(--color-primary)]' : ''}`}>
                    <span>{c.label}</span>{on && <Check className="size-4" aria-hidden="true" />}
                  </button>
                );
              })}
              <button type="button" className={primaryCls} disabled={!picked.length || busy} onClick={() => answer(picked)}>Aage</button>
            </div>
          )}

          {(view.kind === 'choice' || view.kind === 'yesno' || view.kind === 'change') && (
            <div className="grid grid-cols-2 gap-2">
              {(view.choices || []).map((c) => (
                <button key={c.value} type="button" disabled={busy} className={choiceCls} onClick={() => answer(c.value)}>{c.label}</button>
              ))}
            </div>
          )}

          {view.question === 'flight_airline' && (
            <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (text.trim()) answer(text.trim()); }}>
              <input aria-label="Koi khaas airline" placeholder="Koi khaas airline" maxLength={40} value={text}
                onChange={(e) => setText(e.target.value)} className={inputCls} />
              <button type="submit" disabled={!text.trim() || busy} className={`${primaryCls} w-auto shrink-0 px-5`}>OK</button>
            </form>
          )}

          {(view.kind === 'name' || view.kind === 'age' || view.kind === 'phone') && (
            <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); submitText(); }}>
              {(view.choices || []).map((c) => (
                <button key={c.value} type="button" disabled={busy} className={choiceCls} onClick={() => answer(c.value)}>{c.label}</button>
              ))}
              <input
                aria-label={view.kind === 'name' ? 'Naam' : view.kind === 'age' ? 'Umar' : 'Mobile number'}
                placeholder={view.kind === 'name' ? 'Naam' : view.kind === 'age' ? 'Umar (saal)' : '10 digit mobile number'}
                inputMode={view.kind === 'name' ? 'text' : view.kind === 'age' ? 'numeric' : 'tel'}
                autoComplete={view.kind === 'phone' ? 'tel-national' : view.kind === 'name' ? 'name' : 'off'}
                maxLength={view.kind === 'name' ? NAME_MAX : undefined}
                value={text}
                onChange={(e) => {
                  const v = e.target.value;
                  setLocalError(null);
                  setText(view.kind === 'age' ? cleanAgeInput(v) : view.kind === 'phone' ? cleanPhoneInput(v) : v);
                }}
                className={inputCls}
              />
              <button type="submit" disabled={!text.trim() || busy} className={primaryCls}>Aage</button>
            </form>
          )}

          {view.kind === 'review' && (
            <div className="space-y-3">
              <ul className="space-y-2">
                {(view.summary || []).map((line) => (
                  <li key={line.part} className="flex items-start justify-between gap-3 rounded-2xl border border-[var(--color-border)] p-3 dark:border-zinc-700">
                    <div className="min-w-0">
                      <p className="text-xs font-extrabold text-[var(--color-text-secondary)]">{line.label}</p>
                      <p className="wrap-anywhere text-sm font-bold text-[var(--color-text-primary)]">{line.text}</p>
                    </div>
                    <button type="button" disabled={busy} onClick={() => answer(`change:${line.part}`)}
                      className="min-h-11 shrink-0 px-2 text-xs font-bold text-[var(--color-primary)] hover:underline">Badlein</button>
                  </li>
                ))}
              </ul>
              <p className="text-xs font-medium text-[var(--color-text-secondary)]">{view.consent}</p>
              <button type="button" disabled={busy} className={primaryCls} onClick={() => answer('yes')}>Haan, sahi hai</button>
            </div>
          )}

          <button type="button" onClick={() => void notNow()} className="min-h-11 w-full text-sm font-bold text-[var(--color-text-secondary)] hover:underline">
            Abhi nahi
          </button>
        </div>
      )}
    </div>
  );
};

export default BookingFlowPage;
