import React, { useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useTrip } from '../TripContext';
import { useAuth } from '../../../auth/AuthContext';
import type { DestinationReference, TripDraft } from '../types';
import type { TravelStyle } from '../../../auth/types';
import { PreferenceOption } from '../../../components/preferences/PreferenceOption';
import { PreferenceProgress } from '../../../components/preferences/PreferenceProgress';
import { PreferenceFooter } from '../../../components/preferences/PreferenceFooter';
import { PlaceSearchField, placeSubtitle } from '../components/PlaceSearchField';
import { MapPin, Calendar, Sparkles, ArrowLeft, RefreshCw, AlertCircle, Wallet, Baby, User, Pencil } from 'lucide-react';

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

const Stepper: React.FC<{
  label: string;
  hint: string;
  icon: React.ReactNode;
  value: number;
  min: number;
  max: number;
  onChange: (v: number) => void;
}> = ({ label, hint, icon, value, min, max, onChange }) => (
  <div className="bg-slate-900/80 border border-slate-800 rounded-3xl p-4 flex items-center justify-between">
    <div className="flex items-center gap-3">
      {icon}
      <div>
        <div className="font-bold text-sm text-white">{label}</div>
        <div className="text-[11px] text-slate-400">{hint}</div>
      </div>
    </div>
    <div className="flex items-center gap-3">
      <button
        type="button"
        aria-label={`Fewer ${label.toLowerCase()}`}
        onClick={() => onChange(Math.max(min, value - 1))}
        disabled={value <= min}
        className="w-9 h-9 rounded-xl bg-slate-800 text-slate-200 font-bold hover:bg-slate-700 disabled:opacity-40 flex items-center justify-center text-lg"
      >
        −
      </button>
      <span className="font-extrabold text-lg text-teal-400 w-6 text-center">{value}</span>
      <button
        type="button"
        aria-label={`More ${label.toLowerCase()}`}
        onClick={() => onChange(Math.min(max, value + 1))}
        disabled={value >= max}
        className="w-9 h-9 rounded-xl bg-slate-800 text-slate-200 font-bold hover:bg-slate-700 disabled:opacity-40 flex items-center justify-center text-lg"
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
    return null;
  };

  const handleProceed = async () => {
    const problem = validationProblem();
    if (problem || !destination) {
      setSubmitError(problem);
      return;
    }
    setSubmitError(null);
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
      });
      discardDraft();
      navigate('/trip/itinerary');
    } catch (err: any) {
      setSubmitError(err?.message || 'Could not create the trip. Please try again.');
    }
  };

  const toggleStyle = (id: TravelStyle) =>
    setStyles(prev => (prev.includes(id) ? prev.filter(s => s !== id) : [...prev, id]));

  const budgetInput = (
    <div className="space-y-3">
      <div className="relative flex items-center">
        <span className="absolute left-3.5 font-extrabold text-teal-400 text-lg font-mono">₹</span>
        <input
          id="trip-budget-amount"
          type="number"
          inputMode="numeric"
          min={MIN_BUDGET}
          step={1000}
          value={budgetAmount || ''}
          onChange={e => setBudgetAmount(Math.max(0, Number(e.target.value)))}
          className="w-full bg-slate-950 border border-slate-700 focus:border-teal-500 rounded-2xl pl-8 pr-4 py-3 text-lg font-extrabold font-mono text-white outline-none"
          placeholder="Total budget for the whole trip"
        />
      </div>
      <div className="flex flex-wrap gap-2">
        {BUDGET_PRESETS.map(amount => (
          <button
            key={amount}
            type="button"
            onClick={() => setBudgetAmount(amount)}
            className={`px-3 py-1.5 rounded-xl border text-xs font-bold font-mono transition-all ${
              budgetAmount === amount
                ? 'bg-teal-500/15 border-teal-500 text-teal-300'
                : 'bg-slate-950 border-slate-800 text-slate-400 hover:bg-slate-800'
            }`}
          >
            {formatInr(amount)}
          </button>
        ))}
      </div>
      <p className="text-[11px] text-slate-400">
        About <span className="text-teal-300 font-semibold">{formatInr(perPersonPerDay)}</span> per person per day
        {children > 0 && ' (children count as half)'}. Covers stays, food, travel and activities.
      </p>
    </div>
  );

  const datesEditor = (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label htmlFor="trip-start-date" className="text-xs font-semibold text-slate-400 block mb-1.5">Start date</label>
          <input
            id="trip-start-date"
            type="date"
            min={todayStr}
            value={startDate}
            onChange={e => handleStartDateChange(e.target.value)}
            className="w-full bg-slate-950 border border-slate-800 rounded-2xl py-3 px-3 text-slate-100 font-bold text-sm focus:outline-none focus:border-teal-500"
          />
        </div>
        <div>
          <label htmlFor="trip-end-date" className="text-xs font-semibold text-slate-400 block mb-1.5">End date</label>
          <input
            id="trip-end-date"
            type="date"
            min={startDate || todayStr}
            value={endDate}
            onChange={e => handleEndDateChange(e.target.value)}
            className="w-full bg-slate-950 border border-slate-800 rounded-2xl py-3 px-3 text-slate-100 font-bold text-sm focus:outline-none focus:border-teal-500"
          />
        </div>
      </div>
      <div className="flex items-center gap-2 text-teal-400 font-bold text-xs">
        <Calendar className="w-4 h-4" />
        <span>{days} day{days > 1 ? 's' : ''} · {nights} night{nights !== 1 ? 's' : ''}</span>
      </div>
      {dateError && (
        <div className="flex items-center gap-2 text-rose-400 text-xs font-semibold">
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
        icon={<User className="w-5 h-5 text-teal-400" />}
        value={adults}
        min={1}
        max={MAX_TRAVELERS - children}
        onChange={setAdults}
      />
      <Stepper
        label="Children"
        hint="Under 13"
        icon={<Baby className="w-5 h-5 text-teal-400" />}
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

  const sectionCard = (title: string, icon: React.ReactNode, body: React.ReactNode) => (
    <section className="bg-slate-900/70 border border-slate-800 rounded-3xl p-4 space-y-3">
      <h3 className="flex items-center gap-2 text-xs font-extrabold uppercase tracking-wider text-slate-300">
        {icon}
        {title}
      </h3>
      {body}
    </section>
  );

  return (
    <div className="min-h-dvh w-full bg-[#05070E] text-slate-100 flex items-center justify-center p-0 sm:p-6 lg:p-8 relative overflow-x-hidden">
      <div className="fixed -top-40 -left-40 w-96 h-96 bg-teal-500/10 rounded-full blur-[120px] pointer-events-none" />
      <div className="fixed -bottom-40 -right-40 w-96 h-96 bg-emerald-500/10 rounded-full blur-[120px] pointer-events-none" />

      <div className="w-full max-w-md sm:max-w-xl bg-[#090D16]/90 sm:backdrop-blur-2xl sm:border sm:border-slate-800/80 sm:shadow-[0_20px_80px_rgba(0,0,0,0.8)] sm:rounded-[32px] p-6 sm:p-8 flex flex-col justify-between min-h-dvh sm:min-h-[820px] relative z-10 animate-fadeIn">

        {/* Header */}
        <div className="flex items-center justify-between pt-2 pb-2">
          <button
            type="button"
            aria-label="Back"
            onClick={() => (step > 1 && step !== REVIEW_STEP ? goToStep(step - 1) : navigate(-1))}
            className="p-2 rounded-full bg-slate-900 border border-slate-800 text-slate-400 hover:text-white transition-colors"
          >
            <ArrowLeft className="w-5 h-5" />
          </button>
          <div className="flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-teal-400" />
            <span className="text-xs font-semibold tracking-wider text-slate-400 uppercase">
              {step === REVIEW_STEP ? 'Review your trip' : 'Trip Planner'}
            </span>
          </div>
          <div className="w-9" />
        </div>

        {/* Resume unfinished draft */}
        {showResumePrompt && (
          <div className="bg-slate-900 border border-teal-500/40 rounded-3xl p-5 mb-4 space-y-3 shadow-xl animate-fadeIn">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-2xl bg-teal-500/20 text-teal-400 flex items-center justify-center border border-teal-500/30 shrink-0">
                <RefreshCw className="w-5 h-5" />
              </div>
              <div>
                <h3 className="text-sm font-bold text-white">Continue your trip plan?</h3>
                <p className="text-xs text-slate-400">
                  You have an unfinished plan for <span className="text-teal-300 font-semibold">{draft?.destination?.name || 'a trip'}</span>.
                </p>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2.5 pt-1">
              <button type="button" onClick={handleResumeDraft} className="py-3 px-3 bg-teal-500 hover:bg-teal-400 text-slate-950 font-extrabold text-xs rounded-xl">
                Continue draft
              </button>
              <button type="button" onClick={handleStartFresh} className="py-3 px-3 bg-slate-800 hover:bg-slate-700 text-slate-200 font-extrabold text-xs rounded-xl border border-slate-700">
                Start fresh
              </button>
            </div>
          </div>
        )}

        <div className="my-auto py-4 space-y-6">

          {/* STEP 1: WHERE */}
          {step === 1 && (
            <div className="space-y-6 animate-fadeIn">
              <PreferenceProgress currentStep={1} totalSteps={TOTAL_STEPS} />
              <div className="space-y-1">
                <h2 className="text-2xl font-bold text-white tracking-tight">Where are you going?</h2>
                <p className="text-sm text-slate-400">Cruiser supports destinations within India.</p>
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
                  <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">Popular</span>
                  <div className="grid grid-cols-2 gap-2.5">
                    {POPULAR_DESTINATIONS.map(dest => (
                      <button
                        key={dest.id}
                        type="button"
                        onClick={() => setDestination(dest)}
                        className="p-3.5 rounded-2xl border text-left flex items-start gap-3 bg-slate-900/70 border-slate-800 text-slate-300 hover:border-slate-700 active:scale-[0.98] transition-all"
                      >
                        <MapPin className="w-5 h-5 shrink-0 mt-0.5 text-slate-500" />
                        <div>
                          <div className="font-bold text-sm text-slate-100">{dest.name}</div>
                          <div className="text-[11px] text-slate-400">{dest.city}</div>
                        </div>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              <PlaceSearchField
                id="trip-origin"
                label="Starting from"
                placeholder="Your starting city (e.g. Delhi)"
                value={origin}
                onChange={setOrigin}
                optional
              />
              <p className="text-[11px] text-slate-500 -mt-3">
                Add your starting city and we'll suggest trains, flights or buses that fit your budget.
              </p>

              <PreferenceFooter onContinue={() => goToStep(2)} disabled={!destination} />
            </div>
          )}

          {/* STEP 2: WHEN */}
          {step === 2 && (
            <div className="space-y-6 animate-fadeIn">
              <PreferenceProgress currentStep={2} totalSteps={TOTAL_STEPS} />
              <div className="space-y-1">
                <h2 className="text-2xl font-bold text-white tracking-tight">When are you going?</h2>
                <p className="text-sm text-slate-400">
                  Dates for <span className="text-teal-300 font-semibold">{destination?.name}</span>. Up to 30 days.
                </p>
              </div>
              <div className="bg-slate-900/80 border border-slate-800 rounded-3xl p-5">{datesEditor}</div>
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
            <div className="space-y-6 animate-fadeIn">
              <PreferenceProgress currentStep={3} totalSteps={TOTAL_STEPS} />
              <div className="space-y-1">
                <h2 className="text-2xl font-bold text-white tracking-tight">Who's coming?</h2>
                <p className="text-sm text-slate-400">Including you. Up to {MAX_TRAVELERS} people.</p>
              </div>
              {travelersEditor}
              <PreferenceFooter onContinue={() => goToStep(4)} />
            </div>
          )}

          {/* STEP 4: STYLE */}
          {step === 4 && (
            <div className="space-y-6 animate-fadeIn">
              <PreferenceProgress currentStep={4} totalSteps={TOTAL_STEPS} />
              <div className="space-y-1">
                <h2 className="text-2xl font-bold text-white tracking-tight">What kind of trip is this?</h2>
                <p className="text-sm text-slate-400">Preselected from your profile. Change it for this trip if you like.</p>
              </div>
              {stylesEditor}
              <PreferenceFooter onContinue={() => goToStep(5)} />
            </div>
          )}

          {/* STEP 5: BUDGET */}
          {step === 5 && (
            <div className="space-y-6 animate-fadeIn">
              <PreferenceProgress currentStep={5} totalSteps={TOTAL_STEPS} />
              <div className="space-y-1">
                <h2 className="text-2xl font-bold text-white tracking-tight">What's your budget?</h2>
                <p className="text-sm text-slate-400">The total for the whole group, for the whole trip.</p>
              </div>
              <div className="bg-slate-900 border border-slate-800 p-5 rounded-3xl">{budgetInput}</div>
              <PreferenceFooter
                onContinue={() => goToStep(REVIEW_STEP)}
                disabled={!budgetAmount || budgetAmount < MIN_BUDGET}
              />
            </div>
          )}

          {/* STEP 6: REVIEW — everything editable, one Proceed button */}
          {step === REVIEW_STEP && (
            <div className="space-y-4 animate-fadeIn">
              <PreferenceProgress currentStep={6} totalSteps={TOTAL_STEPS} />
              <div className="space-y-1">
                <h2 className="text-2xl font-bold text-white tracking-tight">Check your trip</h2>
                <p className="text-sm text-slate-400 flex items-center gap-1.5">
                  <Pencil className="w-3.5 h-3.5" /> Change anything here, then tap Proceed.
                </p>
              </div>

              {sectionCard('Places', <MapPin className="w-4 h-4 text-teal-400" />, (
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
                    label="Starting from"
                    placeholder="Your starting city"
                    value={origin}
                    onChange={setOrigin}
                    optional
                  />
                </div>
              ))}

              {sectionCard('Dates', <Calendar className="w-4 h-4 text-teal-400" />, datesEditor)}
              {sectionCard('Travelers', <User className="w-4 h-4 text-teal-400" />, travelersEditor)}
              {sectionCard('Budget', <Wallet className="w-4 h-4 text-teal-400" />, budgetInput)}
              {sectionCard('Trip style', <Sparkles className="w-4 h-4 text-teal-400" />, stylesEditor)}

              <div className="rounded-3xl border border-teal-500/30 bg-slate-900/90 p-4 text-xs text-slate-300 space-y-1">
                <div className="font-extrabold text-sm text-white">
                  {destination?.name || 'No destination yet'}
                  {origin && <span className="text-slate-400 font-semibold"> · from {origin.name}</span>}
                </div>
                <div>{startDate} → {endDate} · {days} day{days > 1 ? 's' : ''}</div>
                <div>
                  {adults} adult{adults > 1 ? 's' : ''}{children > 0 && `, ${children} child${children > 1 ? 'ren' : ''}`}
                  {' · '}{budgetAmount ? formatInr(budgetAmount) : 'no budget'}
                </div>
                {destination && <div className="text-slate-500">{placeSubtitle(destination)}</div>}
              </div>

              {submitError && (
                <div role="alert" className="flex items-center gap-2 p-3 rounded-2xl bg-rose-950/60 border border-rose-800 text-rose-200 text-xs font-semibold">
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

        <div className="text-center pt-2 pb-4">
          <p className="text-[11px] text-slate-500">Nothing is saved until you tap Proceed.</p>
        </div>
      </div>
    </div>
  );
};
