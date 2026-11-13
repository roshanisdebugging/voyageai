import React, { useState } from 'react';
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

  const handleConfirmAction = async () => {
    const { tripId, actionType } = confirmActionModal;
    if (actionType === 'DELETE') await deleteTrip(tripId);
    else if (actionType === 'CANCEL') await cancelTrip(tripId);
    else if (actionType === 'ARCHIVE') await archiveTrip(tripId);

    setConfirmActionModal({ isOpen: false, tripId: '', tripTitle: '', actionType: 'DELETE' });
  };

  return (
    <div className="space-y-6 pb-24 max-w-xl mx-auto animate-fadeIn">

      {/* Confirmation Bottom Sheet */}
      {confirmActionModal.isOpen && (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-[#1F2522]/40 backdrop-blur-xs p-4 animate-fadeIn">
          <div className="w-full max-w-md bg-white border border-[#D9DEDA] rounded-3xl p-6 space-y-4 text-center shadow-xl">
            <div className={`w-12 h-12 rounded-2xl flex items-center justify-center mx-auto ${
              confirmActionModal.actionType === 'DELETE'
                ? 'bg-rose-100 text-rose-600'
                : 'bg-amber-100 text-amber-600'
            }`}>
              <AlertTriangle className="w-6 h-6" />
            </div>

            <div className="space-y-1">
              <h3 className="text-lg font-bold text-[#1F2522]">
                {confirmActionModal.actionType === 'DELETE' ? 'Delete Trip?' : confirmActionModal.actionType === 'CANCEL' ? 'Cancel Trip?' : 'Archive Trip?'}
              </h3>
              <p className="text-xs text-[#5F6863]">
                Are you sure you want to {confirmActionModal.actionType.toLowerCase()} <span className="text-[#1F2522] font-semibold">{confirmActionModal.tripTitle}</span>?
              </p>
            </div>

            <div className="space-y-2 pt-2">
              <button
                type="button"
                onClick={handleConfirmAction}
                className={`w-full py-3.5 font-bold text-sm rounded-xl shadow-xs transition-all ${
                  confirmActionModal.actionType === 'DELETE'
                    ? 'bg-rose-600 hover:bg-rose-700 text-white'
                    : 'bg-amber-600 hover:bg-amber-700 text-white'
                }`}
              >
                Confirm {confirmActionModal.actionType}
              </button>
              <button
                type="button"
                onClick={() => setConfirmActionModal({ isOpen: false, tripId: '', tripTitle: '', actionType: 'DELETE' })}
                className="w-full py-2 text-xs text-[#5F6863] hover:text-[#1F2522]"
              >
                Keep Trip
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Header */}
      <div className="flex items-center justify-between pt-1">
        <div>
          <h1 className="text-2xl font-extrabold text-[#1F2522]">My Trips</h1>
          <p className="text-xs text-[#5F6863]">Manage, switch & plan your adventures</p>
        </div>

        <button
          onClick={() => navigate('/trips/new')}
          className="px-3.5 py-2 rounded-xl bg-[#355F58] hover:bg-[#2C504A] text-white font-bold text-xs flex items-center gap-1.5 shadow-xs press-scale"
        >
          <Plus className="w-4 h-4 text-white" />
          <span>New Trip</span>
        </button>
      </div>

      {/* Tab Controls */}
      <div className="flex gap-1.5 p-1.5 rounded-2xl bg-[#F0F2EF] border border-[#D9DEDA] text-xs font-bold overflow-x-auto no-scrollbar">
        {[
          { id: 'ACTIVE', label: 'Active / Planning' },
          { id: 'UPCOMING', label: 'Upcoming' },
          { id: 'PAST', label: 'Past trips' },
          { id: 'ARCHIVED', label: 'Archived' },
        ].map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id as TabId)}
            className={`flex-1 py-2.5 px-3 rounded-xl transition-all whitespace-nowrap text-center ${
              activeTab === tab.id
                ? 'bg-[#355F58] text-white font-extrabold shadow-xs'
                : 'text-[#5F6863] hover:text-[#1F2522]'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Trip List */}
      <div className="space-y-4">
        {filteredTrips.length === 0 ? (
          <div className="bg-white border border-[#D9DEDA] rounded-3xl p-8 text-center space-y-3 shadow-xs">
            <div className="w-12 h-12 rounded-2xl bg-[#F0F2EF] text-[#5F6863] flex items-center justify-center mx-auto">
              <Calendar className="w-6 h-6" />
            </div>
            <h3 className="text-base font-bold text-[#1F2522]">{activeTab === 'PAST' ? 'No past trips yet' : `No ${activeTab.toLowerCase()} trips found`}</h3>
            <p className="text-xs text-[#5F6863] max-w-xs mx-auto font-medium">
              You don't have any trips in this tab right now. Ready to start planning?
            </p>
            <button
              onClick={() => navigate('/trips/new')}
              className="py-3 px-5 rounded-2xl bg-[#355F58] hover:bg-[#2C504A] text-white font-extrabold text-xs inline-flex items-center gap-1.5 shadow-xs press-scale"
            >
              <Plus className="w-4 h-4 text-white" />
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
                  bg-white rounded-3xl overflow-hidden transition-all border shadow-xs
                  ${isCurrent ? 'border-[#355F58]' : 'border-[#D9DEDA] hover:border-[#355F58]/30'}
                `}
              >
                {/* Cover Image */}
                <div className="relative h-36 w-full overflow-hidden bg-[#2C504A]">
                  <SafeImage
                    src={getTripCoverImage(trip)}
                    alt={trip.title}
                    className="w-full h-full object-cover"
                  />
                  <div className="absolute inset-0 bg-gradient-to-t from-white via-white/30 to-transparent" />
                  
                  <div className="absolute top-3 left-3 flex items-center gap-2">
                    <span className={`px-2.5 py-1 rounded-full text-[10px] font-extrabold uppercase tracking-wider backdrop-blur-md ${
                      trip.status === 'ACTIVE'
                        ? 'bg-[#355F58] text-white'
                        : trip.status === 'UPCOMING' || (trip.status as any) === 'CONFIRMED'
                        ? 'bg-[#487C74] text-white'
                        : trip.status === 'COMPLETED'
                        ? 'bg-emerald-700 text-white'
                        : 'bg-[#F0F2EF] text-[#1F2522]'
                    }`}>
                      {trip.status}
                    </span>
                    {isCurrent && (
                      <span className="px-2.5 py-1 rounded-full bg-[#E8F0EE] text-[#355F58] border border-[#355F58]/30 font-extrabold text-[10px] uppercase">
                        Current Context
                      </span>
                    )}
                  </div>
                </div>

                {/* Content */}
                <div className="p-4 space-y-3">
                  <div className="flex items-start justify-between">
                    <div>
                      <h3 className="font-extrabold text-lg text-[#1F2522]">{trip.title}</h3>
                      <div className="flex items-center gap-1.5 text-xs text-[#5F6863] mt-0.5 font-medium">
                        <MapPin className="w-3.5 h-3.5 text-[#355F58] shrink-0" />
                        <span>{trip.destination.name}</span>
                        <span>·</span>
                        <span>{trip.startDate} to {trip.endDate}</span>
                      </div>
                    </div>
                  </div>

                  {/* Actions */}
                  <div className="flex items-center justify-between pt-2 border-t border-[#D9DEDA]">
                    <button
                      onClick={() => {
                        setCurrentTripId(trip.id);
                        navigate('/trip/itinerary');
                      }}
                      className={`px-4 py-2.5 rounded-2xl font-extrabold text-xs flex items-center gap-1.5 press-scale shadow-xs ${
                        isCurrent
                          ? 'bg-[#355F58] text-white hover:bg-[#2C504A]'
                          : 'bg-[#F0F2EF] border border-[#D9DEDA] text-[#355F58] hover:border-[#355F58]/40'
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
                          title="Archive Trip"
                          className="p-2.5 rounded-xl text-[#5F6863] hover:text-amber-700 hover:bg-[#F0F2EF] transition-colors"
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
                        title="Delete Trip"
                        className="p-2.5 rounded-xl text-[#5F6863] hover:text-rose-600 hover:bg-[#F0F2EF] transition-colors"
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
