import React, { useEffect, useId, useRef, useState } from 'react';
import { useApp } from '../../context/AppContext';
import { useTrip } from '../../features/trip/TripContext';
import { MapPin, Sparkles, Wallet, CloudRain, RefreshCw, Navigation, Car, Calendar, Download, Copy, Check, Printer, CheckCircle2, Circle, TrainFront, Plane, Bus } from 'lucide-react';
import { useLocation, useNavigate } from 'react-router-dom';
import { getApiBaseUrl, getAuthHeaders } from '../../config/apiConfig';
import { useToast } from '../common/UndoToast';
import { isPastTrip } from '../../features/trip/tripRepository';
import { ItineraryAiDialog } from './ItineraryAiDialog';
import { Trip3DFlyoverButton } from '../map/Trip3DFlyover';
import { TravelFromHere, TravelOriginBar } from './TravelLeg';
import { MAX_LEGS_PER_DAY } from '../map/mapLogic';

const aiActionClassName =
  'flex min-h-11 items-center gap-1.5 rounded-full border border-[#355F58]/30 bg-[#E8F0EE] px-3 py-1.5 text-xs font-bold text-(--color-primary) press-scale hover:bg-[#D4E4E0] max-sm:px-3.5 dark:border-emerald-800 dark:bg-[#12332B] dark:hover:bg-[#194437]';

