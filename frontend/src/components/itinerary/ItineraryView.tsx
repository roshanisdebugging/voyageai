import React, { useState } from 'react';
import { useApp } from '../../context/AppContext';
import { useTrip } from '../../features/trip/TripContext';
import { MapPin, Sparkles, Wallet, CloudRain, RefreshCw, Navigation, Car, Calendar, Download, Copy, Check, Printer, CheckCircle2, Circle, TrainFront, Plane, Bus } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { getApiBaseUrl, getAuthHeaders } from '../../config/apiConfig';
import { useToast } from '../common/UndoToast';
import { isPastTrip } from '../../features/trip/tripRepository';

export const ItineraryView: React.FC = () => {
  const navigate = useNavigate();
  const { openCabModal, openInAppNavigation, openSwapAssistant } = useApp();
  const { currentTrip, currentItinerary, optimizeDayItinerary, optimizeBudget, weatherReplan, setActivityDone, transports, trips, isLoading: isTripsLoading } = useTrip();
  const { showToast } = useToast();
  const [doneBusyId, setDoneBusyId] = useState<string | null>(null);

  const [expandedDayNumber, setExpandedDayNumber] = useState<number>(1);
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

  const handleRunBudgetOptimization = async () => {
    if (!currentTrip?.id) return;
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

  const handleRunWeatherReplan = async () => {
    if (!currentTrip?.id) return;
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
        <p className="min-w-0 break-words text-sm font-bold text-[var(--color-text-primary)]">
          {destName}<span className="font-normal text-[var(--color-text-secondary)]"> · Itinerary</span>
        </p>

        <div className="flex flex-wrap items-center gap-2">
          {/* Export Itinerary Dropdown */}
          <div className="sm:relative">
            <button
              type="button"
              onClick={() => setShowExportDropdown(!showExportDropdown)}
              disabled={isExportingJson}
              className="px-3 py-1.5 rounded-full bg-[var(--color-surface)] hover:bg-[var(--color-surface-elevated)] border border-[var(--color-border)] dark:border-zinc-700 text-[var(--color-text-primary)] text-xs font-bold flex items-center gap-1.5 press-scale shadow-xs"
              title="Export Itinerary"
              aria-expanded={showExportDropdown}
              onKeyDown={event => { if (event.key === 'Escape') setShowExportDropdown(false); }}
            >
              <Download className="w-3.5 h-3.5 text-[var(--color-primary)]" />
              <span>Export</span>
            </button>

            {showExportDropdown && (
              <>
                <div 
                  className="fixed inset-0 z-40" 
                  onClick={() => setShowExportDropdown(false)} 
                />
                <div className="absolute left-0 top-full mt-2 w-64 max-w-full sm:left-auto sm:right-0 sm:max-w-none bg-[var(--color-surface)] border border-[var(--color-border)] dark:border-zinc-700 rounded-2xl shadow-xl z-50 p-2 space-y-1 animate-fadeIn text-left">
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
                    <div>
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
                    <div>
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
                    <div>
                      <div className="font-extrabold">Export JSON</div>
                      <div className="text-[10px] text-[var(--color-text-secondary)] font-normal">Raw itinerary data</div>
                    </div>
                  </button>
                </div>
              </>
            )}
          </div>

          <button
            onClick={handleRunBudgetOptimization}
            disabled={isOptimizing}
            className="px-3 py-1.5 rounded-full bg-[var(--color-surface-elevated)] hover:bg-[#E8F0EE] dark:hover:bg-[#12332B] border border-[var(--color-border)] dark:border-zinc-700 text-[var(--color-text-primary)] text-xs font-bold flex items-center gap-1.5 press-scale"
          >
            <Wallet className="w-3.5 h-3.5 text-[var(--color-primary)]" />
            <span>Budget AI</span>
          </button>
          <button
            onClick={handleRunWeatherReplan}
            disabled={isOptimizing}
            className="px-3 py-1.5 rounded-full bg-[#E8F0EE] dark:bg-[#12332B] hover:bg-[#D4E4E0] dark:hover:bg-[#194437] border border-[#355F58]/30 dark:border-emerald-800 text-[var(--color-primary)] text-xs font-bold flex items-center gap-1.5 press-scale"
          >
            <CloudRain className="w-3.5 h-3.5 text-[var(--color-primary)]" />
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
        <div className="p-3.5 rounded-2xl bg-[#E8F0EE] dark:bg-[#12332B] border border-[#355F58]/30 dark:border-emerald-800 text-xs font-bold text-[var(--color-primary)] flex items-center gap-2 animate-fadeIn shadow-xs">
          <RefreshCw className="w-4 h-4 animate-spin shrink-0 text-[var(--color-primary)]" />
          <span>{optStatusMessage}</span>
        </div>
      )}

      {/* If Generating or Empty */}
      {(!days || days.length === 0) ? (
        <div className="bg-[var(--color-surface)] border border-[var(--color-border)] dark:border-zinc-700 rounded-3xl p-8 text-center space-y-3 shadow-xs">
          <RefreshCw className="w-8 h-8 text-[var(--color-primary)] animate-spin mx-auto" />
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
                {selectedDay.activities.map((act, idx) => {
                  const isDone = Boolean(act.isDone);
                  return (
                    <div
                      key={act.id}
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

      {/* 1. STYLISH BUDGET AI ANALYSIS MODAL SHEET */}
      {budgetAnalysisModal.isOpen && budgetAnalysisModal.data && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-[#1F2522]/50 backdrop-blur-xs animate-fadeIn">
          <div className="bg-[var(--color-surface)] border border-[var(--color-border)] dark:border-zinc-700 rounded-3xl p-6 max-w-md w-full space-y-5 shadow-2xl animate-scaleUp">
            
            <div className="flex items-center justify-between border-b border-[var(--color-border)] dark:border-zinc-700 pb-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-2xl bg-[#E8F0EE] dark:bg-[#12332B] border border-[#355F58]/30 dark:border-emerald-800 flex items-center justify-center text-[var(--color-primary)]">
                  <Wallet className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-base font-extrabold text-[var(--color-text-primary)]">AI Budget Intelligence</h3>
                  <p className="text-xs text-[var(--color-text-secondary)] font-medium">Smart expense tracking & cost saving recommendations</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setBudgetAnalysisModal({ isOpen: false, data: null })}
                className="w-8 h-8 rounded-full bg-[var(--color-surface-elevated)] text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)] flex items-center justify-center font-bold text-xs"
              >
                ✕
              </button>
            </div>

            {/* Metrics 3-Card Grid */}
            <div className="grid grid-cols-3 gap-2 text-center">
              <div className="p-3 rounded-2xl bg-[var(--color-surface-elevated)] border border-[var(--color-border)] dark:border-zinc-700">
                <span className="text-[10px] font-bold text-[var(--color-text-secondary)] uppercase block">Projected</span>
                <span className="text-sm font-black text-[var(--color-text-primary)]">₹{budgetAnalysisModal.data.projectedCost}</span>
              </div>
              <div className="p-3 rounded-2xl bg-[var(--color-surface-elevated)] border border-[var(--color-border)] dark:border-zinc-700">
                <span className="text-[10px] font-bold text-[var(--color-text-secondary)] uppercase block">Target</span>
                <span className="text-sm font-black text-[var(--color-primary)]">₹{budgetAnalysisModal.data.targetBudget}</span>
              </div>
              <div className="p-3 rounded-2xl bg-[#E8F0EE] dark:bg-[#12332B] border border-[#355F58]/30 dark:border-emerald-800">
                <span className="text-[10px] font-bold text-[var(--color-primary)] uppercase block">Savings Rec.</span>
                <span className="text-sm font-black text-[var(--color-primary)]">₹{budgetAnalysisModal.data.savingsRequired}</span>
              </div>
            </div>

            {/* Recommendations List */}
            <div className="space-y-2 max-h-60 overflow-y-auto pr-1">
              <h4 className="text-xs font-extrabold uppercase text-[var(--color-primary)] tracking-wider">AI Optimization Tips</h4>
              {budgetAnalysisModal.data.recommendations.length === 0 ? (
                <p className="text-xs text-[var(--color-text-secondary)] font-medium p-3 bg-[var(--color-surface-elevated)] rounded-2xl text-center">
                  Your trip budget is well-balanced! No immediate cuts needed.
                </p>
              ) : (
                budgetAnalysisModal.data.recommendations.map((rec: any, idx: number) => (
                  <div key={idx} className="p-3 rounded-2xl bg-[var(--color-surface-elevated)] border border-[var(--color-border)] dark:border-zinc-700 flex items-start gap-2.5">
                    <Sparkles className="w-4 h-4 text-[var(--color-primary)] shrink-0 mt-0.5" />
                    <div className="space-y-0.5">
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

            <button
              type="button"
              onClick={() => setBudgetAnalysisModal({ isOpen: false, data: null })}
              className="w-full py-3.5 rounded-2xl bg-[var(--color-primary)] hover:bg-[#2C504A] dark:hover:bg-[var(--color-primary-light)] text-white dark:text-zinc-950 font-extrabold text-xs shadow-xs press-scale"
            >
              Done & Save
            </button>
          </div>
        </div>
      )}

      {/* 2. STYLISH WEATHER AI REPLAN MODAL SHEET */}
      {weatherReplanModal.isOpen && weatherReplanModal.data && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-[#1F2522]/50 backdrop-blur-xs animate-fadeIn">
          <div className="bg-[var(--color-surface)] border border-[var(--color-border)] dark:border-zinc-700 rounded-3xl p-6 max-w-md w-full space-y-5 shadow-2xl animate-scaleUp">
            
            <div className="flex items-center justify-between border-b border-[var(--color-border)] dark:border-zinc-700 pb-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-2xl bg-[#E8F0EE] dark:bg-[#12332B] border border-[#355F58]/30 dark:border-emerald-800 flex items-center justify-center text-[var(--color-primary)]">
                  <CloudRain className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-base font-extrabold text-[var(--color-text-primary)]">Live Weather AI Alert</h3>
                  <p className="text-xs text-[var(--color-text-secondary)] font-medium">Automatic rain protection & indoor replacements</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setWeatherReplanModal({ isOpen: false, data: null })}
                className="w-8 h-8 rounded-full bg-[var(--color-surface-elevated)] text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)] flex items-center justify-center font-bold text-xs"
              >
                ✕
              </button>
            </div>

            {/* Weather Banner */}
            <div className="p-3.5 rounded-2xl bg-[#E8F0EE] dark:bg-[#12332B] border border-[#355F58]/30 dark:border-emerald-800 flex items-center justify-between">
              <div>
                <span className="text-[10px] font-extrabold uppercase text-[var(--color-primary)] block">Forecast Alert</span>
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
            <div className="space-y-2 max-h-60 overflow-y-auto pr-1">
              <h4 className="text-xs font-extrabold uppercase text-[var(--color-primary)] tracking-wider">Proposed Indoor Replacements</h4>
              {weatherReplanModal.data.recommendations.length === 0 ? (
                <p className="text-xs text-[var(--color-text-secondary)] font-medium p-3 bg-[var(--color-surface-elevated)] rounded-2xl text-center">
                  All outdoor activities are clear! No weather adjustments needed.
                </p>
              ) : (
                weatherReplanModal.data.recommendations.map((rec: any, idx: number) => (
                  <div key={idx} className="p-3 rounded-2xl bg-[var(--color-surface-elevated)] border border-[var(--color-border)] dark:border-zinc-700 space-y-1">
                    <div className="flex items-start gap-2">
                      <Sparkles className="w-4 h-4 text-[var(--color-primary)] shrink-0 mt-0.5" />
                      <p className="text-xs font-bold text-[var(--color-text-primary)]">{rec.reason || rec.suggestion || (typeof rec === 'string' ? rec : 'Replace outdoor activity with indoor venue')}</p>
                    </div>
                  </div>
                ))
              )}
            </div>

            <button
              type="button"
              onClick={() => setWeatherReplanModal({ isOpen: false, data: null })}
              className="w-full py-3.5 rounded-2xl bg-[var(--color-primary)] hover:bg-[#2C504A] dark:hover:bg-[var(--color-primary-light)] text-white dark:text-zinc-950 font-extrabold text-xs shadow-xs press-scale"
            >
              Understand & Close
            </button>
          </div>
        </div>
      )}

      {/* 3. ERROR TOAST BANNER */}
      {errorMessage && (
        <div className="fixed bottom-20 left-1/2 -translate-x-1/2 z-50 max-w-sm w-full p-4 bg-rose-700 text-white rounded-2xl font-bold text-xs shadow-2xl flex items-center justify-between animate-fadeIn">
          <span>{errorMessage}</span>
          <button type="button" onClick={() => setErrorMessage(null)} className="ml-2 font-black text-sm">✕</button>
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
