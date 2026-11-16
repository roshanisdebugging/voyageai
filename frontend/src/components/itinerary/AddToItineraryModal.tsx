import React, { useState, useEffect } from 'react';
import { X, Calendar, Clock, Sparkles, Check, Loader2, MapPin, Sunrise, Sun, Sunset, Moon } from 'lucide-react';
import { Portal } from '../common/Portal';
import './itineraryDialog.css';

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
    icon: Sunrise,
    range: '9:00 AM - 12:00 PM',
    description: 'Fresh starts, nature & sightseeing',
  },
  {
    id: 'Afternoon',
    label: 'Afternoon',
    icon: Sun,
    range: '12:00 PM - 04:00 PM',
    description: 'Museums, dining & indoor culture',
  },
  {
    id: 'Evening',
    label: 'Evening',
    icon: Sunset,
    range: '04:00 PM - 08:00 PM',
    description: 'Sunsets, markets & walks',
  },
  {
    id: 'Night',
    label: 'Night',
    icon: Moon,
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

  const dialogId = React.useId();
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

  // Portal: inside an animated page (e.g. the place details page) the dialog would otherwise sit under the
  // bottom nav, which then catches the "Add to Day" tap.
  return (
    <Portal>
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby={dialogId}
      className="itinerary-dialog fixed inset-0 z-[9999] flex items-end sm:items-center justify-center p-0 sm:p-4 animate-fadeIn"
      onClick={onClose}
    >
      <div
        className="itinerary-dialog__panel itinerary-dialog__panel--sheet itinerary-dialog__scroll w-full max-w-lg rounded-t-[20px] sm:rounded-[20px] p-5 sm:p-6 space-y-5 animate-slideUp overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="itinerary-dialog__divider flex items-start justify-between border-b pb-4 gap-3">
          <div className="space-y-1 min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="itinerary-dialog__label px-2.5 py-0.5 rounded-full text-[10px] font-extrabold uppercase tracking-wide">
                {displayCategory}
              </span>
              {displayPrice && (
                <span className="itinerary-dialog__price px-2 py-0.5 rounded-md text-[11px] font-bold tabular-nums">
                  {typeof displayPrice === 'number' ? `₹${displayPrice}` : displayPrice}
                </span>
              )}
            </div>

            <h3
              id={dialogId}
              className="text-lg font-black leading-tight tracking-tight wrap-anywhere pt-1"
            >
              {displayTitle}
            </h3>

            {displayLocation && (
              <p className="itinerary-dialog__muted text-xs flex items-center gap-1 truncate pt-0.5">
                <MapPin className="itinerary-dialog__accent w-3.5 h-3.5 shrink-0" />
                <span className="truncate">{displayLocation}</span>
              </p>
            )}
          </div>

          <button
            type="button"
            onClick={onClose}
            disabled={isBusy}
            aria-label="Close modal"
            className="itinerary-dialog__button grid place-items-center min-w-11 rounded-2xl transition-colors press-scale shrink-0 disabled:opacity-50"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* 1. Day Selector */}
        <div role="group" aria-labelledby={`${dialogId}-day-label`} className="space-y-2.5">
          <p id={`${dialogId}-day-label`} className="text-[13px] font-bold flex items-center gap-1.5">
            <Calendar className="itinerary-dialog__accent w-4 h-4" />
            1. Select Trip Day
          </p>

          <div className="itinerary-dialog__scroll grid grid-cols-2 sm:grid-cols-3 gap-2 max-h-48 overflow-y-auto pr-1">
            {effectiveDays.map((d) => {
              const isSelected = selectedDayId === d.id;
              return (
                <button
                  key={d.id}
                  type="button"
                  onClick={() => setSelectedDayId(d.id)}
                  aria-pressed={isSelected}
                  className="itinerary-dialog__button press-scale p-3 rounded-2xl text-left transition-colors flex flex-col justify-between gap-1 min-w-0"
                >
                  <div className="flex items-center justify-between w-full">
                    <span className="itinerary-dialog__accent text-xs font-black">
                      Day {d.dayNumber}
                    </span>
                    {isSelected && <Check className="itinerary-dialog__accent w-3.5 h-3.5 stroke-[3] shrink-0" />}
                  </div>
                  <span className="itinerary-dialog__muted text-[11px] font-semibold wrap-anywhere">
                    {d.title || `Day ${d.dayNumber}`}
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        {/* 2. Time Slot Selector */}
        <div role="group" aria-labelledby={`${dialogId}-slot-label`} className="space-y-2.5">
          <p id={`${dialogId}-slot-label`} className="text-[13px] font-bold flex items-center gap-1.5">
            <Clock className="itinerary-dialog__time w-4 h-4" />
            2. Choose Time Slot
          </p>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {TIME_SLOT_OPTIONS.map((slot) => {
              const isSelected = selectedSlot === slot.id;
              const Icon = slot.icon;
              return (
                <button
                  key={slot.id}
                  type="button"
                  onClick={() => setSelectedSlot(slot.id)}
                  aria-pressed={isSelected}
                  className="itinerary-dialog__button press-scale p-3 rounded-2xl text-left transition-colors flex items-start gap-3 min-w-0"
                >
                  <Icon className="itinerary-dialog__time w-5 h-5 shrink-0" aria-hidden="true" />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-extrabold">{slot.label}</span>
                      {isSelected && <Check className="itinerary-dialog__accent w-3.5 h-3.5 stroke-[3] shrink-0" />}
                    </div>
                    <p className="itinerary-dialog__time text-[11px] tabular-nums mt-0.5">{slot.range}</p>
                    <p className="itinerary-dialog__muted text-[11px] mt-0.5">{slot.description}</p>
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        {/* Target Confirmation Summary */}
        <div className="itinerary-dialog__elevated px-3.5 py-2.5 rounded-2xl flex flex-wrap items-center justify-between gap-2 text-xs">
          <span className="itinerary-dialog__muted font-medium">Adding To:</span>
          <span className="itinerary-dialog__accent font-extrabold flex items-center gap-1" aria-live="polite">
            <Sparkles className="itinerary-dialog__time w-3.5 h-3.5" />
            Day {activeDayNumber} · {selectedSlot}
          </span>
        </div>

        {/* Action Buttons */}
        <div className="flex items-center gap-3 pt-2">
          <button
            type="button"
            onClick={onClose}
            disabled={isBusy}
            className="itinerary-dialog__button flex-1 py-2.5 px-3 rounded-2xl font-bold text-[13px] transition-colors press-scale disabled:opacity-50"
          >
            Cancel
          </button>

          <button
            type="button"
            onClick={handleConfirmClick}
            disabled={isBusy}
            className="itinerary-dialog__button itinerary-dialog__button--primary flex-2 py-2.5 px-3 rounded-2xl font-black text-[13px] flex items-center justify-center gap-2 transition-colors press-scale disabled:opacity-50"
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
    </Portal>
  );
};
