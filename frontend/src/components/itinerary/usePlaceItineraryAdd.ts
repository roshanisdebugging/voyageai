import { useMemo, useState } from 'react';
import { useApp } from '../../context/AppContext';
import { useTrip } from '../../features/trip/TripContext';
import { getApiBaseUrl, DEFAULT_HEADERS, getAuthHeaders } from '../../config/apiConfig';
import { sanitizeLocationName } from '../../utils/locationSanitizer';
import type { ItineraryDayOption } from './AddToItineraryModal';

/** The place fields "Add to Itinerary" needs. */
export interface ItineraryPlace {
  id: string;
  name: string;
  category?: string;
  address?: string;
  price_approx?: string;
}

/**
 * "Add to Itinerary" with the day picker, shared by the map cards and the place details page.
 * Same request as before (POST /api/trips/itinerary/add, owner-checked on the server).
 * Usage: const add = usePlaceItineraryAdd(); add.open(place); <AddToItineraryModal {...add.modalProps} />
 */
export function usePlaceItineraryAdd() {
  const { userLocationName } = useApp();
  const { currentTrip, currentItinerary, refetchItinerary } = useTrip();
  const [selected, setSelected] = useState<ItineraryPlace | null>(null);
  const [addedPlaceDays, setAddedPlaceDays] = useState<Map<string, number>>(new Map());
  const [isSubmitting, setIsSubmitting] = useState(false);

  const days: ItineraryDayOption[] = useMemo(() => {
    if (currentItinerary?.days && currentItinerary.days.length > 0) {
      return currentItinerary.days.map((d) => ({ id: d.id, dayNumber: d.dayNumber, title: d.title || `Day ${d.dayNumber}` }));
    }
    const totalDays = currentTrip?.totalDays || 3;
    return Array.from({ length: Math.max(totalDays, 1) }, (_, i) => ({ id: `day_${i + 1}`, dayNumber: i + 1, title: `Day ${i + 1} Highlights` }));
  }, [currentItinerary, currentTrip]);

  const confirm = async (dayId: string, timeSlot: string) => {
    if (!selected) return;
    setIsSubmitting(true);
    const dayNumber = days.find((d) => d.id === dayId)?.dayNumber || 1;
    // First number of the price text ("₹500 - ₹1,500" -> 500). Unknown price -> 0.
    const firstNumber = (selected.price_approx || '').match(/\d[\d,]*/);
    const costInt = firstNumber ? parseInt(firstNumber[0].replace(/,/g, ''), 10) : 0;
    const loc = sanitizeLocationName(selected.address || userLocationName);
    const payload = {
      trip_id: currentTrip?.id || 'active_trip',
      destination: currentTrip?.destination?.name || userLocationName || 'Local Area',
      item_id: selected.id,
      day_id: dayId,
      day_number: dayNumber,
      time_slot: timeSlot,
      title: selected.name,
      location: loc,
      location_name: loc,
      tag: selected.category || 'spotlight',
      price: selected.price_approx || undefined,
      estimated_cost_inr: costInt,
      activity_type: selected.category || 'spotlight',
      is_confirmed: true,
    };
    try {
      const res = await fetch(`${getApiBaseUrl()}/api/trips/itinerary/add`, {
        method: 'POST',
        headers: { ...DEFAULT_HEADERS, ...getAuthHeaders() },
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        setAddedPlaceDays((prev) => new Map(prev).set(selected.id, dayNumber));
        setSelected(null);
        if (refetchItinerary) await refetchItinerary(currentTrip?.id || payload.trip_id);
      }
    } catch (err) {
      console.warn('[ITINERARY] Add to itinerary error:', err);
    } finally {
      setIsSubmitting(false);
    }
  };

  return {
    open: (place: ItineraryPlace) => setSelected(place),
    addedPlaceDays,
    modalProps: {
      isOpen: Boolean(selected),
      onClose: () => { if (!isSubmitting) setSelected(null); },
      itemTitle: selected?.name || '',
      days,
      isSubmitting,
      onConfirm: confirm,
      category: selected?.category,
      location: sanitizeLocationName(selected?.address || userLocationName),
      price: selected?.price_approx,
    },
  };
}
