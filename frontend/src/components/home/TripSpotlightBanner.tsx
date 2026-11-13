import React, { useEffect, useState, useRef, useMemo } from 'react';
import { Calendar, MapPin, Plus, Check, Loader2, Clock, AlertCircle } from 'lucide-react';
import { getApiBaseUrl, DEFAULT_FETCH_OPTIONS, getAuthHeaders } from '../../config/apiConfig';
import { MONTHS, formatDateRange, parseISODate, tripStatus } from './tripDates';
import { isMockPayload } from '../../utils/mockIndicator';
import { MockCardAlert } from '../common/MockCardAlert';
import { AddToItineraryModal, type ItineraryDayOption } from '../itinerary/AddToItineraryModal';
import { useTrip } from '../../features/trip/TripContext';

interface Activity {
  id: string;
  title: string;
  location: string;
  tag: string;
  cost: number;
  duration?: string;
  category?: string;
  description?: string;
  coordinates?: [number, number];
  photos?: string[];
}

interface UpcomingEvent {
  id: string;
  title: string;
  date: string;
  location: string;
  price: number;
  tag?: string;
  category?: string;
  description?: string;
  time?: string;
  image?: string;
}

interface SpotlightData {
  destination: string;
  overview: string;
  activities: Activity[];
  events: UpcomingEvent[];
  region: string;
}

type AddState = 'idle' | 'adding' | 'added' | 'failed';

const FOCUS =
  'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#355F58]';

const AddButton: React.FC<{ title: string; state: AddState; onClick: () => void }> = ({ title, state, onClick }) => {
  const styles: Record<AddState, string> = {
    idle: 'border border-[#355F58] text-[#355F58] hover:bg-[#E8F0EE]',
    adding: 'border border-[#355F58] text-[#355F58]',
    added: 'border border-[#355F58] bg-[#355F58] text-white',
    failed: 'border border-[#B42318] text-[#B42318] hover:bg-[#FEF3F2]',
  };

  return (
    <button
      type="button"
      disabled={state === 'added' || state === 'adding'}
      onClick={onClick}
      aria-label={
        state === 'added'
          ? `${title} added to itinerary`
          : state === 'failed'
            ? `Couldn't add ${title}. Try again`
            : `Add ${title} to itinerary`
      }
      className={`min-h-[44px] shrink-0 px-3.5 rounded-xl text-xs font-bold flex items-center justify-center gap-1.5 transition-colors press-scale ${styles[state]} ${FOCUS}`}
    >
      {state === 'adding' ? (
        <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
      ) : state === 'added' ? (
        <>
          <Check className="w-4 h-4" aria-hidden="true" /> Added
        </>
      ) : state === 'failed' ? (
        <>Try again</>
      ) : (
        <>
          <Plus className="w-4 h-4" aria-hidden="true" /> Add
        </>
      )}
    </button>
  );
};

const spotlightCache = new Map<string, SpotlightData>();

