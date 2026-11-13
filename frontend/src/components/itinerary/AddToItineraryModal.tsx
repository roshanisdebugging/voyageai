import React, { useState, useEffect } from 'react';
import { X, Calendar, Clock, Sparkles, Check, Loader2, MapPin } from 'lucide-react';

export interface ItineraryDayOption {
  id: string;
  dayNumber: number;
  title: string;
}

export interface AddToItineraryModalProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: (dayId: string, timeSlot: string) => Promise<void> | void;
  itemTitle: string;
  days: Array<{ id: string; dayNumber: number; title: string }>;
  isSubmitting?: boolean;
  category?: string;
  location?: string;
  price?: string | number;
  // Backwards compatibility props for existing callers
  place?: any;
  currentTrip?: any;
}

const TIME_SLOT_OPTIONS = [
  {
    id: 'Morning',
    label: 'Morning',
    icon: '🌅',
    range: '9:00 AM - 12:00 PM',
    description: 'Fresh starts, nature & sightseeing',
  },
  {
    id: 'Afternoon',
    label: 'Afternoon',
    icon: '☀️',
    range: '12:00 PM - 04:00 PM',
    description: 'Museums, dining & indoor culture',
  },
  {
    id: 'Evening',
    label: 'Evening',
    icon: '🌇',
    range: '04:00 PM - 08:00 PM',
    description: 'Sunsets, markets & walks',
  },
  {
    id: 'Night',
    label: 'Night',
    icon: '🌙',
    range: '08:00 PM onwards',
    description: 'Dinner, shows & nightlife',
  },
];

