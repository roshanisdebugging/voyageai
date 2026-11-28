import React, { useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useTrip } from '../TripContext';
import { useAuth } from '../../../auth/AuthContext';
import type { DestinationReference, TripDraft } from '../types';
import type { TravelStyle } from '../../../auth/types';
import { PreferenceOption } from '../../../components/preferences/PreferenceOption';
import { PreferenceProgress } from '../../../components/preferences/PreferenceProgress';
import { PreferenceFooter } from '../../../components/preferences/PreferenceFooter';
import { PlaceSearchField } from '../components/PlaceSearchField';
import { cleanOriginName, ORIGIN_MAX_CHARS } from '../originName';
import { MapPin, Calendar, Sparkles, ArrowLeft, RefreshCw, AlertCircle, Wallet, Baby, User, Users } from 'lucide-react';
import { TripReviewChecklist } from './TripReviewChecklist';
import './trip-planner.css';
import { announceTripCreated, setReviewShowing, VOICE_SUBMIT_REVIEW } from '../../../voice/reviewState';

/**
 * Trip wizard: Where → When → Who → Style → Budget → Review.
 *
 * The review step shows every detail, all editable on the same page, with one
 * Proceed button. Other screens (and later the voice agent) can open the wizard
 * already filled in by navigating to /trips/new with `state: { prefill: TripDraft }`;
 * it then jumps straight to the review step.
 */

const TOTAL_STEPS = 6;
const REVIEW_STEP = 6;
const MAX_TRAVELERS = 20;

const POPULAR_DESTINATIONS: DestinationReference[] = [
  { id: 'dest_goa', name: 'Goa', city: 'North & South Goa', region: 'Goa', country: 'India', latitude: 15.5494, longitude: 73.7535, displayName: 'Goa, India' },
  { id: 'dest_kerala', name: 'Kerala', city: 'Munnar & Alleppey', region: 'Kerala', country: 'India', latitude: 9.9312, longitude: 76.2673, displayName: 'Kerala, India' },
  { id: 'dest_manali', name: 'Manali', city: 'Himachal Pradesh', region: 'Himachal Pradesh', country: 'India', latitude: 32.2432, longitude: 77.1892, displayName: 'Manali, Himachal Pradesh, India' },
  { id: 'dest_jaipur', name: 'Jaipur', city: 'Rajasthan', region: 'Rajasthan', country: 'India', latitude: 26.9124, longitude: 75.7873, displayName: 'Jaipur, Rajasthan, India' },
  { id: 'dest_udaipur', name: 'Udaipur', city: 'Rajasthan', region: 'Rajasthan', country: 'India', latitude: 24.5854, longitude: 73.7125, displayName: 'Udaipur, Rajasthan, India' },
  { id: 'dest_varanasi', name: 'Varanasi', city: 'Uttar Pradesh', region: 'Uttar Pradesh', country: 'India', latitude: 25.3176, longitude: 82.9739, displayName: 'Varanasi, Uttar Pradesh, India' },
];

const TRAVEL_STYLES: { id: TravelStyle; label: string }[] = [
  { id: 'RELAXED', label: 'Relaxed' },
  { id: 'ADVENTURE', label: 'Adventure' },
  { id: 'FOODIE', label: 'Foodie' },
  { id: 'CULTURE', label: 'Culture' },
  { id: 'NATURE', label: 'Nature' },
  { id: 'LUXURY', label: 'Luxury' },
];

const BUDGET_PRESETS = [15000, 30000, 60000, 120000];
const MIN_BUDGET = 1000;

