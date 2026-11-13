import React, { useState } from 'react';
import { useApp } from '../../context/AppContext';
import { useTrip } from '../../features/trip/TripContext';
import { MapPin, Sparkles, Wallet, CloudRain, RefreshCw, Navigation, Car, Calendar, ArrowLeft, Download, Copy, Check, Printer, CheckCircle2, Circle, TrainFront, Plane, Bus } from 'lucide-react';
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
    text += `👥 Travelers: ${currentTrip.travelers?.length || 2}\n\n`;

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
        <div className="max-w-xl mx-auto py-16 flex items-center justify-center text-[#5F6863] text-sm font-medium gap-2">
          <RefreshCw className="w-4 h-4 animate-spin text-[#355F58]" />
          <span>Loading your trips…</span>
        </div>
      );
    }
    const pastCount = trips.filter(t => isPastTrip(t)).length;
    return (
      <div className="max-w-xl mx-auto pt-10 pb-28 animate-fadeIn">
        <div className="bg-white border border-[#D9DEDA] rounded-3xl p-8 text-center space-y-4 shadow-xs">
          <div className="w-14 h-14 rounded-2xl bg-[#E8F0EE] text-[#355F58] flex items-center justify-center mx-auto">
            <Calendar className="w-7 h-7" />
          </div>
          <div className="space-y-1">
            <h1 className="text-lg font-extrabold text-[#1F2522]">No current trip</h1>
            <p className="text-xs text-[#5F6863] font-medium max-w-xs mx-auto">
              You have no ongoing or upcoming trips. Plan your next one and we'll build the itinerary for you.
            </p>
          </div>
          <button
            type="button"
            onClick={() => navigate('/trips/new')}
            className="w-full py-3.5 rounded-2xl bg-[#355F58] hover:bg-[#2C504A] text-white font-extrabold text-sm press-scale shadow-xs min-h-[48px]"
          >
            Plan a trip
          </button>
          <button
            type="button"
            onClick={() => navigate('/trips', { state: { tab: 'PAST' } })}
            className="text-xs font-bold text-[#355F58] hover:underline"
          >
            Past trips{pastCount > 0 ? ` (${pastCount})` : ''}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-5 pb-28 max-w-xl mx-auto animate-fadeIn">
      {/* Top Header Bar */}
      <div className="flex items-center justify-between border-b border-[#D9DEDA] pb-3">
        <button
          type="button"
          onClick={() => navigate('/trips')}
          className="flex items-center gap-2 text-[#1F2522] hover:text-[#355F58] font-bold text-sm press-scale"
        >
          <ArrowLeft className="w-5 h-5 text-[#355F58]" />
          <span>My Trips</span>
        </button>

        <div className="flex items-center gap-2">
          {/* Export Itinerary Dropdown */}
          <div className="relative">
            <button
              type="button"
              onClick={() => setShowExportDropdown(!showExportDropdown)}
              disabled={isExportingJson}
              className="px-3 py-1.5 rounded-full bg-white hover:bg-[#F0F2EF] border border-[#D9DEDA] text-[#1F2522] text-xs font-bold flex items-center gap-1.5 press-scale shadow-xs"
              title="Export Itinerary"
            >
              <Download className="w-3.5 h-3.5 text-[#355F58]" />
              <span>Export</span>
            </button>

            {showExportDropdown && (
              <>
                <div 
                  className="fixed inset-0 z-40" 
                  onClick={() => setShowExportDropdown(false)} 
                />
                <div className="absolute right-0 top-full mt-2 w-64 bg-white border border-[#D9DEDA] rounded-2xl shadow-xl z-50 p-2 space-y-1 animate-fadeIn text-left">
                  <div className="px-3 py-1.5 text-[10px] font-extrabold text-[#7C8580] uppercase tracking-wider border-b border-[#F0F2EF]">
                    Export Itinerary
                  </div>
                  
                  <button
                    type="button"
                    onClick={handleDownloadPdfOrPrint}
                    className="w-full px-3 py-2.5 rounded-xl hover:bg-[#F0F2EF] text-[#1F2522] text-xs font-bold flex items-center gap-2.5 transition-colors text-left"
                  >
                    <div className="w-7 h-7 rounded-lg bg-[#E8F0EE] text-[#355F58] flex items-center justify-center shrink-0">
                      <Printer className="w-4 h-4" />
                    </div>
                    <div>
                      <div className="font-extrabold">Download PDF / Print</div>
                      <div className="text-[10px] text-[#5F6863] font-normal">Print-optimized layout</div>
                    </div>
                  </button>

                  <button
                    type="button"
                    onClick={handleCopyShareableSummary}
                    className="w-full px-3 py-2.5 rounded-xl hover:bg-[#F0F2EF] text-[#1F2522] text-xs font-bold flex items-center gap-2.5 transition-colors text-left"
                  >
                    <div className="w-7 h-7 rounded-lg bg-[#E8F0EE] text-[#355F58] flex items-center justify-center shrink-0">
                      <Copy className="w-4 h-4" />
                    </div>
                    <div>
                      <div className="font-extrabold">Copy Shareable Summary</div>
                      <div className="text-[10px] text-[#5F6863] font-normal">Formatted text to clipboard</div>
                    </div>
                  </button>

                  <button
                    type="button"
                    onClick={handleExportJson}
                    className="w-full px-3 py-2.5 rounded-xl hover:bg-[#F0F2EF] text-[#1F2522] text-xs font-bold flex items-center gap-2.5 transition-colors text-left"
                  >
                    <div className="w-7 h-7 rounded-lg bg-[#E8F0EE] text-[#355F58] flex items-center justify-center shrink-0">
                      <Download className="w-4 h-4" />
                    </div>
                    <div>
                      <div className="font-extrabold">Export JSON</div>
                      <div className="text-[10px] text-[#5F6863] font-normal">Raw itinerary data</div>
                    </div>
                  </button>
                </div>
              </>
            )}
          </div>

          <button
            onClick={handleRunBudgetOptimization}
            disabled={isOptimizing}
            className="px-3 py-1.5 rounded-full bg-[#F0F2EF] hover:bg-[#E8F0EE] border border-[#D9DEDA] text-[#1F2522] text-xs font-bold flex items-center gap-1.5 press-scale"
          >
            <Wallet className="w-3.5 h-3.5 text-[#355F58]" />
            <span>Budget AI</span>
          </button>
          <button
            onClick={handleRunWeatherReplan}
            disabled={isOptimizing}
            className="px-3 py-1.5 rounded-full bg-[#E8F0EE] hover:bg-[#D4E4E0] border border-[#355F58]/30 text-[#355F58] text-xs font-bold flex items-center gap-1.5 press-scale"
          >
            <CloudRain className="w-3.5 h-3.5 text-[#355F58]" />
            <span>Weather AI</span>
          </button>
        </div>
      </div>

      {/* Main Trip Banner */}
      <div className="bg-white border border-[#D9DEDA] rounded-3xl p-5 space-y-2 shadow-xs">
        <div className="flex items-center justify-between">
          <span className="px-3 py-1 rounded-full bg-[#E8F0EE] text-[#355F58] font-extrabold text-xs border border-[#355F58]/30">
            {destName}
          </span>
          <span className="text-xs text-[#5F6863] font-bold flex items-center gap-1">
            <Calendar className="w-3.5 h-3.5 text-[#355F58]" />
            {currentTrip?.startDate} to {currentTrip?.endDate}
          </span>
        </div>
        <h1 className="text-xl sm:text-2xl font-black text-[#1F2522]">
          {currentTrip?.title || `${destName} Tour Package`}
        </h1>
        <p className="text-xs text-[#5F6863] font-medium">
          {days.length} Days Detailed AI Itinerary · {currentTrip?.travelers?.length || 2} Travelers
        </p>
      </div>

      {recommendedTransport.length > 0 && (
        <div className="bg-white border border-[#D9DEDA] rounded-3xl p-4 space-y-2.5 shadow-xs">
          <h2 className="text-xs font-extrabold uppercase tracking-wider text-[#355F58]">
            Getting there{currentTrip?.origin?.name ? ` from ${currentTrip.origin.name}` : ''}
          </h2>
          {recommendedTransport.map(t => (
            <div key={t.id} className="flex items-start gap-3 p-3 rounded-2xl bg-[#F0F2EF] border border-[#D9DEDA]">
              <div className="w-8 h-8 rounded-xl bg-[#E8F0EE] text-[#355F58] flex items-center justify-center shrink-0">
                {transportIcon(t.transportType)}
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-xs font-extrabold text-[#1F2522]">{t.providerName}</div>
                <div className="text-[11px] text-[#5F6863]">{t.pickupLocation} → {t.dropoffLocation}</div>
                {t.bookingReference && <div className="text-[11px] text-[#5F6863]">{t.bookingReference}</div>}
              </div>
              {t.estimatedFare > 0 && (
                <span className="text-xs font-bold text-[#355F58] shrink-0" title="Estimated one-way fare for the whole group">
                  ~₹{t.estimatedFare.toLocaleString('en-IN')}
                </span>
              )}
            </div>
          ))}
          <p className="text-[10px] text-[#7C8580]">Suggested by AI to fit your budget. Fares are estimates for the whole group, one way.</p>
        </div>
      )}

      {optStatusMessage && (
        <div className="p-3.5 rounded-2xl bg-[#E8F0EE] border border-[#355F58]/30 text-xs font-bold text-[#355F58] flex items-center gap-2 animate-fadeIn shadow-xs">
          <RefreshCw className="w-4 h-4 animate-spin shrink-0 text-[#355F58]" />
          <span>{optStatusMessage}</span>
        </div>
      )}

      {/* If Generating or Empty */}
      {(!days || days.length === 0) ? (
        <div className="bg-white border border-[#D9DEDA] rounded-3xl p-8 text-center space-y-3 shadow-xs">
          <RefreshCw className="w-8 h-8 text-[#355F58] animate-spin mx-auto" />
          <h2 className="text-lg font-extrabold text-[#1F2522]">Generating AI Itinerary...</h2>
          <p className="text-xs text-[#5F6863] font-medium">
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
                className={`press-scale shrink-0 px-4 py-2.5 rounded-2xl text-xs font-extrabold transition-all border ${
                  expandedDayNumber === day.dayNumber
                    ? 'bg-[#355F58] text-white border-[#355F58] shadow-xs'
                    : 'bg-[#F0F2EF] text-[#1F2522] border-[#D9DEDA] hover:border-[#355F58]/40'
                }`}
              >
                Day {day.dayNumber}
              </button>
            ))}
          </div>

          {/* Connected Day Timeline */}
          {selectedDay && (
            <div key={selectedDay.id || selectedDay.dayNumber} className="space-y-4">
              <div className="p-4 rounded-2xl bg-white border border-[#D9DEDA] flex items-center justify-between shadow-xs">
                <div>
                  <h2 className="text-base font-extrabold text-[#1F2522]">{selectedDay.title}</h2>
                  <p className="text-xs text-[#5F6863] font-medium mt-0.5">{selectedDay.date || `Day ${selectedDay.dayNumber}`}</p>
                </div>
                <span className="px-3 py-1 rounded-full bg-[#E8F0EE] text-[#355F58] font-bold text-xs border border-[#355F58]/30">
                  {selectedDay.activities.length} Activities
                </span>
              </div>

              <div className="space-y-3">
                {selectedDay.activities.map((act, idx) => {
                  const isDone = Boolean(act.isDone);
                  return (
                    <div
                      key={act.id}
                      className="bg-white border border-[#D9DEDA] rounded-2xl p-4 space-y-3 shadow-xs hover:border-[#355F58]/40 transition-all"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0 flex-1 space-y-1.5">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-[10px] uppercase font-bold text-[#355F58] tracking-wider px-2 py-0.5 rounded-md bg-[#E8F0EE] border border-[#355F58]/20">
                              Activity {idx + 1} · {act?.timeSlot ?? 'Flexible'}
                            </span>
                            {act.isConfirmed && (
                              <span className="inline-flex items-center gap-1 text-[10px] font-bold text-emerald-700 bg-emerald-50 border border-emerald-200/80 px-2 py-0.5 rounded-md">
                                <Check className="w-3 h-3 stroke-[2.5]" /> Confirmed
                              </span>
                            )}
                          </div>

                          <h3 className={`text-base font-extrabold leading-snug break-words ${isDone ? 'text-[#5F6863] line-through' : 'text-[#1F2522]'}`}>
                            {act.title}
                          </h3>

                          <p className="text-xs text-[#5F6863] flex items-center gap-1 font-medium pt-0.5">
                            <MapPin className="w-3.5 h-3.5 text-[#355F58] shrink-0" />
                            <span className="truncate">{act.locationName || destName}</span>
                          </p>
                        </div>

                        {act.estimatedCostInr != null && (
                          <span className="text-xs font-bold text-[#355F58] bg-[#E8F0EE] px-2.5 py-1 rounded-full border border-[#D9DEDA] shrink-0 self-start">
                            ₹{act.estimatedCostInr}
                          </span>
                        )}
                      </div>

                      {act.description && (
                        <p className="text-xs text-[#5F6863] leading-relaxed font-medium">{act.description}</p>
                      )}

                      {/* Action Buttons */}
                      <div className="flex items-center gap-2 pt-2 border-t border-[#D9DEDA]">
                        <button
                          type="button"
                          onClick={() => handleToggleDone(act.id, act.title, isDone)}
                          disabled={doneBusyId === act.id}
                          aria-pressed={isDone}
                          aria-label={isDone ? `Mark ${act.title} as not done` : `Mark ${act.title} as done`}
                          className={`py-2 px-3 rounded-xl border text-xs font-bold flex items-center justify-center gap-1.5 press-scale transition-all min-h-[40px] disabled:opacity-50 ${
                            isDone ? 'bg-emerald-50 border-emerald-200 text-emerald-700' : 'bg-white border-[#D9DEDA] text-[#1F2522] hover:bg-[#F0F2EF]'
                          }`}
                        >
                          {isDone ? <CheckCircle2 className="w-4 h-4" /> : <Circle className="w-4 h-4 text-[#355F58]" />}
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
                          className="flex-1 py-2 px-3 rounded-xl bg-[#355F58] hover:bg-[#2C504A] disabled:opacity-50 disabled:cursor-not-allowed text-white text-xs font-bold flex items-center justify-center gap-1.5 press-scale transition-all min-h-[40px]"
                        >
                          <Navigation className="w-3.5 h-3.5" />
                          <span>Directions</span>
                        </button>

                        <button
                          type="button"
                          onClick={() => openCabModal(act.locationName || act.title)}
                          className="flex-1 py-2 px-3 rounded-xl bg-[#F0F2EF] hover:bg-[#E4E8E4] border border-[#D9DEDA] text-[#1F2522] text-xs font-bold flex items-center justify-center gap-1.5 press-scale transition-all min-h-[40px]"
                        >
                          <Car className="w-3.5 h-3.5 text-[#355F58]" />
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
                          className="py-2 px-3 rounded-xl bg-[#E8F0EE] hover:bg-[#D4E4E0] border border-[#355F58]/30 text-[#355F58] text-xs font-extrabold flex items-center justify-center gap-1 press-scale transition-all min-h-[40px]"
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
                className="w-full py-3.5 press-scale flex items-center justify-center gap-2 rounded-2xl bg-[#E8F0EE] hover:bg-[#D4E4E0] border border-[#355F58]/30 text-[#355F58] font-extrabold text-xs transition-all disabled:opacity-50 shadow-xs"
              >
                <Sparkles className="w-4 h-4 text-[#355F58]" />
                <span>{isOptimizing ? 'Optimizing Day Route...' : `Optimize Day ${selectedDay.dayNumber} Route Flow`}</span>
              </button>
            </div>
          )}
        </>
      )}

      {/* 1. STYLISH BUDGET AI ANALYSIS MODAL SHEET */}
      {budgetAnalysisModal.isOpen && budgetAnalysisModal.data && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-[#1F2522]/50 backdrop-blur-xs animate-fadeIn">
          <div className="bg-white border border-[#D9DEDA] rounded-3xl p-6 max-w-md w-full space-y-5 shadow-2xl animate-scaleUp">
            
            <div className="flex items-center justify-between border-b border-[#D9DEDA] pb-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-2xl bg-[#E8F0EE] border border-[#355F58]/30 flex items-center justify-center text-[#355F58]">
                  <Wallet className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-base font-extrabold text-[#1F2522]">AI Budget Intelligence</h3>
                  <p className="text-xs text-[#5F6863] font-medium">Smart expense tracking & cost saving recommendations</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setBudgetAnalysisModal({ isOpen: false, data: null })}
                className="w-8 h-8 rounded-full bg-[#F0F2EF] text-[#5F6863] hover:text-[#1F2522] flex items-center justify-center font-bold text-xs"
              >
                ✕
              </button>
            </div>

            {/* Metrics 3-Card Grid */}
            <div className="grid grid-cols-3 gap-2 text-center">
              <div className="p-3 rounded-2xl bg-[#F0F2EF] border border-[#D9DEDA]">
                <span className="text-[10px] font-bold text-[#5F6863] uppercase block">Projected</span>
                <span className="text-sm font-black text-[#1F2522]">₹{budgetAnalysisModal.data.projectedCost}</span>
              </div>
              <div className="p-3 rounded-2xl bg-[#F0F2EF] border border-[#D9DEDA]">
                <span className="text-[10px] font-bold text-[#5F6863] uppercase block">Target</span>
                <span className="text-sm font-black text-[#355F58]">₹{budgetAnalysisModal.data.targetBudget}</span>
              </div>
              <div className="p-3 rounded-2xl bg-[#E8F0EE] border border-[#355F58]/30">
                <span className="text-[10px] font-bold text-[#355F58] uppercase block">Savings Rec.</span>
                <span className="text-sm font-black text-[#355F58]">₹{budgetAnalysisModal.data.savingsRequired}</span>
              </div>
            </div>

            {/* Recommendations List */}
            <div className="space-y-2 max-h-60 overflow-y-auto pr-1">
              <h4 className="text-xs font-extrabold uppercase text-[#355F58] tracking-wider">AI Optimization Tips</h4>
              {budgetAnalysisModal.data.recommendations.length === 0 ? (
                <p className="text-xs text-[#5F6863] font-medium p-3 bg-[#F0F2EF] rounded-2xl text-center">
                  Your trip budget is well-balanced! No immediate cuts needed.
                </p>
              ) : (
                budgetAnalysisModal.data.recommendations.map((rec: any, idx: number) => (
                  <div key={idx} className="p-3 rounded-2xl bg-[#F0F2EF] border border-[#D9DEDA] flex items-start gap-2.5">
                    <Sparkles className="w-4 h-4 text-[#355F58] shrink-0 mt-0.5" />
                    <div className="space-y-0.5">
                      <p className="text-xs font-bold text-[#1F2522]">{rec.reason || rec.suggestion || rec}</p>
                      {rec.estimatedSavings && (
                        <span className="text-[10px] font-bold text-[#355F58] bg-[#E8F0EE] px-2 py-0.5 rounded-md inline-block">
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
              className="w-full py-3.5 rounded-2xl bg-[#355F58] hover:bg-[#2C504A] text-white font-extrabold text-xs shadow-xs press-scale"
            >
              Done & Save
            </button>
          </div>
        </div>
      )}

      {/* 2. STYLISH WEATHER AI REPLAN MODAL SHEET */}
      {weatherReplanModal.isOpen && weatherReplanModal.data && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-[#1F2522]/50 backdrop-blur-xs animate-fadeIn">
          <div className="bg-white border border-[#D9DEDA] rounded-3xl p-6 max-w-md w-full space-y-5 shadow-2xl animate-scaleUp">
            
            <div className="flex items-center justify-between border-b border-[#D9DEDA] pb-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-2xl bg-[#E8F0EE] border border-[#355F58]/30 flex items-center justify-center text-[#355F58]">
                  <CloudRain className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-base font-extrabold text-[#1F2522]">Live Weather AI Alert</h3>
                  <p className="text-xs text-[#5F6863] font-medium">Automatic rain protection & indoor replacements</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setWeatherReplanModal({ isOpen: false, data: null })}
                className="w-8 h-8 rounded-full bg-[#F0F2EF] text-[#5F6863] hover:text-[#1F2522] flex items-center justify-center font-bold text-xs"
              >
                ✕
              </button>
            </div>

            {/* Weather Banner */}
            <div className="p-3.5 rounded-2xl bg-[#E8F0EE] border border-[#355F58]/30 flex items-center justify-between">
              <div>
                <span className="text-[10px] font-extrabold uppercase text-[#355F58] block">Forecast Alert</span>
                <span className="text-sm font-black text-[#1F2522]">{weatherReplanModal.data.forecast?.condition || 'Forecast'}</span>
                {weatherReplanModal.data.message && (
                  <span className="text-[11px] text-[#5F6863] font-medium block mt-0.5">{weatherReplanModal.data.message}</span>
                )}
              </div>
              <span className="px-3 py-1 rounded-full bg-white text-[#355F58] font-bold text-xs border border-[#D9DEDA]">
                {weatherReplanModal.data.affectedActivities.length} Outdoor Activities Flagged
              </span>
            </div>

            {/* Swaps & Suggestions List */}
            <div className="space-y-2 max-h-60 overflow-y-auto pr-1">
              <h4 className="text-xs font-extrabold uppercase text-[#355F58] tracking-wider">Proposed Indoor Replacements</h4>
              {weatherReplanModal.data.recommendations.length === 0 ? (
                <p className="text-xs text-[#5F6863] font-medium p-3 bg-[#F0F2EF] rounded-2xl text-center">
                  All outdoor activities are clear! No weather adjustments needed.
                </p>
              ) : (
                weatherReplanModal.data.recommendations.map((rec: any, idx: number) => (
                  <div key={idx} className="p-3 rounded-2xl bg-[#F0F2EF] border border-[#D9DEDA] space-y-1">
                    <div className="flex items-start gap-2">
                      <Sparkles className="w-4 h-4 text-[#355F58] shrink-0 mt-0.5" />
                      <p className="text-xs font-bold text-[#1F2522]">{rec.reason || rec.suggestion || (typeof rec === 'string' ? rec : 'Replace outdoor activity with indoor venue')}</p>
                    </div>
                  </div>
                ))
              )}
            </div>

            <button
              type="button"
              onClick={() => setWeatherReplanModal({ isOpen: false, data: null })}
              className="w-full py-3.5 rounded-2xl bg-[#355F58] hover:bg-[#2C504A] text-white font-extrabold text-xs shadow-xs press-scale"
            >
              Understand & Close
            </button>
          </div>
        </div>
      )}

      {/* 3. ERROR TOAST BANNER */}
      {errorMessage && (
        <div className="fixed bottom-20 left-1/2 -translate-x-1/2 z-50 max-w-sm w-full p-4 bg-rose-600 text-white rounded-2xl font-bold text-xs shadow-2xl flex items-center justify-between animate-fadeIn">
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
