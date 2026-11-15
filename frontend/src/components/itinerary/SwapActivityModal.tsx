import React, { useState, useEffect } from 'react';
import { useApp } from '../../context/AppContext';
import { useTrip } from '../../features/trip/TripContext';
import { getApiBaseUrl, DEFAULT_FETCH_OPTIONS } from '../../config/apiConfig';
import { Sparkles, RefreshCw, X, Clock, MapPin, Check, AlertCircle } from 'lucide-react';
import { isMockPayload } from '../../utils/mockIndicator';
import { MockCardAlert } from '../common/MockCardAlert';
import './itineraryDialog.css';

export interface SwapOptionItem {
  id: string;
  title: string;
  category: string;
  tag: string;
  duration: string;
  cost: number;
  location: string;
  description: string;
}

export const SwapActivityModal: React.FC = () => {
  const { isSwapModalOpen, closeSwapAssistant, swapContext } = useApp();
  const { currentTrip, refetchItinerary } = useTrip();

  const [alternatives, setAlternatives] = useState<SwapOptionItem[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [swappingId, setSwappingId] = useState<string | null>(null);
  const [swappedSuccessId, setSwappedSuccessId] = useState<string | null>(null);

  const destName = swapContext?.destination || currentTrip?.destination?.name || 'Jaipur';
  const targetTitle = swapContext?.activityName || 'Current Activity';
  const dayNum = Number(swapContext?.selectedDay) || 1;

  useEffect(() => {
    if (!isSwapModalOpen || !swapContext) {
      setAlternatives([]);
      setErrorMsg(null);
      setSwappingId(null);
      setSwappedSuccessId(null);
      return;
    }

    let isMounted = true;
    const fetchOptions = async () => {
      setIsLoading(true);
      setErrorMsg(null);

      try {
        const baseUrl = getApiBaseUrl();
        const res = await fetch(`${baseUrl}/api/trips/itinerary/swap-options`, {
          ...DEFAULT_FETCH_OPTIONS,
          method: 'POST',
          body: JSON.stringify({
            trip_id: swapContext.tripId || currentTrip?.id || 'active_trip',
            destination: destName,
            activity_title: targetTitle,
            category: 'Sights',
            day_number: dayNum
          })
        });

        if (res.ok) {
          const data = await res.json();
          if (isMounted) {
            const alts = Array.isArray(data?.alternatives) ? data.alternatives : [];
            setAlternatives(alts);
            setIsLoading(false);
          }
        } else {
          if (isMounted) {
            setErrorMsg(`Failed to fetch swap options (HTTP ${res.status})`);
            setIsLoading(false);
          }
        }
      } catch (err: any) {
        if (isMounted) {
          console.warn('[SWAP OPTIONS ERROR]', err);
          setErrorMsg('Network error while loading alternatives.');
          setIsLoading(false);
        }
      }
    };

    fetchOptions();

    return () => {
      isMounted = false;
    };
  }, [isSwapModalOpen, swapContext, destName, targetTitle, dayNum, currentTrip]);

  if (!isSwapModalOpen || !swapContext) return null;

  const handleExecuteSwap = async (selectedOption: SwapOptionItem) => {
    setSwappingId(selectedOption.id);
    try {
      const baseUrl = getApiBaseUrl();
      const res = await fetch(`${baseUrl}/api/trips/itinerary/swap-execute`, {
        ...DEFAULT_FETCH_OPTIONS,
        method: 'POST',
        body: JSON.stringify({
          trip_id: swapContext.tripId || currentTrip?.id || 'active_trip',
          day_number: dayNum,
          old_activity_id: swapContext.activityId,
          new_activity: selectedOption
        })
      });

      if (res.ok) {
        setSwappedSuccessId(selectedOption.id);
        if (refetchItinerary) {
          await refetchItinerary(swapContext.tripId || currentTrip?.id);
        }
        setTimeout(() => {
          closeSwapAssistant();
        }, 800);
      } else {
        setErrorMsg('Failed to commit swap. Please try again.');
      }
    } catch (err) {
      console.error('[EXECUTE SWAP ERROR]', err);
      setErrorMsg('Failed to execute swap.');
    } finally {
      setSwappingId(null);
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="swap-activity-title"
      className="itinerary-dialog fixed inset-0 z-50 flex items-center justify-center p-4 animate-fadeIn"
    >
      <div className="itinerary-dialog__panel relative w-full max-w-lg rounded-[20px] p-5 space-y-4 flex flex-col">
        {/* Header */}
        <div className="itinerary-dialog__divider flex shrink-0 items-center justify-between gap-3 border-b pb-3">
          <div className="min-w-0 space-y-0.5">
            <span className="itinerary-dialog__label px-2.5 py-0.5 rounded-full text-[10px] font-black uppercase flex items-center gap-1 w-fit">
              <Sparkles className="itinerary-dialog__accent w-3 h-3" /> AI Activity Swap
            </span>
            <h2 id="swap-activity-title" className="text-base font-black tracking-tight wrap-anywhere">
              Replace "{targetTitle}"
            </h2>
            <p className="itinerary-dialog__muted text-xs font-semibold wrap-anywhere">
              Trip to <span className="itinerary-dialog__accent font-extrabold">{destName}</span> • Day {dayNum}
            </p>
          </div>

          <button
            type="button"
            onClick={closeSwapAssistant}
            aria-label="Close activity swap"
            className="itinerary-dialog__button grid place-items-center min-w-11 shrink-0 rounded-full transition-colors press-scale"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Content Body */}
        <div className="itinerary-dialog__scroll flex-1 min-h-0 overflow-y-auto space-y-3 pr-1">
          {isLoading ? (
            <div role="status" className="py-12 text-center space-y-3">
              <RefreshCw className="itinerary-dialog__accent w-7 h-7 animate-spin mx-auto" />
              <p className="itinerary-dialog__muted text-xs font-bold">
                Finding authentic alternatives in {destName}...
              </p>
            </div>
          ) : errorMsg ? (
            <div role="alert" className="itinerary-dialog__error p-4 rounded-2xl border text-xs flex items-center gap-2">
              <AlertCircle className="w-4 h-4 shrink-0" />
              <span>{errorMsg}</span>
            </div>
          ) : alternatives.length === 0 ? (
            <div role="status" className="itinerary-dialog__muted py-8 text-center text-xs">
              No alternatives found for {destName}.
            </div>
          ) : (
            alternatives.map((opt) => {
              if (isMockPayload(opt)) {
                return (
                  <MockCardAlert
                    key={opt.id}
                    title={opt.title}
                    location={opt.location}
                    headsUp={opt.description || 'MOCK: Gemini swap-options service unavailable'}
                    className="itinerary-dialog__fallback"
                  />
                );
              }

              const isSwappingThis = swappingId === opt.id;
              const isSuccess = swappedSuccessId === opt.id;

              return (
                <div
                  key={opt.id}
                  className="itinerary-dialog__elevated rounded-2xl p-4 space-y-2.5"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0 wrap-anywhere">
                      <span className="itinerary-dialog__label px-2 py-0.5 rounded-md text-[10px] font-black uppercase">
                        {opt.tag || opt.category || 'Alternative'}
                      </span>
                      <h3 className="text-sm font-black tracking-tight mt-1">
                        {opt.title}
                      </h3>
                      <p className="itinerary-dialog__muted text-[11px] flex items-center gap-1 mt-0.5">
                        <MapPin className="itinerary-dialog__accent w-3 h-3 shrink-0" />
                        <span className="truncate">{opt.location || destName}</span>
                      </p>
                    </div>

                    <div className="text-right shrink-0">
                      <span className="itinerary-dialog__accent text-xs font-black tabular-nums block">
                        {opt.cost > 0 ? `₹${opt.cost}` : 'Free'}
                      </span>
                      <span className="itinerary-dialog__muted text-[11px] font-bold tabular-nums flex items-center gap-1 mt-0.5 justify-end">
                        <Clock className="w-3 h-3 shrink-0" /> {opt.duration || '—'}
                      </span>
                    </div>
                  </div>

                  <p className="itinerary-dialog__muted text-[13px] leading-relaxed font-medium wrap-anywhere">
                    {opt.description}
                  </p>

                  <div className="itinerary-dialog__divider pt-2 border-t flex justify-end">
                    <button
                      type="button"
                      onClick={() => handleExecuteSwap(opt)}
                      disabled={Boolean(swappingId)}
                      aria-live="polite"
                      className="itinerary-dialog__button itinerary-dialog__button--primary px-4 py-2 rounded-xl text-xs font-extrabold flex items-center gap-1.5 transition-colors press-scale"
                    >
                      {isSwappingThis ? (
                        <>
                          <RefreshCw className="w-3.5 h-3.5 animate-spin" /> Swapping...
                        </>
                      ) : isSuccess ? (
                        <>
                          <Check className="w-3.5 h-3.5 stroke-[3]" /> Swapped!
                        </>
                      ) : (
                        <>
                          <Sparkles className="w-3.5 h-3.5" /> Swap with this
                        </>
                      )}
                    </button>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
};