const toDateString = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const getTodayDateString = () => toDateString(new Date());
const addDays = (dateStr: string, days: number) => {
  const base = new Date(`${dateStr}T00:00:00`);
  const valid = isNaN(base.getTime()) ? new Date() : base;
  valid.setDate(valid.getDate() + days);
  return toDateString(valid);
};
const tripDays = (start: string, end: string) => {
  const ms = new Date(`${end}T00:00:00`).getTime() - new Date(`${start}T00:00:00`).getTime();
  return Math.max(1, Math.round(ms / 86400000) + 1);
};
const formatInr = (n: number) => `₹${n.toLocaleString('en-IN')}`;
const reviewDateFormat = new Intl.DateTimeFormat('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
const formatReviewDate = (value: string) => {
  const date = new Date(`${value}T00:00:00`);
  return Number.isNaN(date.getTime()) ? 'Check date' : reviewDateFormat.format(date);
};

const Stepper: React.FC<{
  label: string;
  hint: string;
  icon: React.ReactNode;
  value: number;
  min: number;
  max: number;
  onChange: (v: number) => void;
}> = ({ label, hint, icon, value, min, max, onChange }) => (
  <div className="flex flex-wrap items-center justify-between gap-2 rounded-2xl border border-(--itinerary-border) bg-(--color-surface-elevated) p-3">
    <div className="flex items-center gap-2.5">
      {icon}
      <div>
        <div className="font-bold text-sm text-(--color-text-primary)">{label}</div>
        <div className="text-[11px] text-(--itinerary-muted)">{hint}</div>
      </div>
    </div>
    <div className="ml-auto flex items-center gap-1.5">
      <button
        type="button"
        aria-label={`Fewer ${label.toLowerCase()}`}
        onClick={() => onChange(Math.max(min, value - 1))}
        disabled={value <= min}
        className="grid size-11 place-items-center rounded-[14px] border border-(--itinerary-control-border) bg-(--color-surface) text-lg font-bold hover:border-(--itinerary-accent) disabled:opacity-40"
      >
        −
      </button>
      <span className="font-extrabold text-lg text-(--itinerary-accent) w-6 text-center tabular-nums">{value}</span>
      <button
        type="button"
        aria-label={`More ${label.toLowerCase()}`}
        onClick={() => onChange(Math.min(max, value + 1))}
        disabled={value >= max}
        className="grid size-11 place-items-center rounded-[14px] border border-(--itinerary-control-border) bg-(--color-surface) text-lg font-bold hover:border-(--itinerary-accent) disabled:opacity-40"
      >
        +
      </button>
    </div>
  </div>
);

export const TripCreationWizard: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { createTrip, draft, saveDraft, discardDraft, isLoading: isTripLoading } = useTrip();
  const { userPreferences } = useAuth();

  const prefill = (location.state as { prefill?: TripDraft } | null)?.prefill;
  const todayStr = getTodayDateString();

  const [step, setStep] = useState<number>(1);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const lastFocusedStep = useRef(step);

  useEffect(() => {
    if (lastFocusedStep.current === step) return;
    lastFocusedStep.current = step;
    window.scrollTo({ top: 0, behavior: 'instant' });
    headingRef.current?.focus({ preventScroll: true });
  }, [step]);
  const [showResumePrompt, setShowResumePrompt] = useState(false);
  const initializedRef = useRef(false);

  const [destination, setDestination] = useState<DestinationReference | null>(null);
  const [origin, setOrigin] = useState<DestinationReference | null>(null);
  const [startDate, setStartDate] = useState(todayStr);
  const [endDate, setEndDate] = useState(addDays(todayStr, 3));
  const [adults, setAdults] = useState(2);
  const [children, setChildren] = useState(0);
  const [styles, setStyles] = useState<TravelStyle[]>([]);
  const [budgetAmount, setBudgetAmount] = useState<number>(30000);
  // A checked plan accepted by voice; sent with the trip, the server keeps it only if it fits the destination.
  const [planCardId, setPlanCardId] = useState<string | undefined>(undefined);

  const [dateError, setDateError] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const applyDraft = (d: TripDraft) => {
    if (d.destination) setDestination(d.destination);
    if (d.origin !== undefined) setOrigin(d.origin || null);
    if (d.startDate && d.startDate >= todayStr) {
      setStartDate(d.startDate);
      setEndDate(d.endDate && d.endDate >= d.startDate ? d.endDate : addDays(d.startDate, 3));
    }
    if (d.adultsCount != null) setAdults(Math.max(1, d.adultsCount));
    else if (d.travelersCount != null) setAdults(Math.max(1, d.travelersCount));
    if (d.childrenCount != null) setChildren(Math.max(0, d.childrenCount));
    if (d.tripStyle) setStyles(d.tripStyle);
    if (d.customBudgetAmount) setBudgetAmount(d.customBudgetAmount);
    setPlanCardId(d.planCardId);
  };

  // First render: a prefill (e.g. from voice) wins, then an unfinished draft, then saved preferences.
  useEffect(() => {
    if (initializedRef.current) return;
    initializedRef.current = true;
    if (prefill) {
      applyDraft(prefill);
      setStep(REVIEW_STEP);
    } else if (draft?.destination) {
      setShowResumePrompt(true);
    } else if (userPreferences?.travelStyles?.length) {
      setStyles(userPreferences.travelStyles);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const currentDraft = (nextStep: number): TripDraft => ({
    destination: destination || undefined,
    origin,
    startDate,
    endDate,
    adultsCount: adults,
    childrenCount: children,
    travelersCount: adults + children,
    tripStyle: styles,
    customBudgetAmount: budgetAmount,
    planCardId,
    currentStep: nextStep,
  });

  const goToStep = (next: number) => {
    setStep(next);
    saveDraft(currentDraft(next));
  };

  const handleResumeDraft = () => {
    if (draft) {
      applyDraft(draft);
      if (draft.currentStep) setStep(Math.min(draft.currentStep, REVIEW_STEP));
    }
    setShowResumePrompt(false);
  };

  const handleStartFresh = () => {
    discardDraft();
    setDestination(null);
    setOrigin(null);
    setStartDate(todayStr);
    setEndDate(addDays(todayStr, 3));
    setAdults(2);
    setChildren(0);
    setStyles(userPreferences?.travelStyles || []);
    setBudgetAmount(30000);
    setPlanCardId(undefined);
    setStep(1);
    setShowResumePrompt(false);
  };

  const handleStartDateChange = (val: string) => {
    setDateError(null);
    if (val < todayStr) {
      setDateError('Trip start date cannot be in the past.');
      return;
    }
    setStartDate(val);
    if (endDate < val) setEndDate(addDays(val, 3));
  };

  const handleEndDateChange = (val: string) => {
    setDateError(null);
    if (val < startDate) {
      setDateError('Trip end date cannot be earlier than start date.');
      return;
    }
    setEndDate(val);
  };

  const days = tripDays(startDate, endDate);
  const nights = Math.max(0, days - 1);
  const totalTravelers = adults + children;
  const perPersonPerDay = Math.round(budgetAmount / Math.max(1, adults + 0.5 * children) / days);

  const validationProblem = (): string | null => {
    if (!destination) return 'Choose where you are going.';
    if (startDate < todayStr) return 'Trip start date cannot be in the past.';
    if (endDate < startDate) return 'Trip end date cannot be earlier than start date.';
    if (days > 30) return 'Trips can be at most 30 days long.';
    if (adults < 1) return 'At least one adult must travel.';
    if (totalTravelers > MAX_TRAVELERS) return `A trip can have at most ${MAX_TRAVELERS} travelers.`;
    if (!budgetAmount || budgetAmount < MIN_BUDGET) return `Enter a budget of at least ${formatInr(MIN_BUDGET)}.`;
    if (origin && !cleanOriginName(origin.name)) return `Starting city: choose a city name (letters only, at most ${ORIGIN_MAX_CHARS} characters), or clear it.`;
    return null;
  };

  const submittingRef = useRef(false);
  const handleProceed = async () => {
    if (submittingRef.current) return; // a second tap / voice confirm while saving does nothing
    const problem = validationProblem();
    if (problem || !destination) {
      setSubmitError(problem);
      return;
    }
    setSubmitError(null);
    submittingRef.current = true;
    try {
      await createTrip({
        destination,
        origin,
        startDate,
        endDate,
        adultsCount: adults,
        childrenCount: children,
        tripStyle: styles,
        budgetAmount,
        ...(planCardId ? { planCardId } : {}),
      });
      discardDraft();
      announceTripCreated(); // voice: the draft for this trip can go
      navigate('/trip/itinerary');
    } catch (err: any) {
      setSubmitError(err?.message || 'Could not create the trip. Please try again.');
    } finally {
      submittingRef.current = false;
    }
  };

  // Voice step 4: tell the mic button when the review step shows; "haan" / Confirm presses Proceed here,
  // so the values on this page (including edits made by tap) are what gets saved.
  const proceedRef = useRef(handleProceed);
  useEffect(() => { proceedRef.current = handleProceed; });
  useEffect(() => {
    setReviewShowing(step === REVIEW_STEP);
    return () => setReviewShowing(false);
  }, [step]);
  useEffect(() => {
    const onSubmit = () => { if (step === REVIEW_STEP) void proceedRef.current(); };
    window.addEventListener(VOICE_SUBMIT_REVIEW, onSubmit);
    return () => window.removeEventListener(VOICE_SUBMIT_REVIEW, onSubmit);
  }, [step]);

  // A new voice prefill while the wizard is already open (e.g. a corrected budget): apply it and show the review.
  const lastPrefillKeyRef = useRef(location.key);
  useEffect(() => {
    if (location.key === lastPrefillKeyRef.current) return;
    lastPrefillKeyRef.current = location.key;
    if (prefill) {
      applyDraft(prefill);
      setStep(REVIEW_STEP);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.key]);

  const toggleStyle = (id: TravelStyle) =>
    setStyles(prev => (prev.includes(id) ? prev.filter(s => s !== id) : [...prev, id]));

  const budgetInput = (
    <div className="space-y-3">
      <div className="relative flex items-center">
        <span className="absolute left-3.5 pointer-events-none font-extrabold text-(--itinerary-accent) text-lg">₹</span>
        <input
          id="trip-budget-amount"
          type="number"
          inputMode="numeric"
          aria-label="Total trip budget"
          min={MIN_BUDGET}
          step={1000}
          value={budgetAmount || ''}
          onChange={e => setBudgetAmount(Math.max(0, Number(e.target.value)))}
          className="min-h-12 w-full rounded-[14px] border border-(--itinerary-control-border) bg-(--color-surface) py-3 pl-8 pr-4 text-[15px] font-extrabold tabular-nums"
          placeholder="Total budget for the whole trip"
        />
      </div>
      <div className="flex flex-wrap gap-2">
        {BUDGET_PRESETS.map(amount => (
          <button
            key={amount}
            type="button"
            onClick={() => setBudgetAmount(amount)}
            aria-pressed={budgetAmount === amount}
            className={`min-h-11 rounded-[14px] border px-2.5 text-xs font-bold tabular-nums transition-colors ${
              budgetAmount === amount
                ? 'border-(--itinerary-accent) bg-(--itinerary-accent-surface) text-(--itinerary-accent)'
                : 'border-(--itinerary-control-border) bg-(--color-surface-elevated) text-(--itinerary-muted) hover:border-(--itinerary-accent)'
            }`}
          >
            {formatInr(amount)}
          </button>
        ))}
      </div>
      <p className="text-[11px] text-(--itinerary-muted)">
        About <span className="text-(--itinerary-accent) font-semibold">{formatInr(perPersonPerDay)}</span> per person per day
        {children > 0 && ' (children count as half)'}. Covers stays, food, travel and activities.
      </p>
    </div>
  );

  const datesEditor = (
    <div className="space-y-3">
      <div className="grid grid-cols-1 gap-3 min-[366px]:grid-cols-2 [&>div]:min-w-0">
        <div>
          <label htmlFor="trip-start-date" className="text-xs font-semibold text-(--itinerary-muted) block mb-1.5">Start date</label>
          <input
            id="trip-start-date"
            type="date"
            min={todayStr}
            value={startDate}
            onChange={e => handleStartDateChange(e.target.value)}
            className="min-h-12 w-full min-w-0 rounded-[14px] border border-(--itinerary-control-border) bg-(--color-surface) px-3 text-[15px] font-bold"
          />
        </div>
        <div>
          <label htmlFor="trip-end-date" className="text-xs font-semibold text-(--itinerary-muted) block mb-1.5">End date</label>
          <input
            id="trip-end-date"
            type="date"
            min={startDate || todayStr}
            value={endDate}
            onChange={e => handleEndDateChange(e.target.value)}
            className="min-h-12 w-full min-w-0 rounded-[14px] border border-(--itinerary-control-border) bg-(--color-surface) px-3 text-[15px] font-bold"
          />
        </div>
      </div>
      <div className="flex items-center gap-2 text-(--itinerary-accent) font-bold text-xs">
        <Calendar className="w-4 h-4" />
        <span>{days} day{days > 1 ? 's' : ''} · {nights} night{nights !== 1 ? 's' : ''}</span>
      </div>
      {dateError && (
        <div className="flex items-center gap-2 text-(--itinerary-error) text-xs font-semibold">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span>{dateError}</span>
        </div>
      )}
    </div>
  );

  const travelersEditor = (
    <div className="space-y-2.5">
      <Stepper
        label="Adults"
        hint="13 years and older"
        icon={<User className="w-5 h-5 text-(--itinerary-accent)" />}
        value={adults}
        min={1}
        max={MAX_TRAVELERS - children}
        onChange={setAdults}
      />
      <Stepper
        label="Children"
        hint="Under 13"
        icon={<Baby className="w-5 h-5 text-(--itinerary-accent)" />}
        value={children}
        min={0}
        max={MAX_TRAVELERS - adults}
        onChange={setChildren}
      />
    </div>
  );

  const stylesEditor = (
    <div className="grid grid-cols-2 gap-2.5">
      {TRAVEL_STYLES.map(item => (
        <PreferenceOption
          key={item.id}
          id={item.id}
          label={item.label}
          selected={styles.includes(item.id)}
          onSelect={id => toggleStyle(id as TravelStyle)}
          mode="multiple"
        />
      ))}
    </div>
  );

  return (
    <main className="trip-planner min-h-dvh bg-(--color-background) px-3.5 pt-3.5 pb-12 text-(--color-text-primary) sm:px-5 sm:pt-8">

      <div className="mx-auto w-full max-w-xl space-y-4 rounded-3xl border border-(--itinerary-border) bg-(--color-surface) p-4 sm:px-7 sm:py-6">

        {/* Header */}
        <header className="flex items-center gap-3 border-b border-(--itinerary-border) pb-4">
          <button
            type="button"
            aria-label="Back"
            onClick={() => (step > 1 && step !== REVIEW_STEP ? goToStep(step - 1) : navigate(-1))}
            className="grid size-11 shrink-0 place-items-center rounded-[14px] border border-(--itinerary-border) bg-(--color-surface-elevated) text-(--itinerary-muted) transition-colors hover:border-(--itinerary-accent)"
          >
            <ArrowLeft className="w-5 h-5" />
          </button>
          <span className="text-[15px] font-bold">
            {step === REVIEW_STEP ? 'Review your trip' : 'Trip Planner'}
          </span>
        </header>

        {/* Resume unfinished draft */}
        {showResumePrompt && (
          <div className="space-y-3 rounded-2xl border border-(--itinerary-accent) bg-(--color-surface-elevated) p-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-2xl bg-(--itinerary-accent-surface) text-(--itinerary-accent) flex items-center justify-center border border-(--itinerary-accent) shrink-0">
                <RefreshCw className="w-5 h-5" />
              </div>
              <div>
                <h3 className="text-sm font-bold text-(--color-text-primary)">Continue your trip plan?</h3>
                <p className="text-xs text-(--itinerary-muted)">
                  You have an unfinished plan for <span className="text-(--itinerary-accent) font-semibold">{draft?.destination?.name || 'a trip'}</span>.
                </p>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2.5 pt-1">
              <button type="button" onClick={handleResumeDraft} className="min-h-11 rounded-[14px] bg-(--color-primary) px-3 text-xs font-extrabold text-(--preference-on-accent) hover:brightness-95">
                Continue draft
              </button>
              <button type="button" onClick={handleStartFresh} className="min-h-11 rounded-[14px] border border-(--itinerary-control-border) bg-(--color-surface) px-3 text-xs font-extrabold hover:border-(--itinerary-accent)">
                Start fresh
              </button>
            </div>
          </div>
        )}

        <div>
          <PreferenceProgress currentStep={step} totalSteps={TOTAL_STEPS} />

          {/* STEP 1: WHERE */}
          {step === 1 && (
            <div className="mt-3 space-y-4 sm:space-y-[18px]">
              <div className="space-y-1">
                <h2 ref={headingRef} tabIndex={-1} className="text-[23px] font-extrabold leading-tight sm:text-[26px]">Where are you going?</h2>
                <p className="text-sm text-(--itinerary-muted)">Cruiser supports destinations within India.</p>
              </div>

              <PlaceSearchField
                id="trip-destination"
                label="Destination"
                placeholder="Search a city or region (e.g. Jaipur, Kerala)"
                value={destination}
                onChange={setDestination}
              />

              {!destination && (
                <div className="space-y-2">
                  <span className="text-xs font-semibold uppercase tracking-wider text-(--itinerary-muted)">Popular</span>
                  <div className="grid grid-cols-2 gap-2.5">
                    {POPULAR_DESTINATIONS.map(dest => (
                      <button
                        key={dest.id}
                        type="button"
                        onClick={() => setDestination(dest)}
                        className="flex min-w-0 items-start gap-2 rounded-[14px] border border-(--itinerary-border) bg-(--color-surface-elevated) p-2.5 text-left hover:border-(--itinerary-accent) sm:gap-3 sm:p-3.5"
                      >
                        <MapPin className="w-5 h-5 shrink-0 mt-0.5 text-(--itinerary-muted)" />
                        <div>
                          <div className="font-bold text-sm text-(--color-text-primary)">{dest.name}</div>
                          <div className="break-words text-xs text-(--itinerary-muted)">{dest.city}</div>
                        </div>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              <PlaceSearchField
                id="trip-origin"
                label="Starting city"
                placeholder="Your starting city (e.g. Delhi)"
                value={origin}
                onChange={setOrigin}
                optional
              />
              <p className="text-[11px] text-(--itinerary-muted) -mt-3">
                Add your starting city and we'll suggest trains, flights or buses that fit your budget.
              </p>

              <PreferenceFooter onContinue={() => goToStep(2)} disabled={!destination} />
            </div>
          )}

          {/* STEP 2: WHEN */}
          {step === 2 && (
            <div className="mt-3 space-y-4 sm:space-y-[18px]">
              <div className="space-y-1">
                <h2 ref={headingRef} tabIndex={-1} className="text-[23px] font-extrabold leading-tight sm:text-[26px]">When are you going?</h2>
                <p className="text-sm text-(--itinerary-muted)">
                  Dates for <span className="text-(--itinerary-accent) font-semibold">{destination?.name}</span>. Up to 30 days.
                </p>
              </div>
              <div className="rounded-2xl border border-(--itinerary-border) bg-(--color-surface-elevated) p-4">{datesEditor}</div>
              <PreferenceFooter
                onContinue={() => {
                  if (startDate < todayStr) return setDateError('Trip start date cannot be in the past.');
                  if (endDate < startDate) return setDateError('Trip end date cannot be earlier than start date.');
                  if (days > 30) return setDateError('Trips can be at most 30 days long.');
                  setDateError(null);
                  goToStep(3);
                }}
              />
            </div>
          )}

          {/* STEP 3: WHO */}
          {step === 3 && (
            <div className="mt-3 space-y-4 sm:space-y-[18px]">
              <div className="space-y-1">
                <h2 ref={headingRef} tabIndex={-1} className="text-[23px] font-extrabold leading-tight sm:text-[26px]">Who's coming?</h2>
                <p className="text-sm text-(--itinerary-muted)">Including you. Up to {MAX_TRAVELERS} people.</p>
              </div>
              {travelersEditor}
              <PreferenceFooter onContinue={() => goToStep(4)} />
            </div>
          )}

          {/* STEP 4: STYLE */}
          {step === 4 && (
            <div className="mt-3 space-y-4 sm:space-y-[18px]">
              <div className="space-y-1">
                <h2 ref={headingRef} tabIndex={-1} className="text-[23px] font-extrabold leading-tight sm:text-[26px]">What kind of trip is this?</h2>
                <p className="text-sm text-(--itinerary-muted)">Preselected from your profile. Change it for this trip if you like.</p>
              </div>
              {stylesEditor}
              <PreferenceFooter onContinue={() => goToStep(5)} />
            </div>
          )}

          {/* STEP 5: BUDGET */}
          {step === 5 && (
            <div className="mt-3 space-y-4 sm:space-y-[18px]">
              <div className="space-y-1">
                <h2 ref={headingRef} tabIndex={-1} className="text-[23px] font-extrabold leading-tight sm:text-[26px]">What's your budget?</h2>
                <p className="text-sm text-(--itinerary-muted)">The total for the whole group, for the whole trip.</p>
              </div>
              <div className="rounded-2xl border border-(--itinerary-border) bg-(--color-surface-elevated) p-4">{budgetInput}</div>
              <PreferenceFooter
                onContinue={() => goToStep(REVIEW_STEP)}
                disabled={!budgetAmount || budgetAmount < MIN_BUDGET}
              />
            </div>
          )}

          {/* STEP 6: REVIEW — everything editable, one Proceed button */}
          {step === REVIEW_STEP && (
            <div className="mt-3 space-y-4 sm:space-y-[18px]">
              <div className="space-y-1">
                <h2 ref={headingRef} tabIndex={-1} className="text-[23px] font-extrabold leading-tight sm:text-[26px]">Check your trip</h2>
                <p className="text-sm text-(--itinerary-muted)">Check the details, then tap Proceed.</p>
              </div>

              <TripReviewChecklist items={[
                {
                  id: 'places',
                  label: 'Places',
                  icon: MapPin,
                  value: destination?.name || 'Choose a destination',
                  detail: origin ? `From ${origin.name}` : 'Starting city optional',
                  editor: (
                    <div className="space-y-3">
                      <PlaceSearchField
                        id="review-destination"
                        label="Destination"
                        placeholder="Search a city or region"
                        value={destination}
                        onChange={setDestination}
                      />
                      <PlaceSearchField
                        id="review-origin"
                        label="Starting city"
                        placeholder="Your starting city"
                        value={origin}
                        onChange={setOrigin}
                        optional
                      />
                    </div>
                  ),
                },
                {
                  id: 'dates',
                  label: 'Dates',
                  icon: Calendar,
                  value: startDate === endDate
                    ? formatReviewDate(startDate)
                    : `${formatReviewDate(startDate)} – ${formatReviewDate(endDate)}`,
                  detail: `${days} day${days === 1 ? '' : 's'}`,
                  editor: datesEditor,
                },
                {
                  id: 'travelers',
                  label: 'Travelers',
                  icon: Users,
                  value: `${adults} adult${adults === 1 ? '' : 's'}` +
                    (children ? ` · ${children} ${children === 1 ? 'child' : 'children'}` : ''),
                  editor: travelersEditor,
                },
                {
                  id: 'budget',
                  label: 'Budget',
                  icon: Wallet,
                  value: budgetAmount ? formatInr(budgetAmount) : 'Enter a budget',
                  detail: 'Total for the group',
                  editor: budgetInput,
                },
                {
                  id: 'style',
                  label: 'Trip style',
                  icon: Sparkles,
                  value: TRAVEL_STYLES.filter(item => styles.includes(item.id)).map(item => item.label).join(' · ') || 'Any style',
                  editor: stylesEditor,
                },
              ]} />

              {!destination && (
                <p className="text-sm text-(--itinerary-muted)">Choose a destination to proceed.</p>
              )}

              {submitError && (
                <div role="alert" className="flex items-center gap-2 rounded-2xl border border-(--itinerary-error) bg-(--itinerary-error-surface) p-3 text-(--itinerary-error) text-xs font-semibold">
                  <AlertCircle className="w-4 h-4 shrink-0" />
                  <span>{submitError}</span>
                </div>
              )}

              <PreferenceFooter
                onContinue={handleProceed}
                continueText="Proceed"
                isLoading={isTripLoading}
                disabled={!destination}
              />
            </div>
          )}
        </div>

        <div className="text-center">
          <p className="text-[11px] text-(--itinerary-muted)">Nothing is saved until you tap Proceed.</p>
        </div>
      </div>
    </main>
  );
};