export const ItineraryView: React.FC = () => {
  const navigate = useNavigate();
  const { openCabModal, openInAppNavigation, openSwapAssistant } = useApp();
  const { currentTrip, currentItinerary, optimizeDayItinerary, optimizeBudget, weatherReplan, setActivityDone, transports, trips, isLoading: isTripsLoading } = useTrip();
  const { showToast } = useToast();
  const [doneBusyId, setDoneBusyId] = useState<string | null>(null);

  // ?day=N (voice: "day 2 dikhao") selects that day, on load and whenever the URL changes.
  const { search } = useLocation();
  const dayFromUrl = (() => {
    const day = Number(new URLSearchParams(search).get('day'));
    return Number.isInteger(day) && day >= 1 && day <= 30 ? day : null;
  })();
  const [expandedDayNumber, setExpandedDayNumber] = useState<number>(dayFromUrl ?? 1);
  const [appliedSearch, setAppliedSearch] = useState(search);
  if (search !== appliedSearch) {
    setAppliedSearch(search);
    if (dayFromUrl !== null) setExpandedDayNumber(dayFromUrl);
  }
  const [isOptimizing, setIsOptimizing] = useState<boolean>(false);
  const [optStatusMessage, setOptStatusMessage] = useState<string | null>(null);

  // Custom UI Modals for Budget AI and Weather AI (Replaces raw browser alerts)
  const [budgetAnalysisModal, setBudgetAnalysisModal] = useState<{
    isOpen: boolean;
    data: {
      projectedCost: number;
      targetBudget: number;
      savingsRequired: number;
      recommendations: any[];
    } | null;
  }>({ isOpen: false, data: null });

  const [weatherReplanModal, setWeatherReplanModal] = useState<{
    isOpen: boolean;
    data: {
      forecast: any;
      affectedActivities: any[];
      recommendations: any[];
      message?: string;
    } | null;
  }>({ isOpen: false, data: null });

  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [showExportDropdown, setShowExportDropdown] = useState<boolean>(false);
  const [copyToast, setCopyToast] = useState<boolean>(false);
  const [isExportingJson, setIsExportingJson] = useState<boolean>(false);
  const exportId = useId();
  const exportControl = useRef<HTMLDivElement>(null);
  const exportButton = useRef<HTMLButtonElement>(null);
  const aiTrigger = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (!showExportDropdown) return;
    const closeOnOutsidePress = (event: PointerEvent) => {
      if (event.target instanceof Node && !exportControl.current?.contains(event.target)) {
        setShowExportDropdown(false);
      }
    };
    document.addEventListener('pointerdown', closeOnOutsidePress);
    return () => document.removeEventListener('pointerdown', closeOnOutsidePress);
  }, [showExportDropdown]);

  const days = currentItinerary?.days || [];
  const selectedDay = days.find(d => d.dayNumber === expandedDayNumber) || days[0];

  const handleOptimizeCurrentDay = async () => {
    if (!currentTrip?.id || !selectedDay?.id) return;
    setIsOptimizing(true);
    setOptStatusMessage("Calculating shortest transit route & optimizing day flow...");
    try {
      const res = await optimizeDayItinerary(currentTrip.id, selectedDay.id, "MINIMIZE_TRAVEL_TIME");
      setOptStatusMessage(res.message || "Day flow optimized!");
      setTimeout(() => setOptStatusMessage(null), 4000);
    } catch (err: any) {
      setErrorMessage(err.message || "Failed to optimize day flow");
      setOptStatusMessage(null);
    } finally {
      setIsOptimizing(false);
    }
  };

  const handleRunBudgetOptimization = async (event: React.MouseEvent<HTMLButtonElement>) => {
    if (!currentTrip?.id) return;
    aiTrigger.current = event.currentTarget;
    setIsOptimizing(true);
    setOptStatusMessage("Analyzing expenses against budget...");
    try {
      const res = await optimizeBudget(currentTrip.id);
      setBudgetAnalysisModal({
        isOpen: true,
        data: {
          projectedCost: res.projectedCost || 0,
          targetBudget: res.targetBudget ?? currentTrip?.budget?.targetAmount ?? 0,
          savingsRequired: res.savingsRequired || 0,
          recommendations: res.recommendations || []
        }
      });
      setOptStatusMessage(null);
    } catch (err: any) {
      setErrorMessage(err.message || "Failed to run budget optimization");
      setOptStatusMessage(null);
    } finally {
      setIsOptimizing(false);
    }
  };

  const handleRunWeatherReplan = async (event: React.MouseEvent<HTMLButtonElement>) => {
    if (!currentTrip?.id) return;
    aiTrigger.current = event.currentTarget;
    setIsOptimizing(true);
    setOptStatusMessage("Checking weather forecasts & outdoor activities...");
    try {
      const res = await weatherReplan(currentTrip.id);
      setWeatherReplanModal({
        isOpen: true,
        data: {
          forecast: res.forecast || res.weatherAlert || {},
          affectedActivities: res.affectedActivities || res.recommendations || [],
          recommendations: res.recommendations || [],
          message: res.message || res.forecast?.summary || res.weatherAlert?.summary
        }
      });
      setOptStatusMessage(null);
    } catch (err: any) {
      setErrorMessage(err.message || "Failed to run weather replan");
      setOptStatusMessage(null);
    } finally {
      setIsOptimizing(false);
    }
  };

  const handleToggleDone = async (activityId: string, title: string, currentlyDone: boolean) => {
    if (!currentTrip?.id || doneBusyId) return;
    const tripId = currentTrip.id;
    const nextDone = !currentlyDone;
    setDoneBusyId(activityId);
    try {
      await setActivityDone(tripId, activityId, nextDone);
      showToast({
        message: nextDone ? `Marked "${title}" as done` : `"${title}" marked not done`,
        undo: () => setActivityDone(tripId, activityId, currentlyDone),
      });
    } catch (err: any) {
      showToast({ message: err?.message || "Couldn't update the activity. Please try again.", tone: 'error' });
    } finally {
      setDoneBusyId(null);
    }
  };

  // Real count only: adults + children, else the travellers list; 0 = unknown (not shown).
  const travellerCount = ((currentTrip?.adultsCount ?? 0) + (currentTrip?.childrenCount ?? 0)) || currentTrip?.travelers?.length || 0;
  const recommendedTransport = transports.filter(t => t.status === 'RECOMMENDED');
  const transportIcon = (type: string) =>
    type === 'FLIGHT' ? <Plane className="w-4 h-4" /> : type === 'BUS' ? <Bus className="w-4 h-4" /> : type === 'TRAIN' ? <TrainFront className="w-4 h-4" /> : <Car className="w-4 h-4" />;

  const destName = currentTrip?.destination?.name || 'Trip Destination';

  const handleDownloadPdfOrPrint = () => {
    setShowExportDropdown(false);
    if (!currentTrip?.id) return;
    const baseUrl = getApiBaseUrl();
    const url = `${baseUrl}/api/trips/${currentTrip.id}/export?format=html&autoprint=true`;
    window.open(url, '_blank');
  };

  const handleCopyShareableSummary = () => {
    setShowExportDropdown(false);
    if (!currentTrip) return;
    let text = `✈️ ${currentTrip.title || `${destName} Tour Package`}\n`;
    text += `📍 Destination: ${destName}\n`;
    text += `📅 Dates: ${currentTrip.startDate} to ${currentTrip.endDate}\n`;
    if (travellerCount > 0) text += `👥 Travelers: ${travellerCount}\n\n`;

    days.forEach(d => {
      text += `🗓️ Day ${d.dayNumber}: ${d.title || ''}\n`;
      if (d.summary) text += `   ${d.summary}\n`;
      (d.activities || []).forEach(a => {
        const cost = a.estimatedCostInr ? ` (₹${a.estimatedCostInr})` : '';
        const conf = a.isConfirmed ? ' [✓ Confirmed]' : '';
        text += `   • ${a.timeSlot || 'Anytime'}: ${a.title} @ ${a.locationName || 'Local'}${cost}${conf}\n`;
      });
      text += '\n';
    });
    text += `\nGenerated with Cruiser Concierge`;

    if (navigator.clipboard) {
      navigator.clipboard.writeText(text).then(() => {
        setCopyToast(true);
        setTimeout(() => setCopyToast(false), 3000);
      }).catch(err => {
        console.error("Failed to copy itinerary:", err);
      });
    }
  };

  const handleExportJson = async () => {
    setShowExportDropdown(false);
    if (!currentTrip?.id) return;
    setIsExportingJson(true);
    try {
      const baseUrl = getApiBaseUrl();
      const res = await fetch(`${baseUrl}/api/trips/${currentTrip.id}/export?format=json`, {
        credentials: 'include',
        headers: getAuthHeaders(),
      });
      if (!res.ok) throw new Error("Failed to export JSON");
      const data = await res.json();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const blobUrl = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = blobUrl;
      const fileSlug = (destName || 'itinerary').toLowerCase().replace(/\s+/g, '-');
      a.download = `trip-${fileSlug}-itinerary.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(blobUrl);
    } catch (err: any) {
      setErrorMessage(err.message || "Failed to download itinerary JSON");
    } finally {
      setIsExportingJson(false);
    }
  };

  // No ongoing or upcoming trip: past trips never open by themselves.
  if (!currentTrip) {
    if (isTripsLoading) {
      return (
        <div className="max-w-xl mx-auto py-16 flex items-center justify-center text-[var(--color-text-secondary)] text-sm font-medium gap-2">
          <RefreshCw className="w-4 h-4 animate-spin text-[var(--color-primary)]" />
          <span>Loading your trips…</span>
        </div>
      );
    }
    const pastCount = trips.filter(t => isPastTrip(t)).length;
    return (
      <div className="max-w-xl mx-auto pt-10 pb-28 animate-fadeIn">
        <div className="bg-[var(--color-surface)] border border-[var(--color-border)] dark:border-zinc-700 rounded-3xl p-8 text-center space-y-4 shadow-xs">
          <div className="w-14 h-14 rounded-2xl bg-[#E8F0EE] dark:bg-[#12332B] text-[var(--color-primary)] flex items-center justify-center mx-auto">
            <Calendar className="w-7 h-7" />
          </div>
          <div className="space-y-1">
            <h1 className="text-lg font-extrabold text-[var(--color-text-primary)]">No current trip</h1>
            <p className="text-xs text-[var(--color-text-secondary)] font-medium max-w-xs mx-auto">
              You have no ongoing or upcoming trips. Plan your next one and we'll build the itinerary for you.
            </p>
          </div>
          <button
            type="button"
            onClick={() => navigate('/trips/new')}
            className="w-full py-3.5 rounded-2xl bg-[var(--color-primary)] hover:bg-[#2C504A] dark:hover:bg-[var(--color-primary-light)] text-white dark:text-zinc-950 font-extrabold text-sm press-scale shadow-xs min-h-[48px]"
          >
            Plan a trip
          </button>
          <button
            type="button"
            onClick={() => navigate('/trips', { state: { tab: 'PAST' } })}
            className="text-xs font-bold text-[var(--color-primary)] hover:underline"
          >
            Past trips{pastCount > 0 ? ` (${pastCount})` : ''}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="[&_button:focus-visible]:outline-2 [&_button:focus-visible]:outline-offset-2 [&_button:focus-visible]:outline-[var(--color-primary)] space-y-5 pb-28 w-full max-w-xl mx-auto animate-fadeIn">
      {/* Top Header Bar */}
      <div className="relative flex flex-wrap items-center justify-between gap-x-3 gap-y-2 border-b border-[var(--color-border)] dark:border-zinc-700 pb-3">
        <p className="min-w-0 wrap-anywhere text-sm font-bold text-[var(--color-text-primary)]">
          {destName}<span className="font-normal text-[var(--color-text-secondary)]"> · Itinerary</span>
        </p>

        <div className="flex min-w-0 flex-wrap items-center gap-2 max-sm:w-full">
          {/* Export Itinerary Dropdown */}
          <div
            ref={exportControl}
            className="sm:relative"
            onBlur={event => {
              if (event.relatedTarget && !event.currentTarget.contains(event.relatedTarget)) {
                setShowExportDropdown(false);
              }
            }}
            onKeyDown={event => {
              if (event.key === 'Escape' && showExportDropdown) {
                event.stopPropagation();
                exportButton.current?.focus();
                setShowExportDropdown(false);
              }
            }}
          >
            <button
              ref={exportButton}
              type="button"
              onClick={() => setShowExportDropdown(open => !open)}
              disabled={isExportingJson}
              className="flex min-h-11 items-center gap-1.5 rounded-full border border-(--color-border) bg-(--color-surface) px-3 py-1.5 text-xs font-bold text-(--color-text-primary) shadow-xs press-scale hover:bg-(--color-surface-elevated) max-sm:px-3.5 dark:border-zinc-700"
              title="Export Itinerary"
              aria-expanded={showExportDropdown}
              aria-controls={showExportDropdown ? exportId : undefined}
            >
              <Download className="size-3.5 shrink-0 text-(--color-primary)" aria-hidden="true" />
              <span>Export</span>
            </button>

            {showExportDropdown && (
              <div
                id={exportId}
                className="absolute left-0 top-full z-50 mt-2 max-h-[max(5rem,calc(100dvh-13rem))] w-64 max-w-full space-y-1 overflow-y-auto overscroll-contain rounded-2xl border border-(--color-border) bg-(--color-surface) p-2 text-left shadow-xl animate-fadeIn sm:max-w-none min-[480px]:max-sm:[@media(max-height:420px)]:inset-[0_0_auto_auto] min-[480px]:max-sm:[@media(max-height:420px)]:mt-0 min-[480px]:max-sm:[@media(max-height:420px)]:max-h-[max(5rem,calc(100dvh-9.25rem))] [@media(max-height:420px)]:space-y-0 [@media(max-height:420px)]:py-1 [@media(max-height:420px)]:[&>button]:min-h-11 [@media(max-height:420px)]:[&>button]:py-1 dark:border-zinc-700 [&_button:focus-visible]:-outline-offset-2"
              >
                <div className="px-3 py-1.5 text-[10px] font-extrabold text-[var(--color-text-secondary)] uppercase tracking-wider border-b border-[var(--color-border)]">
                  Export Itinerary
                </div>

                <button
                  type="button"
                  onClick={handleDownloadPdfOrPrint}
                  className="w-full px-3 py-2.5 rounded-xl hover:bg-[var(--color-surface-elevated)] text-[var(--color-text-primary)] text-xs font-bold flex items-center gap-2.5 transition-colors text-left"
                >
                  <div className="w-7 h-7 rounded-lg bg-[#E8F0EE] dark:bg-[#12332B] text-[var(--color-primary)] flex items-center justify-center shrink-0">
                    <Printer className="w-4 h-4" />
                  </div>
                  <div className="min-w-0 wrap-anywhere">
                    <div className="font-extrabold">Download PDF / Print</div>
                    <div className="text-[10px] text-[var(--color-text-secondary)] font-normal">Print-optimized layout</div>
                  </div>
                </button>

                <button
                  type="button"
                  onClick={handleCopyShareableSummary}
                  className="w-full px-3 py-2.5 rounded-xl hover:bg-[var(--color-surface-elevated)] text-[var(--color-text-primary)] text-xs font-bold flex items-center gap-2.5 transition-colors text-left"
                >
                  <div className="w-7 h-7 rounded-lg bg-[#E8F0EE] dark:bg-[#12332B] text-[var(--color-primary)] flex items-center justify-center shrink-0">
                    <Copy className="w-4 h-4" />
                  </div>
                  <div className="min-w-0 wrap-anywhere">
                    <div className="font-extrabold">Copy Shareable Summary</div>
                    <div className="text-[10px] text-[var(--color-text-secondary)] font-normal">Formatted text to clipboard</div>
                  </div>
                </button>

                <button
                  type="button"
                  onClick={handleExportJson}
                  className="w-full px-3 py-2.5 rounded-xl hover:bg-[var(--color-surface-elevated)] text-[var(--color-text-primary)] text-xs font-bold flex items-center gap-2.5 transition-colors text-left"
                >
                  <div className="w-7 h-7 rounded-lg bg-[#E8F0EE] dark:bg-[#12332B] text-[var(--color-primary)] flex items-center justify-center shrink-0">
                    <Download className="w-4 h-4" />
                  </div>
                  <div className="min-w-0 wrap-anywhere">
                    <div className="font-extrabold">Export JSON</div>
                    <div className="text-[10px] text-[var(--color-text-secondary)] font-normal">Raw itinerary data</div>
                  </div>
                </button>
              </div>
            )}
          </div>

          <button
            type="button"
            onClick={handleRunBudgetOptimization}
            disabled={isOptimizing}
            className={aiActionClassName}
          >
            <Wallet className="size-3.5 shrink-0" aria-hidden="true" />
            <span>Budget AI</span>
          </button>
          <button
            type="button"
            onClick={handleRunWeatherReplan}
            disabled={isOptimizing}
            className={aiActionClassName}
          >
            <CloudRain className="size-3.5 shrink-0" aria-hidden="true" />
            <span>Weather AI</span>
          </button>
        </div>
      </div>

      {/* Main Trip Banner */}
      <div className="bg-[var(--color-surface)] border border-[var(--color-border)] dark:border-zinc-700 rounded-3xl p-5 space-y-2 shadow-xs">
        <div className="flex items-center justify-between">
          <span className="px-3 py-1 rounded-full bg-[#E8F0EE] dark:bg-[#12332B] text-[var(--color-primary)] font-extrabold text-xs border border-[#355F58]/30 dark:border-emerald-800">
            {destName}
          </span>
          <span className="text-xs text-[var(--color-text-secondary)] font-bold flex items-center gap-1">
            <Calendar className="w-3.5 h-3.5 text-[var(--color-primary)]" />
            {currentTrip?.startDate} to {currentTrip?.endDate}
          </span>
        </div>
        <h1 className="text-xl sm:text-2xl font-black text-[var(--color-text-primary)]">
          {currentTrip?.title || `${destName} Tour Package`}
        </h1>
        <p className="text-xs text-[var(--color-text-secondary)] font-medium">
          {days.length} Days Detailed AI Itinerary{travellerCount > 0 ? ` · ${travellerCount} Travelers` : ''}
        </p>
        {/* Optional, VITE_MAP_3D=true only */}
        <Trip3DFlyoverButton />
      </div>

      {recommendedTransport.length > 0 && (
        <div className="bg-[var(--color-surface)] border border-[var(--color-border)] dark:border-zinc-700 rounded-3xl p-4 space-y-2.5 shadow-xs">
          <h2 className="text-xs font-extrabold uppercase tracking-wider text-[var(--color-primary)]">
            Getting there{currentTrip?.origin?.name ? ` from ${currentTrip.origin.name}` : ''}
          </h2>
          {recommendedTransport.map(t => (
            <div key={t.id} className="flex items-start gap-3 p-3 rounded-2xl bg-[var(--color-surface-elevated)] border border-[var(--color-border)] dark:border-zinc-700">
              <div className="w-8 h-8 rounded-xl bg-[#E8F0EE] dark:bg-[#12332B] text-[var(--color-primary)] flex items-center justify-center shrink-0">
                {transportIcon(t.transportType)}
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-xs font-extrabold text-[var(--color-text-primary)]">{t.providerName}</div>
                <div className="text-[11px] text-[var(--color-text-secondary)]">{t.pickupLocation} → {t.dropoffLocation}</div>
                {t.bookingReference && <div className="text-[11px] text-[var(--color-text-secondary)]">{t.bookingReference}</div>}
              </div>
              {t.estimatedFare > 0 && (
                <span className="text-xs font-bold text-[var(--color-primary)] shrink-0" title="Estimated one-way fare for the whole group">
                  ~₹{t.estimatedFare.toLocaleString('en-IN')}
                </span>
              )}
            </div>
          ))}
          <p className="text-[10px] text-[var(--color-text-secondary)]">Suggested by AI to fit your budget. Fares are estimates for the whole group, one way.</p>
        </div>
      )}

      {optStatusMessage && (
        <div className="p-3.5 rounded-2xl bg-(--itinerary-accent-surface) border border-(--itinerary-border) text-xs font-bold text-(--itinerary-accent) flex items-center gap-2 animate-fadeIn shadow-xs">
          <RefreshCw className="w-4 h-4 animate-spin shrink-0 text-(--itinerary-accent)" />
          <span>{optStatusMessage}</span>
        </div>
      )}

      {/* If Generating or Empty */}
      {(!days || days.length === 0) ? (
        <div className="bg-(--color-surface) border border-(--itinerary-border) rounded-3xl p-8 text-center space-y-3 shadow-xs">
          <RefreshCw className="w-8 h-8 text-(--itinerary-accent) animate-spin mx-auto" />
          <h2 className="text-lg font-extrabold text-[var(--color-text-primary)]">Generating AI Itinerary...</h2>
          <p className="text-xs text-[var(--color-text-secondary)] font-medium">
            Building day-by-day activities, places, and recommendations for {destName}. This usually takes a few seconds.
          </p>
        </div>
      ) : (
        <>
          {/* Day Pills Selector */}
          <div className="flex gap-2 overflow-x-auto no-scrollbar pb-1">
            {days.map(day => (
              <button
                key={day.id || day.dayNumber}
                type="button"
                onClick={() => setExpandedDayNumber(day.dayNumber)}
                aria-pressed={selectedDay?.dayNumber === day.dayNumber}
                className={`press-scale shrink-0 px-4 py-2.5 rounded-2xl text-xs font-extrabold transition-all border ${
                  selectedDay?.dayNumber === day.dayNumber
                    ? 'bg-[var(--color-primary)] text-white dark:text-zinc-950 border-[var(--color-primary)] shadow-xs'
                    : 'bg-[var(--color-surface-elevated)] text-[var(--color-text-primary)] border-[var(--color-border)] dark:border-zinc-700 hover:border-[var(--color-primary)]'
                }`}
              >
                Day {day.dayNumber}
              </button>
            ))}
          </div>

          {/* Connected Day Timeline */}
          {selectedDay && (
            <div key={selectedDay.id || selectedDay.dayNumber} className="space-y-4">
              <div className="p-4 rounded-2xl bg-[var(--color-surface)] border border-[var(--color-border)] dark:border-zinc-700 flex items-center justify-between shadow-xs">
                <div>
                  <h2 className="text-base font-extrabold text-[var(--color-text-primary)]">{selectedDay.title}</h2>
                  <p className="text-xs text-[var(--color-text-secondary)] font-medium mt-0.5">{selectedDay.date || `Day ${selectedDay.dayNumber}`}</p>
                </div>
                <span className="px-3 py-1 rounded-full bg-[#E8F0EE] dark:bg-[#12332B] text-[var(--color-primary)] font-bold text-xs border border-[#355F58]/30 dark:border-emerald-800">
                  {selectedDay.activities.length} Activities
                </span>
              </div>

              <div className="space-y-3">
                <TravelOriginBar />
                {selectedDay.activities.map((act, idx) => {
                  const isDone = Boolean(act.isDone);
                  // Google route only for the first MAX_LEGS_PER_DAY activities with coordinates; the rest straight-line
                  const coordRank = selectedDay.activities.slice(0, idx).filter((a) => a.latitude != null && a.longitude != null).length;
                  return (
                    <React.Fragment key={act.id}>
                    <div
                      className="bg-[var(--color-surface)] border border-[var(--color-border)] dark:border-zinc-700 rounded-2xl p-4 space-y-3 shadow-xs hover:border-[var(--color-primary)] transition-all"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0 flex-1 space-y-1.5">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-[10px] uppercase font-bold text-[var(--color-primary)] tracking-wider px-2 py-0.5 rounded-md bg-[#E8F0EE] dark:bg-[#12332B] border border-[#355F58]/20 dark:border-emerald-800">
                              Activity {idx + 1} · {act?.timeSlot ?? 'Flexible'}
                            </span>
                            {act.isConfirmed && (
                              <span className="inline-flex items-center gap-1 text-[10px] font-bold text-emerald-700 dark:text-emerald-300 bg-emerald-50 dark:bg-emerald-950 border border-emerald-200/80 dark:border-emerald-800 px-2 py-0.5 rounded-md">
                                <Check className="w-3 h-3 stroke-[2.5]" /> Confirmed
                              </span>
                            )}
                          </div>

                          <h3 className={`text-base font-extrabold leading-snug break-words ${isDone ? 'text-[var(--color-text-secondary)] line-through' : 'text-[var(--color-text-primary)]'}`}>
                            {act.title}
                          </h3>

                          <p className="text-xs text-[var(--color-text-secondary)] flex items-center gap-1 font-medium pt-0.5">
                            <MapPin className="w-3.5 h-3.5 text-[var(--color-primary)] shrink-0" />
                            <span className="truncate">{act.locationName || destName}</span>
                          </p>
                          {/* Travel time from the device's current location (never from the previous activity) */}
                          <TravelFromHere dest={act} routeAllowed={coordRank < MAX_LEGS_PER_DAY} />
                        </div>

                        {act.estimatedCostInr != null && (
                          <span className="text-xs font-bold text-[var(--color-primary)] bg-[#E8F0EE] dark:bg-[#12332B] px-2.5 py-1 rounded-full border border-[var(--color-border)] dark:border-zinc-700 shrink-0 self-start">
                            ₹{act.estimatedCostInr}
                          </span>
                        )}
                      </div>

                      {act.description && (
                        <p className="text-xs text-[var(--color-text-secondary)] leading-relaxed font-medium">{act.description}</p>
                      )}

                      {/* Action Buttons */}
                      <div className="flex flex-wrap items-center gap-2 pt-2 border-t border-[var(--color-border)] dark:border-zinc-700">
                        <button
                          type="button"
                          onClick={() => handleToggleDone(act.id, act.title, isDone)}
                          disabled={doneBusyId === act.id}
                          aria-pressed={isDone}
                          aria-label={isDone ? `Mark ${act.title} as not done` : `Mark ${act.title} as done`}
                          className={`py-2 px-3 rounded-xl border text-xs font-bold flex items-center justify-center gap-1.5 press-scale transition-all min-h-[40px] disabled:opacity-50 ${
                            isDone ? 'bg-emerald-50 dark:bg-emerald-950 border-emerald-200 dark:border-emerald-800 text-emerald-700 dark:text-emerald-300' : 'bg-[var(--color-surface)] border-[var(--color-border)] dark:border-zinc-700 text-[var(--color-text-primary)] hover:bg-[var(--color-surface-elevated)]'
                          }`}
                        >
                          {isDone ? <CheckCircle2 className="w-4 h-4" /> : <Circle className="w-4 h-4 text-[var(--color-primary)]" />}
                          <span>{isDone ? 'Done' : 'Mark done'}</span>
                        </button>
                        <button
                          type="button"
                          disabled={!act.latitude || !act.longitude}
                          onClick={() => {
                            if (act.latitude && act.longitude) {
                              openInAppNavigation({
                                title: act.title,
                                locationName: act.locationName || destName,
                                coordinates: [act.latitude, act.longitude],
                                dayNumber: selectedDay.dayNumber
                              });
                            }
                          }}
                          className="flex-1 py-2 px-3 rounded-xl bg-[var(--color-primary)] hover:bg-[#2C504A] dark:hover:bg-[var(--color-primary-light)] disabled:opacity-50 disabled:cursor-not-allowed text-white dark:text-zinc-950 text-xs font-bold flex items-center justify-center gap-1.5 press-scale transition-all min-h-[40px]"
                        >
                          <Navigation className="w-3.5 h-3.5" />
                          <span>Directions</span>
                        </button>

                        <button
                          type="button"
                          onClick={() => openCabModal(act.locationName || act.title)}
                          className="flex-1 py-2 px-3 rounded-xl bg-[var(--color-surface-elevated)] hover:bg-[#E4E8E4] dark:hover:bg-zinc-700 border border-[var(--color-border)] dark:border-zinc-700 text-[var(--color-text-primary)] text-xs font-bold flex items-center justify-center gap-1.5 press-scale transition-all min-h-[40px]"
                        >
                          <Car className="w-3.5 h-3.5 text-[var(--color-primary)]" />
                          <span>Book Ride</span>
                        </button>

                        <button
                          type="button"
                          onClick={() => openSwapAssistant({
                            tripId: currentTrip?.id || '',
                            activityId: act.id,
                            activityName: act.title,
                            selectedDay: selectedDay.dayNumber,
                            destination: destName
                          })}
                          className="py-2 px-3 rounded-xl bg-[#E8F0EE] dark:bg-[#12332B] hover:bg-[#D4E4E0] dark:hover:bg-[#194437] border border-[#355F58]/30 dark:border-emerald-800 text-[var(--color-primary)] text-xs font-extrabold flex items-center justify-center gap-1 press-scale transition-all min-h-[40px]"
                          title="Swap with AI alternative"
                        >
                          <Sparkles className="w-3.5 h-3.5" />
                          <span>Swap</span>
                        </button>
                      </div>
                    </div>
                    </React.Fragment>
                  );
                })}
              </div>

              <button
                type="button"
                onClick={handleOptimizeCurrentDay}
                disabled={isOptimizing}
                className="w-full py-3.5 press-scale flex items-center justify-center gap-2 rounded-2xl bg-[#E8F0EE] dark:bg-[#12332B] hover:bg-[#D4E4E0] dark:hover:bg-[#194437] border border-[#355F58]/30 dark:border-emerald-800 text-[var(--color-primary)] font-extrabold text-xs transition-all disabled:opacity-50 shadow-xs"
              >
                <Sparkles className="w-4 h-4 text-[var(--color-primary)]" />
                <span>{isOptimizing ? 'Optimizing Day Route...' : `Optimize Day ${selectedDay.dayNumber} Route Flow`}</span>
              </button>
            </div>
          )}
        </>
      )}

      {budgetAnalysisModal.isOpen && budgetAnalysisModal.data && (
        <ItineraryAiDialog
          icon={Wallet}
          title="AI Budget Intelligence"
          description="Smart expense tracking & cost saving recommendations"
          actionLabel="Done & Save"
          onDismiss={() => {
            setBudgetAnalysisModal({ isOpen: false, data: null });
            aiTrigger.current?.focus({ preventScroll: true });
          }}
        >
          <dl className="grid gap-2 sm:grid-cols-3 sm:text-center">
            {[
              { label: 'Projected', value: budgetAnalysisModal.data.projectedCost, valueStyle: 'text-(--color-text-primary)' },
              { label: 'Target', value: budgetAnalysisModal.data.targetBudget, valueStyle: 'text-(--color-primary)' },
              { label: 'Savings Rec.', value: budgetAnalysisModal.data.savingsRequired, valueStyle: 'text-(--itinerary-accent)', savings: true },
            ].map(({ label, value, valueStyle, savings }) => (
              <div
                key={label}
                className={`flex min-w-0 flex-wrap items-baseline justify-between gap-x-2 gap-y-1 rounded-2xl border px-2.5 py-2 sm:block sm:p-3 ${
                  savings
                    ? 'border-(--itinerary-border) bg-(--itinerary-accent-surface)'
                    : 'border-(--itinerary-border) bg-(--color-surface-elevated)'
                }`}
              >
                <dt className={`text-[10px] font-bold uppercase ${savings ? 'text-(--itinerary-accent)' : 'text-(--color-text-secondary)'}`}>
                  {label}
                </dt>
                <dd className={`min-w-0 text-sm font-black tabular-nums ${valueStyle}`}>
                  ₹{value}
                </dd>
              </div>
            ))}
          </dl>

          <div className="space-y-2">
            <h4 className="text-xs font-extrabold uppercase text-(--itinerary-accent) tracking-wider">AI Optimization Tips</h4>
            {budgetAnalysisModal.data.recommendations.length === 0 ? (
              <p className="text-xs text-(--itinerary-muted) font-medium p-3 bg-(--color-surface-elevated) rounded-2xl text-center">
                Your trip budget is well-balanced! No immediate cuts needed.
              </p>
            ) : (
              budgetAnalysisModal.data.recommendations.map((rec: any, idx: number) => (
                <div key={idx} className="p-3 rounded-2xl bg-(--color-surface-elevated) border border-(--itinerary-border) flex items-start gap-2.5">
                  <Sparkles className="w-4 h-4 text-[var(--color-primary)] shrink-0 mt-0.5" />
                  <div className="min-w-0 space-y-0.5">
                    <p className="text-xs font-bold text-[var(--color-text-primary)]">{rec.reason || rec.suggestion || rec}</p>
                    {rec.estimatedSavings && (
                      <span className="text-[10px] font-bold text-[var(--color-primary)] bg-[#E8F0EE] dark:bg-[#12332B] px-2 py-0.5 rounded-md inline-block">
                        Save up to ₹{rec.estimatedSavings}
                      </span>
                    )}
                  </div>
                </div>
              ))
            )}
          </div>
        </ItineraryAiDialog>
      )}

      {weatherReplanModal.isOpen && weatherReplanModal.data && (
        <ItineraryAiDialog
          icon={CloudRain}
          title="Live Weather AI Alert"
          description="Automatic rain protection & indoor replacements"
          actionLabel="Understand & Close"
          onDismiss={() => {
            setWeatherReplanModal({ isOpen: false, data: null });
            aiTrigger.current?.focus({ preventScroll: true });
          }}
        >
          <div className="p-3.5 rounded-2xl bg-(--itinerary-accent-surface) border border-(--itinerary-border) flex flex-wrap items-center justify-between gap-2">
            <div className="min-w-0 flex-1 basis-48">
              <span className="text-[10px] font-extrabold uppercase text-(--itinerary-accent) block">Forecast Alert</span>
              <span className="text-sm font-black text-[var(--color-text-primary)]">{weatherReplanModal.data.forecast?.condition || 'Forecast'}</span>
              {weatherReplanModal.data.message && (
                <span className="text-[11px] text-[var(--color-text-secondary)] font-medium block mt-0.5">{weatherReplanModal.data.message}</span>
              )}
            </div>
            <span className="px-3 py-1 rounded-full bg-[var(--color-surface)] text-[var(--color-primary)] font-bold text-xs border border-[var(--color-border)] dark:border-zinc-700">
              {weatherReplanModal.data.affectedActivities.length} Outdoor Activities Flagged
            </span>
          </div>

          {/* Swaps & Suggestions List */}
          <div className="space-y-2">
            <h4 className="text-xs font-extrabold uppercase text-(--itinerary-accent) tracking-wider">Proposed Indoor Replacements</h4>
            {weatherReplanModal.data.recommendations.length === 0 ? (
              <p className="text-xs text-(--itinerary-muted) font-medium p-3 bg-(--color-surface-elevated) rounded-2xl text-center">
                All outdoor activities are clear! No weather adjustments needed.
              </p>
            ) : (
              weatherReplanModal.data.recommendations.map((rec: any, idx: number) => (
                <div key={idx} className="p-3 rounded-2xl bg-(--color-surface-elevated) border border-(--itinerary-border) space-y-1">
                  <div className="flex items-start gap-2">
                    <Sparkles className="w-4 h-4 text-[var(--color-primary)] shrink-0 mt-0.5" />
                    <p className="min-w-0 text-xs font-bold text-[var(--color-text-primary)]">{rec.reason || rec.suggestion || (typeof rec === 'string' ? rec : 'Replace outdoor activity with indoor venue')}</p>
                  </div>
                </div>
              ))
            )}
          </div>
        </ItineraryAiDialog>
      )}

      {/* 3. ERROR TOAST BANNER */}
      {errorMessage && (
        <div className="fixed bottom-20 left-1/2 z-50 flex w-[calc(100%-2rem)] max-w-sm -translate-x-1/2 items-center justify-between gap-2 rounded-2xl border border-(--itinerary-error) bg-(--itinerary-error-surface) px-4 py-2 text-xs font-bold text-(--itinerary-error) shadow-2xl animate-fadeIn">
          <span role="alert" className="min-w-0 wrap-anywhere">{errorMessage}</span>
          <button
            type="button"
            aria-label="Dismiss error"
            onClick={() => setErrorMessage(null)}
            className="flex size-11 shrink-0 items-center justify-center rounded-full font-black text-sm"
          >
            ✕
          </button>
        </div>
      )}

      {/* 4. CLIPBOARD COPY TOAST */}
      {copyToast && (
        <div className="fixed bottom-20 left-1/2 -translate-x-1/2 z-50 px-4 py-2.5 rounded-2xl bg-[#1F2522] text-white text-xs font-bold flex items-center gap-2 shadow-2xl animate-fadeIn">
          <Check className="w-4 h-4 text-emerald-400 shrink-0" />
          <span>Itinerary copied to clipboard!</span>
        </div>
      )}

    </div>
  );
};
