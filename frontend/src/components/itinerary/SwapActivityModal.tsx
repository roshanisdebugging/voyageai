import React, { useState, useEffect } from 'react';
import { useApp } from '../../context/AppContext';
import { useTrip } from '../../features/trip/TripContext';
import { getApiBaseUrl, DEFAULT_FETCH_OPTIONS } from '../../config/apiConfig';
import { Sparkles, RefreshCw, X, Clock, MapPin, Check, AlertCircle } from 'lucide-react';
import { isMockPayload } from '../../utils/mockIndicator';
import { MockCardAlert } from '../common/MockCardAlert';

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
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-md animate-fadeIn">
      <div className="relative w-full max-w-lg rounded-3xl bg-slate-900 border border-white/10 p-5 shadow-2xl space-y-4 text-slate-100 max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-white/10 pb-3">
          <div className="space-y-0.5">
            <span className="px-2.5 py-0.5 rounded-full bg-emerald-500/15 border border-emerald-500/30 text-emerald-400 text-[10px] font-black uppercase flex items-center gap-1 w-fit">
              <Sparkles className="w-3 h-3 text-emerald-400" /> AI Activity Swap
            </span>
            <h2 className="text-base font-black text-white flex items-center gap-2">
              Replace "{targetTitle}"
            </h2>
            <p className="text-xs text-slate-400 font-semibold">
              Trip to <span className="text-emerald-400 font-extrabold">{destName}</span> • Day {dayNum}
            </p>
          </div>

          <button
            onClick={closeSwapAssistant}
            className="p-2 rounded-full bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-white transition-all press-scale"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Content Body */}
        <div className="flex-1 overflow-y-auto space-y-3 pr-1">
          {isLoading ? (
            <div className="py-12 text-center space-y-3">
              <RefreshCw className="w-7 h-7 text-emerald-400 animate-spin mx-auto" />
              <p className="text-xs font-bold text-slate-300">
                Finding authentic alternatives in {destName}...
              </p>
            </div>
          ) : errorMsg ? (
            <div className="p-4 rounded-2xl bg-rose-500/15 border border-rose-500/30 text-rose-300 text-xs flex items-center gap-2">
              <AlertCircle className="w-4 h-4 shrink-0 text-rose-400" />
              <span>{errorMsg}</span>
            </div>
          ) : alternatives.length === 0 ? (
            <div className="py-8 text-center text-xs text-slate-400">
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
                  />
                );
              }

              const isSwappingThis = swappingId === opt.id;
              const isSuccess = swappedSuccessId === opt.id;

              return (
                <div
                  key={opt.id}
                  className="rounded-2xl bg-slate-950/80 border border-white/10 p-4 space-y-2.5 hover:border-emerald-500/40 transition-all shadow-md"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <span className="px-2 py-0.5 rounded-md bg-emerald-500/20 text-emerald-300 text-[10px] font-black border border-emerald-500/30 uppercase">
                        {opt.tag || opt.category || 'Alternative'}
                      </span>
                      <h3 className="text-sm font-black text-white mt-1">
                        {opt.title}
                      </h3>
                      <p className="text-[11px] text-slate-400 flex items-center gap-1 mt-0.5">
                        <MapPin className="w-3 h-3 text-emerald-400 shrink-0" />
                        <span className="truncate">{opt.location || destName}</span>
                      </p>
                    </div>

                    <div className="text-right shrink-0">
                      <span className="text-xs font-black text-emerald-400 block">
                        {opt.cost > 0 ? `₹${opt.cost}` : 'Free'}
                      </span>
                      <span className="text-[10px] text-slate-400 font-bold flex items-center gap-1 mt-0.5 justify-end">
                        <Clock className="w-3 h-3 text-slate-400" /> {opt.duration || '2 hrs'}
                      </span>
                    </div>
                  </div>

                  <p className="text-xs text-slate-300 leading-relaxed font-medium">
                    {opt.description}
                  </p>

                  <div className="pt-2 border-t border-white/10 flex justify-end">
                    <button
                      onClick={() => handleExecuteSwap(opt)}
                      disabled={Boolean(swappingId)}
                      className={`px-4 py-2 rounded-xl text-xs font-extrabold flex items-center gap-1.5 transition-all press-scale ${
                        isSuccess
                          ? 'bg-emerald-500 text-slate-950 shadow-lg shadow-emerald-500/30'
                          : 'bg-emerald-500 hover:bg-emerald-400 text-slate-950 shadow-md shadow-emerald-500/20'
                      }`}
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
