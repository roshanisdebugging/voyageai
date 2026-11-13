import React, { useState, useEffect } from 'react';
import { useToast } from '../common/UndoToast';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft, Heart, MapPin, Star, Navigation, Trash2, Compass, Check, Loader2, ExternalLink } from 'lucide-react';
import { getSavedPlaces, removeSavedPlace, savePlace, type SavedPlace } from '../../services/savedPlacesApi';

export const SavedPlacesPage: React.FC = () => {
  const navigate = useNavigate();

  const [places, setPlaces] = useState<SavedPlace[]>([]);
  const { showToast } = useToast();
  const [loading, setLoading] = useState<boolean>(true);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState<boolean>(false);

  const fetchPlaces = async () => {
    setLoading(true);
    try {
      const data = await getSavedPlaces();
      setPlaces(data);
    } catch (err) {
      console.warn('[SAVED PLACES LOAD ERROR]:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPlaces();
  }, []);

  const handleRemoveConfirm = async () => {
    if (!confirmDeleteId || isDeleting) return;
    setIsDeleting(true);

    const targetPlace = places.find(p => p.place_id === confirmDeleteId || p.id === confirmDeleteId);
    const placeId = targetPlace?.place_id || confirmDeleteId;

    try {
      await removeSavedPlace(placeId);
      setPlaces(prev => prev.filter(p => p.place_id !== placeId && p.id !== placeId));
      setConfirmDeleteId(null);
      if (targetPlace) {
        showToast({
          message: `Removed ${targetPlace.title || 'place'}`,
          undo: async () => {
            await savePlace(targetPlace);
            setPlaces(prev => [targetPlace, ...prev]);
          },
        });
      }
    } catch (err: any) {
      setToastMessage(err.message || 'Failed to remove place');
    } finally {
      setIsDeleting(false);
      setTimeout(() => setToastMessage(null), 3000);
    }
  };

  const handleOpenDirections = (place: SavedPlace) => {
    const query = place.location_name || place.title;
    const url = `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`;
    window.open(url, '_blank', 'noopener,noreferrer');
  };

  return (
    <div className="space-y-6 pb-28 max-w-xl mx-auto animate-fadeIn relative">
      {/* Floating Toast Notification */}
      {toastMessage && (
        <div className="fixed top-5 left-1/2 -translate-x-1/2 z-[1000] px-4 py-2.5 rounded-2xl bg-[#1F2522] text-white text-xs font-bold shadow-xl animate-fadeIn flex items-center gap-2 border border-white/10">
          <Check className="w-4 h-4 text-teal-400 shrink-0" />
          <span>{toastMessage}</span>
        </div>
      )}

      {/* Confirmation Modal */}
      {confirmDeleteId && (
        <div className="fixed inset-0 z-[99999] flex items-center justify-center p-4 bg-[#1F2522]/50 backdrop-blur-xs animate-fadeIn">
          <div className="bg-white rounded-3xl p-6 max-w-sm w-full border border-[#D9DEDA] shadow-2xl space-y-4 animate-slideUp text-center">
            <div className="w-12 h-12 rounded-2xl bg-rose-50 text-rose-600 border border-rose-200 flex items-center justify-center mx-auto">
              <Trash2 className="w-6 h-6" />
            </div>
            <div>
              <h3 className="text-base font-extrabold text-[#1F2522]">Remove from saved places?</h3>
              <p className="text-xs text-[#5F6863] mt-1">
                This spot will be removed from your favorites and Redis cache will be updated.
              </p>
            </div>
            <div className="grid grid-cols-2 gap-2.5 pt-1">
              <button
                type="button"
                onClick={() => setConfirmDeleteId(null)}
                disabled={isDeleting}
                className="py-3 rounded-xl bg-[#F0F2EF] hover:bg-[#E8F0EE] text-[#1F2522] font-bold text-xs transition-colors"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleRemoveConfirm}
                disabled={isDeleting}
                className="py-3 rounded-xl bg-rose-600 hover:bg-rose-700 text-white font-bold text-xs shadow-xs transition-colors flex items-center justify-center gap-1.5"
              >
                {isDeleting ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Remove'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Top Header */}
      <div className="flex items-center gap-3 pt-1">
        <button
          type="button"
          onClick={() => navigate('/more')}
          className="w-10 h-10 rounded-2xl bg-white border border-[#D9DEDA] hover:border-[#355F58]/40 flex items-center justify-center text-[#1F2522] press-scale shadow-xs shrink-0"
          aria-label="Back to more options"
        >
          <ArrowLeft className="w-5 h-5" />
        </button>
        <div className="min-w-0">
          <h1 className="text-xl sm:text-2xl font-extrabold text-[#1F2522] truncate">Saved Places</h1>
          <p className="text-xs text-[#5F6863] font-medium">Your bookmarked spots, hotels, & dining</p>
        </div>
      </div>

      {/* Loading State */}
      {loading ? (
        <div className="py-20 text-center space-y-3 bg-white rounded-3xl border border-[#D9DEDA] p-8 shadow-xs">
          <Loader2 className="w-8 h-8 text-[#355F58] animate-spin mx-auto" />
          <p className="text-sm font-bold text-[#1F2522]">Loading your saved places...</p>
        </div>
      ) : places.length === 0 ? (
        /* Empty State */
        <div className="bg-white rounded-3xl border border-[#D9DEDA] p-8 text-center space-y-5 shadow-xs py-14">
          <div className="w-16 h-16 rounded-full bg-rose-50 text-rose-500 border border-rose-200 flex items-center justify-center mx-auto">
            <Heart className="w-8 h-8" />
          </div>
          <div className="space-y-1.5 max-w-xs mx-auto">
            <h2 className="text-lg font-extrabold text-[#1F2522]">No saved places yet</h2>
            <p className="text-xs text-[#5F6863] leading-relaxed">
              Explore spots, attractions, and hotels across destinations and tap the heart icon to save them here.
            </p>
          </div>
          <button
            type="button"
            onClick={() => navigate('/explore')}
            className="inline-flex items-center gap-2 px-5 py-3 rounded-2xl bg-[#355F58] hover:bg-[#2C504A] text-white font-extrabold text-xs shadow-xs press-scale transition-all"
          >
            <Compass className="w-4 h-4" />
            <span>Explore Places</span>
          </button>
        </div>
      ) : (
        /* List State */
        <div className="space-y-4">
          <div className="flex items-center justify-between text-xs font-bold text-[#5F6863] px-1">
            <span>{places.length} {places.length === 1 ? 'place' : 'places'} bookmarked</span>
            <span>Atomic Cache (10m TTL)</span>
          </div>

          <div className="space-y-3.5">
            {places.map((place) => (
              <div
                key={place.id || place.place_id}
                className="bg-white p-5 rounded-3xl border border-[#D9DEDA] hover:border-[#355F58]/30 shadow-xs space-y-3.5 transition-all"
              >
                {/* Card Header: Category, Rating & Remove */}
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="px-2.5 py-0.5 rounded-md bg-[#E8F0EE] text-[#355F58] font-bold text-[11px] uppercase tracking-wider border border-[#D9DEDA]">
                      {place.category || 'Spot'}
                    </span>
                    {place.rating !== null && place.rating !== undefined && (
                      <div className="flex items-center gap-1 text-xs font-bold text-amber-700 bg-amber-50 px-2 py-0.5 rounded-md border border-amber-200">
                        <Star className="w-3.5 h-3.5 fill-amber-500 text-amber-500" />
                        <span>{place.rating}</span>
                      </div>
                    )}
                  </div>

                  <button
                    type="button"
                    onClick={() => setConfirmDeleteId(place.place_id || place.id || null)}
                    className="p-2 rounded-xl text-[#5F6863] hover:text-rose-600 hover:bg-rose-50 border border-transparent hover:border-rose-200 transition-colors shrink-0"
                    title="Remove from saved places"
                    aria-label={`Remove ${place.title}`}
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>

                {/* Title & Address */}
                <div>
                  <h3 className="text-base sm:text-lg font-extrabold text-[#1F2522] leading-tight">{place.title}</h3>
                  {place.location_name && (
                    <p className="text-xs text-[#5F6863] flex items-center gap-1 font-medium mt-1">
                      <MapPin className="w-3.5 h-3.5 text-[#355F58] shrink-0" />
                      <span className="truncate">{place.location_name}</span>
                    </p>
                  )}
                </div>

                {/* Info Pills */}
                <div className="grid grid-cols-3 gap-2 pt-1 text-center">
                  <div className="p-2 rounded-xl bg-[#F0F2EF] border border-[#D9DEDA]">
                    <span className="text-[10px] uppercase font-bold text-[#5F6863] block">Distance</span>
                    <span className="text-xs font-extrabold text-[#1F2522] truncate block">{place.distance_text || '—'}</span>
                  </div>
                  <div className="p-2 rounded-xl bg-[#F0F2EF] border border-[#D9DEDA]">
                    <span className="text-[10px] uppercase font-bold text-[#5F6863] block">Duration</span>
                    <span className="text-xs font-extrabold text-[#1F2522] truncate block">{place.duration_text || '—'}</span>
                  </div>
                  <div className="p-2 rounded-xl bg-[#F0F2EF] border border-[#D9DEDA]">
                    <span className="text-[10px] uppercase font-bold text-[#5F6863] block">Cost</span>
                    <span className="text-xs font-extrabold text-[#355F58] truncate block">{place.cost_text || '—'}</span>
                  </div>
                </div>

                {/* Description Excerpt */}
                {place.description && (
                  <p className="text-xs text-[#5F6863] line-clamp-2 leading-relaxed font-medium">
                    {place.description}
                  </p>
                )}

                {/* Card Actions */}
                <div className="pt-2 border-t border-[#D9DEDA] flex items-center justify-between gap-3">
                  <button
                    type="button"
                    onClick={() => handleOpenDirections(place)}
                    className="flex-1 py-2.5 px-4 rounded-xl bg-[#355F58] hover:bg-[#2C504A] text-white font-extrabold text-xs flex items-center justify-center gap-1.5 shadow-xs press-scale"
                  >
                    <Navigation className="w-3.5 h-3.5 text-white" />
                    <span>Get Directions</span>
                    <ExternalLink className="w-3 h-3 text-white/70 ml-0.5" />
                  </button>

                  <button
                    type="button"
                    onClick={() => setConfirmDeleteId(place.place_id || place.id || null)}
                    className="py-2.5 px-3.5 rounded-xl bg-[#F0F2EF] hover:bg-rose-50 hover:text-rose-600 border border-[#D9DEDA] hover:border-rose-200 text-[#5F6863] font-bold text-xs flex items-center gap-1.5 transition-colors"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                    <span>Remove</span>
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
