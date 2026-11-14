import React, { useEffect, useRef, useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useTrip } from '../../features/trip/TripContext';
import { isPastTrip } from '../../features/trip/tripRepository';
import { getTripCoverImage } from '../../utils/imageUtils';
import { SafeImage } from '../common/SafeImage';
import {
  Calendar, MapPin, Plus, AlertTriangle, Archive, Trash2, ArrowRight
} from 'lucide-react';

export const MyTripsPage: React.FC = () => {
  const navigate = useNavigate();
  const { trips, currentTrip, setCurrentTripId, deleteTrip, cancelTrip, archiveTrip } = useTrip();

  type TabId = 'ACTIVE' | 'UPCOMING' | 'PAST' | 'ARCHIVED';
  const location = useLocation();
  const requestedTab = (location.state as { tab?: TabId } | null)?.tab;
  const [activeTab, setActiveTab] = useState<TabId>(requestedTab || 'ACTIVE');

  // Deletion / Cancellation Bottom Sheet Confirmation
  const [confirmActionModal, setConfirmActionModal] = useState<{
    isOpen: boolean;
    tripId: string;
    tripTitle: string;
    actionType: 'DELETE' | 'CANCEL' | 'ARCHIVE';
  }>({
    isOpen: false,
    tripId: '',
    tripTitle: '',
    actionType: 'DELETE',
  });
  const confirmationDialog = useRef<HTMLDialogElement>(null);
  const keepTripButton = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const dialog = confirmationDialog.current;
    if (!dialog) return;

    if (confirmActionModal.isOpen) {
      dialog.showModal();
      keepTripButton.current?.focus();
    } else {
      dialog.close();
    }
  }, [confirmActionModal.isOpen]);

  const filteredTrips = trips.filter(trip => {
    const status = (trip.status || '').toUpperCase();
    const past = isPastTrip(trip);
    if (activeTab === 'ACTIVE') return !past && (status === 'ACTIVE' || status === 'PLANNING');
    if (activeTab === 'UPCOMING') return !past && (status === 'UPCOMING' || status === 'CONFIRMED');
    if (activeTab === 'PAST') return past;
    if (activeTab === 'ARCHIVED') return status === 'ARCHIVED' || status === 'CANCELLED';
    return true;
  });
  // Past trips: newest first (latest end date at the top).
  if (activeTab === 'PAST') {
    filteredTrips.sort((a, b) => (b.endDate || '').localeCompare(a.endDate || ''));
  }

  const closeConfirmation = () => {
    setConfirmActionModal({ isOpen: false, tripId: '', tripTitle: '', actionType: 'DELETE' });
  };

  const handleConfirmAction = async () => {
    const { tripId, actionType } = confirmActionModal;
    if (actionType === 'DELETE') await deleteTrip(tripId);
    else if (actionType === 'CANCEL') await cancelTrip(tripId);
    else if (actionType === 'ARCHIVE') await archiveTrip(tripId);

    closeConfirmation();
  };

  return (
    <div className="mx-auto w-full min-w-0 max-w-xl space-y-6 pb-44 lg:pb-24 animate-fadeIn">

      {/* Confirmation Bottom Sheet */}
      <dialog
        ref={confirmationDialog}
        aria-labelledby="my-trips-confirmation-title"
        aria-describedby="my-trips-confirmation-description"
        onCancel={event => {
          event.preventDefault();
          closeConfirmation();
        }}
        className="fixed inset-x-0 top-auto bottom-4 mx-auto max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] max-w-md overflow-y-auto rounded-3xl border border-(--color-border) bg-(--color-surface) p-6 text-center shadow-xl backdrop:bg-black/55 backdrop:backdrop-blur-xs"
      >
        {confirmActionModal.isOpen && (
          <div className="space-y-4">
            <div className={`w-12 h-12 rounded-2xl flex items-center justify-center mx-auto ${
              confirmActionModal.actionType === 'DELETE'
                ? 'bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-200'
                : 'bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200'
            }`}>
              <AlertTriangle className="w-6 h-6" />
            </div>

            <div className="space-y-1">
              <h3 id="my-trips-confirmation-title" className="text-lg font-bold text-(--color-text-primary)">
                {confirmActionModal.actionType === 'DELETE' ? 'Delete Trip?' : confirmActionModal.actionType === 'CANCEL' ? 'Cancel Trip?' : 'Archive Trip?'}
              </h3>
              <p id="my-trips-confirmation-description" className="text-xs text-(--color-text-secondary) [overflow-wrap:anywhere]">
                Are you sure you want to {confirmActionModal.actionType.toLowerCase()} <span className="text-(--color-text-primary) font-semibold">{confirmActionModal.tripTitle}</span>?
              </p>
            </div>

            <div className="flex flex-col gap-2 pt-2 sm:flex-row-reverse">
              <button
                type="button"
                onClick={handleConfirmAction}
                className={`w-full py-3.5 font-bold text-sm rounded-xl shadow-xs transition-all ${
                  confirmActionModal.actionType === 'DELETE'
                    ? 'bg-rose-700 hover:bg-rose-800 text-white dark:bg-rose-400 dark:text-zinc-950 dark:hover:bg-rose-300'
                    : 'bg-amber-800 hover:bg-amber-900 text-white dark:bg-amber-300 dark:text-zinc-950 dark:hover:bg-amber-200'
                }`}
              >
                Confirm {confirmActionModal.actionType}
              </button>
              <button
                type="button"
                onClick={closeConfirmation}
                ref={keepTripButton}
                className="min-h-11 w-full rounded-xl border border-(--color-text-secondary) px-3 py-2 text-sm font-semibold text-(--color-text-primary) hover:bg-(--color-surface-elevated)"
              >
                Keep Trip
              </button>
            </div>
          </div>
        )}
      </dialog>

      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-3 pt-1">
        <div className="min-w-0">
          <h1 className="text-2xl font-extrabold text-(--color-text-primary)">My Trips</h1>
          <p className="text-xs text-(--color-text-secondary)">Manage, switch & plan your adventures</p>
        </div>

        <button
          onClick={() => navigate('/trips/new')}
          className="min-h-11 px-3.5 py-2 rounded-xl bg-(--color-primary) hover:brightness-95 text-white dark:text-zinc-950 font-bold text-xs flex items-center gap-1.5 shadow-xs press-scale"
        >
          <Plus className="size-4" />
          <span>New Trip</span>
        </button>
      </div>

      {/* Tab Controls */}
      <div role="group" aria-label="Trip status" className="grid grid-cols-2 gap-1.5 p-1.5 rounded-2xl bg-(--color-surface-elevated) border border-(--color-border) text-xs font-bold sm:grid-cols-4">
        {[
          { id: 'ACTIVE', label: 'Active / Planning' },
          { id: 'UPCOMING', label: 'Upcoming' },
          { id: 'PAST', label: 'Past trips' },
          { id: 'ARCHIVED', label: 'Archived' },
        ].map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id as TabId)}
            aria-pressed={activeTab === tab.id}
            className={`min-h-11 min-w-0 py-2.5 px-2 rounded-xl transition-all text-center ${
              activeTab === tab.id
                ? 'bg-(--color-primary) text-white dark:text-zinc-950 font-extrabold shadow-xs'
                : 'text-(--color-text-secondary) hover:text-(--color-text-primary)'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Trip List */}
      <div className="space-y-4">
        {filteredTrips.length === 0 ? (
          <div className="bg-(--color-surface) border border-(--color-border) rounded-3xl p-8 text-center space-y-3 shadow-xs">
            <div className="w-12 h-12 rounded-2xl bg-(--color-surface-elevated) text-(--color-text-secondary) flex items-center justify-center mx-auto">
              <Calendar className="w-6 h-6" />
            </div>
            <h3 className="text-base font-bold text-(--color-text-primary)">{activeTab === 'PAST' ? 'No past trips yet' : `No ${activeTab.toLowerCase()} trips found`}</h3>
            <p className="text-xs text-(--color-text-secondary) max-w-xs mx-auto font-medium">
              You don't have any trips in this tab right now. Ready to start planning?
            </p>
            <button
              onClick={() => navigate('/trips/new')}
              className="min-h-11 py-3 px-5 rounded-2xl bg-(--color-primary) hover:brightness-95 text-white dark:text-zinc-950 font-extrabold text-xs inline-flex items-center gap-1.5 shadow-xs press-scale"
            >
              <Plus className="size-4" />
              <span>Plan a Trip</span>
            </button>
          </div>
        ) : (
          filteredTrips.map(trip => {
            const isCurrent = currentTrip?.id === trip.id;
            return (
              <div
                key={trip.id}
                className={`
                  bg-(--color-surface) rounded-3xl overflow-hidden transition-all border shadow-xs
                  ${isCurrent ? 'border-(--color-primary)' : 'border-(--color-border) hover:border-(--color-primary)'}
                `}
              >
                {/* Cover Image */}
                <div className="relative h-44 w-full overflow-hidden bg-(--color-surface-elevated)">
                  <SafeImage
                    src={getTripCoverImage(trip)}
                    alt={trip.title}
                    className="w-full h-full object-cover"
                  />
                  <div className="absolute inset-0 bg-gradient-to-t from-(--color-surface) via-(--color-surface)/30 to-transparent" />
                  
                  <div className="absolute inset-x-3 bottom-2 flex flex-wrap items-center gap-2">
                    <span className={`px-2.5 py-1 rounded-full text-[10px] font-extrabold uppercase tracking-wider backdrop-blur-md ${
                      trip.status === 'ACTIVE'
                        ? 'bg-(--color-primary) text-white dark:text-zinc-950'
                        : ['UPCOMING', 'CONFIRMED'].includes(trip.status)
                        ? 'bg-sky-100 text-sky-900 dark:bg-sky-950 dark:text-sky-200'
                        : trip.status === 'COMPLETED'
                        ? 'bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200'
                        : 'bg-(--color-surface-elevated) text-(--color-text-primary)'
                    }`}>
                      {trip.status}
                    </span>
                    {isCurrent && (
                      <span className="px-2.5 py-1 rounded-full bg-(--color-surface-elevated) text-(--color-primary) border border-(--color-primary) font-extrabold text-[10px] uppercase">
                        Current Context
                      </span>
                    )}
                  </div>
                </div>

                {/* Content */}
                <div className="p-4 space-y-3">
                  <div>
                    <h3 className="font-extrabold text-lg text-(--color-text-primary) [overflow-wrap:anywhere]">{trip.title}</h3>
                    <div className="mt-0.5 flex flex-wrap items-baseline gap-x-3 gap-y-1 text-xs font-medium text-(--color-text-secondary) [overflow-wrap:anywhere]">
                      <div className="flex min-w-0 items-start gap-1.5">
                        <MapPin className="w-3.5 h-3.5 text-(--color-primary) shrink-0" />
                        <span>{trip.destination.name}</span>
                      </div>
                      <span>{trip.startDate} to {trip.endDate}</span>
                    </div>
                  </div>

                  {/* Actions */}
                  <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-(--color-border)">
                    <button
                      onClick={() => {
                        setCurrentTripId(trip.id);
                        navigate('/trip/itinerary');
                      }}
                      className={`min-h-11 px-4 py-2.5 rounded-2xl font-extrabold text-xs flex items-center gap-1.5 press-scale shadow-xs ${
                        isCurrent
                          ? 'bg-(--color-primary) text-white hover:brightness-95 dark:text-zinc-950'
                          : 'bg-(--color-surface-elevated) border border-(--color-primary) text-(--color-primary) hover:border-(--color-primary)'
                      }`}
                    >
                      <span>View Trip Details</span>
                      <ArrowRight className="w-3.5 h-3.5" />
                    </button>

                    <div className="flex items-center gap-1">
                      {trip.status !== 'ARCHIVED' && (
                        <button
                          onClick={() => setConfirmActionModal({
                            isOpen: true,
                            tripId: trip.id,
                            tripTitle: trip.title,
                            actionType: 'ARCHIVE'
                          })}
                          aria-label="Archive Trip"
                          title="Archive Trip"
                          className="grid size-11 place-items-center rounded-xl border border-(--color-text-secondary) bg-(--color-surface-elevated) text-(--color-text-secondary) hover:text-amber-800 dark:hover:text-amber-300 hover:bg-(--color-surface-elevated) transition-colors"
                        >
                          <Archive className="w-4.5 h-4.5" />
                        </button>
                      )}

                      <button
                        onClick={() => setConfirmActionModal({
                          isOpen: true,
                          tripId: trip.id,
                          tripTitle: trip.title,
                          actionType: 'DELETE'
                        })}
                        aria-label="Delete Trip"
                        title="Delete Trip"
                        className="grid size-11 place-items-center rounded-xl border border-(--color-text-secondary) bg-(--color-surface-elevated) text-(--color-text-secondary) hover:text-rose-800 dark:hover:text-rose-300 hover:bg-(--color-surface-elevated) transition-colors"
                      >
                        <Trash2 className="w-4.5 h-4.5" />
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>

    </div>
  );
};