export const AddToItineraryModal: React.FC<AddToItineraryModalProps> = ({
  isOpen,
  onClose,
  onConfirm,
  itemTitle,
  days,
  isSubmitting = false,
  category,
  location,
  price,
  place,
  currentTrip,
}) => {
  // Support legacy props if passed
  const displayTitle = itemTitle || place?.title || place?.name || 'Selected Activity';
  const displayCategory = category || place?.tag || place?.category || 'Activity';
  const displayLocation = location || place?.location || place?.address || '';
  const displayPrice = price ?? place?.price ?? (place?.cost ? `₹${place.cost}` : place?.price_approx);

  // Fallback days if days array is empty
  const effectiveDays: ItineraryDayOption[] = React.useMemo(() => {
    if (days && days.length > 0) return days;
    const count = currentTrip?.totalDays || currentTrip?.itinerary?.length || 3;
    return Array.from({ length: Math.max(count, 1) }, (_, i) => ({
      id: `day_${i + 1}`,
      dayNumber: i + 1,
      title: `Day ${i + 1} Itinerary`,
    }));
  }, [days, currentTrip]);

  const [selectedDayId, setSelectedDayId] = useState<string>('');
  const [selectedSlot, setSelectedSlot] = useState<string>('Morning');
  const [internalLoading, setInternalLoading] = useState<boolean>(false);

  // Initialize selection when modal opens or days change
  useEffect(() => {
    if (isOpen) {
      if (effectiveDays.length > 0) {
        setSelectedDayId(effectiveDays[0].id);
      }
      setSelectedSlot('Morning');
      setInternalLoading(false);
    }
  }, [isOpen, effectiveDays]);

  if (!isOpen) return null;

  const activeDay = effectiveDays.find((d) => d.id === selectedDayId) || effectiveDays[0];
  const activeDayNumber = activeDay?.dayNumber ?? 1;
  const isBusy = isSubmitting || internalLoading;

  const handleConfirmClick = async () => {
    if (!selectedDayId && effectiveDays.length > 0) {
      setSelectedDayId(effectiveDays[0].id);
    }
    const finalDayId = selectedDayId || effectiveDays[0]?.id || 'day_1';
    setInternalLoading(true);
    try {
      await onConfirm(finalDayId, selectedSlot);
    } finally {
      setInternalLoading(false);
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="add-to-itinerary-title"
      className="fixed inset-0 z-[9999] flex items-end sm:items-center justify-center p-0 sm:p-4 bg-slate-950/75 backdrop-blur-md animate-fadeIn"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg rounded-t-3xl sm:rounded-3xl bg-slate-900 border border-white/10 shadow-2xl p-5 sm:p-6 space-y-5 animate-slideUp text-slate-100 max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between border-b border-white/10 pb-4 gap-3">
          <div className="space-y-1 min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="px-2.5 py-0.5 rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 text-[10px] font-extrabold uppercase tracking-wide">
                {displayCategory}
              </span>
              {displayPrice && (
                <span className="px-2 py-0.5 rounded-md bg-white/5 text-amber-300 border border-white/10 text-[11px] font-bold">
                  {typeof displayPrice === 'number' ? `₹${displayPrice}` : displayPrice}
                </span>
              )}
            </div>

            <h3
              id="add-to-itinerary-title"
              className="text-lg font-black text-white leading-tight break-words pt-1"
            >
              {displayTitle}
            </h3>

            {displayLocation && (
              <p className="text-xs text-slate-400 flex items-center gap-1 truncate pt-0.5">
                <MapPin className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                <span className="truncate">{displayLocation}</span>
              </p>
            )}
          </div>

          <button
            type="button"
            onClick={onClose}
            disabled={isBusy}
            aria-label="Close modal"
            className="p-2 rounded-2xl bg-white/5 hover:bg-white/10 text-slate-400 hover:text-white transition-all press-scale shrink-0"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* 1. Day Selector */}
        <div className="space-y-2.5">
          <label className="text-xs font-black text-slate-200 uppercase tracking-wider flex items-center gap-1.5">
            <Calendar className="w-4 h-4 text-emerald-400" />
            1. Select Trip Day
          </label>

          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 max-h-48 overflow-y-auto pr-1">
            {effectiveDays.map((d) => {
              const isSelected = selectedDayId === d.id;
              return (
                <button
                  key={d.id}
                  type="button"
                  onClick={() => setSelectedDayId(d.id)}
                  className={`press-scale p-3 rounded-2xl text-left border transition-all flex flex-col justify-between gap-1 ${
                    isSelected
                      ? 'bg-emerald-500 text-slate-950 border-emerald-400 shadow-lg shadow-emerald-500/25 ring-2 ring-emerald-400/50'
                      : 'bg-white/5 text-slate-300 border-white/10 hover:bg-white/10 hover:border-white/20'
                  }`}
                >
                  <div className="flex items-center justify-between w-full">
                    <span className={`text-xs font-black ${isSelected ? 'text-slate-950' : 'text-emerald-400'}`}>
                      Day {d.dayNumber}
                    </span>
                    {isSelected && <Check className="w-3.5 h-3.5 stroke-[3] text-slate-950" />}
                  </div>
                  <span
                    className={`text-[11px] font-semibold line-clamp-1 ${
                      isSelected ? 'text-slate-900' : 'text-slate-400'
                    }`}
                  >
                    {d.title || `Day ${d.dayNumber}`}
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        {/* 2. Time Slot Selector */}
        <div className="space-y-2.5">
          <label className="text-xs font-black text-slate-200 uppercase tracking-wider flex items-center gap-1.5">
            <Clock className="w-4 h-4 text-amber-400" />
            2. Choose Time Slot
          </label>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {TIME_SLOT_OPTIONS.map((slot) => {
              const isSelected = selectedSlot === slot.id;
              return (
                <button
                  key={slot.id}
                  type="button"
                  onClick={() => setSelectedSlot(slot.id)}
                  className={`press-scale p-3 rounded-2xl text-left border transition-all flex items-start gap-3 ${
                    isSelected
                      ? 'bg-amber-500/20 text-amber-200 border-amber-400/60 shadow-md ring-1 ring-amber-400/40'
                      : 'bg-white/5 text-slate-300 border-white/10 hover:bg-white/10'
                  }`}
                >
                  <span className="text-xl shrink-0" aria-hidden="true">
                    {slot.icon}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-extrabold text-white">{slot.label}</span>
                      {isSelected && <Check className="w-3.5 h-3.5 text-amber-400 stroke-[3]" />}
                    </div>
                    <p className="text-[10px] text-amber-300/80 font-mono mt-0.5">{slot.range}</p>
                    <p className="text-[10px] text-slate-400 line-clamp-1 mt-0.5">{slot.description}</p>
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        {/* Target Confirmation Summary */}
        <div className="px-3.5 py-2.5 rounded-2xl bg-white/5 border border-white/10 flex items-center justify-between text-xs">
          <span className="text-slate-400 font-medium">Adding To:</span>
          <span className="font-extrabold text-emerald-400 flex items-center gap-1">
            <Sparkles className="w-3.5 h-3.5 text-amber-400" />
            Day {activeDayNumber} · {selectedSlot}
          </span>
        </div>

        {/* Action Buttons */}
        <div className="flex items-center gap-3 pt-2">
          <button
            type="button"
            onClick={onClose}
            disabled={isBusy}
            className="flex-1 py-3 px-4 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 text-slate-300 hover:text-white font-bold text-xs transition-all press-scale disabled:opacity-50"
          >
            Cancel
          </button>

          <button
            type="button"
            onClick={handleConfirmClick}
            disabled={isBusy}
            className="flex-2 py-3 px-4 rounded-2xl bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-black text-xs flex items-center justify-center gap-2 shadow-xl shadow-emerald-500/25 transition-all press-scale disabled:opacity-50"
          >
            {isBusy ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" /> Adding to Day {activeDayNumber}...
              </>
            ) : (
              <>
                <Check className="w-4 h-4 stroke-[3]" /> Add to Day {activeDayNumber}
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
};