export const TripSpotlightBanner: React.FC<{
  destination?: string;
  startDate?: string;
  endDate?: string;
  /** Pre-formatted fallback, shown only when startDate can't be read. */
  dates?: string;
  isLocalMode?: boolean;
  latitude?: number;
  longitude?: number;
}> = ({ destination, startDate, endDate, dates, isLocalMode = false, latitude, longitude }) => {
  // Quantize coordinates to ~10km (0.1 deg) so continuous GPS ticks never trigger re-fetching
  const coarseLat = latitude !== undefined ? Number(latitude.toFixed(1)) : undefined;
  const coarseLng = longitude !== undefined ? Number(longitude.toFixed(1)) : undefined;
  const cleanDest = destination?.trim();
  const hasTarget = Boolean(cleanDest || (coarseLat !== undefined && coarseLng !== undefined));

  const fetchKey = cleanDest
    ? `dest:${cleanDest.toLowerCase()}`
    : (coarseLat !== undefined && coarseLng !== undefined ? `geo:${coarseLat}_${coarseLng}` : '');

  const { currentTrip, currentItinerary, refetchItinerary } = useTrip();

  const [data, setData] = useState<SpotlightData | null>(() => {
    return fetchKey ? spotlightCache.get(fetchKey) || null : null;
  });
  const [loading, setLoading] = useState<boolean>(Boolean(hasTarget && !data));
  const [addingId, setAddingId] = useState<string | null>(null);
  const [failedId, setFailedId] = useState<string | null>(null);
  const [addedIds, setAddedIds] = useState<Record<string, boolean>>({});
  const [expanded, setExpanded] = useState(false);

  // Modal State
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [selectedItemForModal, setSelectedItemForModal] = useState<(Activity | UpcomingEvent) | null>(null);
  const [selectedItemType, setSelectedItemType] = useState<'activity' | 'event'>('activity');
  const [isSubmittingModal, setIsSubmittingModal] = useState(false);
  const [feedbackToast, setFeedbackToast] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  const modalDays: ItineraryDayOption[] = useMemo(() => {
    if (currentItinerary?.days && currentItinerary.days.length > 0) {
      return currentItinerary.days.map((d) => ({
        id: d.id,
        dayNumber: d.dayNumber,
        title: d.title || `Day ${d.dayNumber}`,
      }));
    }
    const totalDays = currentTrip?.totalDays || 3;
    return Array.from({ length: Math.max(totalDays, 1) }, (_, i) => ({
      id: `day_${i + 1}`,
      dayNumber: i + 1,
      title: `Day ${i + 1} Highlights`,
    }));
  }, [currentItinerary, currentTrip]);

  const lastFetchedKeyRef = useRef<string>('');

  useEffect(() => {
    if (!hasTarget || !fetchKey) {
      setLoading(false);
      return;
    }

    if (fetchKey === lastFetchedKeyRef.current && data) {
      return;
    }

    if (spotlightCache.has(fetchKey)) {
      setData(spotlightCache.get(fetchKey)!);
      setLoading(false);
      lastFetchedKeyRef.current = fetchKey;
      return;
    }

    let isMounted = true;
    if (!data) {
      setLoading(true);
    }

    const baseUrl = getApiBaseUrl();
    const queryParams: string[] = [];

    if (latitude !== undefined && longitude !== undefined) {
      queryParams.push(`lat=${latitude}&lng=${longitude}`);
    }

    if (cleanDest) {
      queryParams.push(`destination=${encodeURIComponent(cleanDest)}`);
    }

    const endpoint = queryParams.length > 0
      ? `${baseUrl}/api/trips/highlights?${queryParams.join('&')}`
      : `${baseUrl}/api/trips/highlights`;

    fetch(endpoint, { ...DEFAULT_FETCH_OPTIONS })
      .then((res) => {
        if (!res.ok) {
          throw new Error(`Highlights API failed with status ${res.status}`);
        }
        return res.json();
      })
      .then((json: SpotlightData) => {
        if (isMounted) {
          spotlightCache.set(fetchKey, json);
          lastFetchedKeyRef.current = fetchKey;
          setData(json);
        }
      })
      .catch((err) => {
        console.error('❌ Error loading spotlight:', err);
      })
      .finally(() => {
        if (isMounted) {
          setLoading(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [fetchKey, cleanDest, latitude, longitude]);

  const handleOpenAddModal = (item: Activity | UpcomingEvent, itemType: 'activity' | 'event') => {
    setSelectedItemForModal(item);
    setSelectedItemType(itemType);
    setIsModalOpen(true);
  };

  const handleConfirmAddToItinerary = async (dayId: string, timeSlot: string) => {
    if (!selectedItemForModal) return;
    setIsSubmittingModal(true);
    setAddingId(selectedItemForModal.id);
    setFailedId(null);

    const targetDay = modalDays.find((d) => d.id === dayId);
    const dayNumber = targetDay?.dayNumber || 1;
    const priceStr = 'cost' in selectedItemForModal ? String(selectedItemForModal.cost) : String(selectedItemForModal.price);
    const digits = priceStr.replace(/[^\d]/g, '');
    const costInt = digits ? parseInt(digits, 10) : 0;
    const loc = 'location' in selectedItemForModal ? selectedItemForModal.location : (data?.destination || destination || 'Local Area');

    const payload = {
      trip_id: currentTrip?.id || 'active_trip',
      destination: data?.destination || destination || currentTrip?.destination?.name || 'Curated Trip',
      item_id: selectedItemForModal.id,
      day_id: dayId,
      day_number: dayNumber,
      time_slot: timeSlot,
      title: selectedItemForModal.title,
      location: loc,
      location_name: loc,
      tag: ('tag' in selectedItemForModal && selectedItemForModal.tag) ? selectedItemForModal.tag : (selectedItemType === 'event' ? 'EVENT' : 'SIGHTSEEING'),
      price: priceStr,
      estimated_cost_inr: costInt,
      activity_type: ('tag' in selectedItemForModal && selectedItemForModal.tag) ? selectedItemForModal.tag : (selectedItemType === 'event' ? 'event' : 'spotlight'),
      is_confirmed: true,
    };

    const baseUrl = getApiBaseUrl();
    try {
      const res = await fetch(`${baseUrl}/api/trips/itinerary/add`, {
        ...DEFAULT_FETCH_OPTIONS,
        method: 'POST',
        headers: {
          ...DEFAULT_FETCH_OPTIONS.headers,
          ...getAuthHeaders(),
        },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        let detail = `Server responded with status ${res.status}`;
        try {
          const errJson = await res.json();
          if (errJson.detail) detail = errJson.detail;
          else if (errJson.message) detail = errJson.message;
        } catch (_) {}
        throw new Error(detail);
      }

      setAddedIds((prev) => ({ ...prev, [selectedItemForModal.id]: true }));
      setIsModalOpen(false);
      setFeedbackToast({
        type: 'success',
        message: `Added "${selectedItemForModal.title}" to Day ${dayNumber} (${timeSlot})!`,
      });
      setTimeout(() => setFeedbackToast(null), 3500);

      // Revalidate itinerary cache & state without full page reload
      if (refetchItinerary) {
        await refetchItinerary(currentTrip?.id);
      }
    } catch (err: any) {
      console.error('❌ Failed to add to itinerary:', err);
      setFailedId(selectedItemForModal.id);
      setFeedbackToast({
        type: 'error',
        message: err.message || 'Failed to add activity. Please try again.',
      });
      setTimeout(() => setFeedbackToast(null), 4000);
    } finally {
      setIsSubmittingModal(false);
      setAddingId(null);
    }
  };

  const stateFor = (id: string): AddState =>
    addedIds[id] ? 'added' : addingId === id ? 'adding' : failedId === id ? 'failed' : 'idle';

  if (!cleanDest && (latitude === undefined || longitude === undefined)) {
    return null; // Don't fetch default mock Kolkata/Goa highlights
  }

  if (loading) {
    return (
      <div role="status">
        <span className="sr-only">Loading highlights for {destination || 'your location'}</span>
        <div className="h-44 rounded-3xl bg-[#1F3B37]/90 animate-pulse motion-reduce:animate-none" />
        <div className="-mt-11 px-3 flex gap-3 overflow-hidden">
          {[0, 1].map((i) => (
            <div
              key={i}
              className="h-36 w-60 shrink-0 rounded-2xl bg-[#E9ECE8] border border-[#D9DEDA] animate-pulse motion-reduce:animate-none"
            />
          ))}
        </div>
      </div>
    );
  }

  if (!data) return null;

  const activities = data.activities || [];
  const events = data.events || [];

  if (activities.length === 0 && events.length === 0) return null;

  const dateLabel = formatDateRange(startDate, endDate) ?? dates ?? null;
  const status = tripStatus(startDate, endDate);

  return (
    <section aria-label={`Highlights for ${data.destination}`} className="w-full max-w-full">
      {/* Destination panel */}
      <div className="relative overflow-hidden rounded-3xl bg-[#1F3B37] text-white px-5 pt-5 pb-16">
        <svg
          aria-hidden="true"
          viewBox="0 0 200 200"
          fill="none"
          stroke="currentColor"
          strokeWidth="1"
          className="pointer-events-none absolute -right-20 -top-20 h-72 w-72 text-white/10"
        >
          <circle cx="100" cy="100" r="28" />
          <circle cx="100" cy="100" r="52" />
          <circle cx="100" cy="100" r="76" />
          <circle cx="100" cy="100" r="100" />
        </svg>

        <div className="relative flex items-start justify-between gap-3">
          <p className="text-sm font-medium text-[#A9C4BE]">{isLocalMode ? 'Local highlights' : 'Active itinerary'}</p>
          {status && (
            <span className="shrink-0 rounded-full bg-white/10 px-3 py-1 text-xs font-semibold">{status}</span>
          )}
        </div>

        <h2 className="relative mt-2 text-4xl font-extrabold leading-none tracking-tight">{data.destination}</h2>

        {dateLabel && (
          <p className="relative mt-3 flex items-center gap-1.5 text-sm font-medium text-[#CFE1DC]">
            <Calendar className="w-4 h-4" aria-hidden="true" />
            {dateLabel}
          </p>
        )}

        {data.overview && (
          <div className="relative mt-3 max-w-prose">
            <p className={`text-sm leading-relaxed text-[#BFD3CE] ${expanded ? '' : 'line-clamp-2'}`}>{data.overview}</p>
            {data.overview.length > 110 && (
              <button
                type="button"
                onClick={() => setExpanded((v) => !v)}
                aria-expanded={expanded}
                className="mt-1 py-1.5 text-xs font-semibold text-white underline underline-offset-4 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
              >
                {expanded ? 'Show less' : 'Read more'}
              </button>
            )}
          </div>
        )}
      </div>

      {/* Highlights sit on the panel's lower edge */}
      <ul className="relative -mt-11 flex list-none gap-3 overflow-x-auto px-3 pb-2 scroll-px-3 snap-x snap-mandatory scrollbar-none">
        {activities.map((act) => {
          if (isMockPayload(act)) {
            return (
              <li key={act.id} className="w-60 sm:w-64 shrink-0 snap-start">
                <MockCardAlert
                  title={act.title}
                  location={act.location}
                  className="h-full"
                />
              </li>
            );
          }

          return (
            <li key={act.id} className="w-60 sm:w-64 shrink-0 snap-start">
              <article className="h-full flex flex-col gap-3 rounded-2xl bg-white border border-[#D9DEDA] p-4 shadow-[0_2px_8px_rgba(31,37,34,0.06)]">
                <div>
                  <p className="text-xs font-semibold text-[#355F58] truncate">{act.tag || 'Must visit'}</p>
                  <h3 className="mt-1 min-h-[2.75rem] text-base font-bold leading-snug text-[#1F2522] line-clamp-2">
                    {act.title}
                  </h3>
                </div>

                <p className="flex items-center gap-1.5 text-xs text-[#5F6863]">
                  <MapPin className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
                  <span className="line-clamp-1">{act.location}</span>
                </p>

                <div className="mt-auto flex items-end justify-between gap-2 border-t border-[#E7EBE8] pt-3">
                  <div>
                    <p className="text-sm font-bold text-[#1F2522]">{act.cost === 0 ? 'Free' : `₹${act.cost}`}</p>
                    {act.duration && (
                      <p className="mt-0.5 flex items-center gap-1 text-xs text-[#5F6863]">
                        <Clock className="w-3 h-3 shrink-0" aria-hidden="true" />
                        {act.duration}
                      </p>
                    )}
                  </div>
                  <AddButton
                    title={act.title}
                    state={stateFor(act.id)}
                    onClick={() => handleOpenAddModal(act, 'activity')}
                  />
                </div>
              </article>
            </li>
          );
        })}

        {events.map((evt) => {
          if (isMockPayload(evt)) {
            return (
              <li key={evt.id} className="w-60 sm:w-64 shrink-0 snap-start">
                <MockCardAlert
                  title={evt.title}
                  location={evt.location}
                  className="h-full"
                />
              </li>
            );
          }

          const when = parseISODate(evt.date);
          return (
            <li key={evt.id} className="w-60 sm:w-64 shrink-0 snap-start">
              <article className="h-full flex flex-col gap-3 rounded-2xl bg-white border border-[#D9DEDA] p-4 shadow-[0_2px_8px_rgba(31,37,34,0.06)]">
                <div className="flex items-start gap-3">
                  {when && (
                    <div
                      aria-hidden="true"
                      className="shrink-0 w-11 rounded-lg bg-[#FBF3DF] py-1.5 text-center text-[#5A4210]"
                    >
                      <div className="text-[11px] font-semibold leading-none">{MONTHS[when.getMonth()]}</div>
                      <div className="mt-1 text-lg font-bold leading-none">{when.getDate()}</div>
                    </div>
                  )}
                  <div className="min-w-0">
                    <p className="text-xs font-semibold text-[#8A5A00]">Event</p>
                    <h3 className="mt-1 text-base font-bold leading-snug text-[#1F2522] line-clamp-2">
                      {when && <span className="sr-only">{evt.date}: </span>}
                      {evt.title}
                    </h3>
                  </div>
                </div>

                <div className="space-y-1 text-xs text-[#5F6863]">
                  {!when && evt.date && (
                    <p className="flex items-center gap-1.5">
                      <Calendar className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
                      {evt.date}
                    </p>
                  )}
                  {evt.time && (
                    <p className="flex items-center gap-1.5">
                      <Clock className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
                      {evt.time}
                    </p>
                  )}
                  <p className="flex items-center gap-1.5">
                    <MapPin className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
                    <span className="line-clamp-1">{evt.location}</span>
                  </p>
                </div>

                <div className="mt-auto flex items-center justify-between gap-2 border-t border-[#E7EBE8] pt-3">
                  <p className="text-sm font-bold text-[#1F2522]">{evt.price === 0 ? 'Free' : `₹${evt.price}`}</p>
                  <AddButton
                    title={evt.title}
                    state={stateFor(evt.id)}
                    onClick={() => handleOpenAddModal(evt, 'event')}
                  />
                </div>
              </article>
            </li>
          );
        })}
      </ul>

      {/* Floating Feedback Toast Notification */}
      {feedbackToast && (
        <div
          role="alert"
          className={`fixed bottom-6 left-1/2 -translate-x-1/2 z-[10000] px-4 py-2.5 rounded-2xl text-xs font-black flex items-center gap-2 shadow-2xl animate-bounce ${
            feedbackToast.type === 'success'
              ? 'bg-emerald-500 text-slate-950 shadow-emerald-500/25'
              : 'bg-rose-500 text-white shadow-rose-500/25'
          }`}
        >
          {feedbackToast.type === 'success' ? (
            <Check className="w-4 h-4 stroke-[3]" />
          ) : (
            <AlertCircle className="w-4 h-4" />
          )}
          <span>{feedbackToast.message}</span>
        </div>
      )}

      {/* Add To Itinerary Day/Time Selection Modal */}
      <AddToItineraryModal
        isOpen={isModalOpen}
        onClose={() => {
          if (!isSubmittingModal) {
            setIsModalOpen(false);
            setSelectedItemForModal(null);
          }
        }}
        onConfirm={handleConfirmAddToItinerary}
        itemTitle={selectedItemForModal?.title || ''}
        days={modalDays}
        isSubmitting={isSubmittingModal}
        category={selectedItemForModal?.tag || selectedItemForModal?.category || (selectedItemType === 'event' ? 'Event' : 'Activity')}
        location={'location' in (selectedItemForModal || {}) ? (selectedItemForModal as any).location : ''}
        price={'cost' in (selectedItemForModal || {}) ? (selectedItemForModal as any).cost : (selectedItemForModal as any)?.price}
      />
    </section>
  );
};
