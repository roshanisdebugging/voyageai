import React, { useState, useEffect } from 'react';
import { useToast } from './UndoToast';
import { useApp } from '../../context/AppContext';
import { MapPin, Star, Navigation, Sparkles, X, Car, Heart, Check, Loader2 } from 'lucide-react';
import { checkPlaceSaved, savePlace, removeSavedPlace } from '../../services/savedPlacesApi';

export interface PlaceDetailItem {
  id: string;
  name: string;
  category?: string;
  rating?: number;
  distanceText?: string;
  durationText?: string;
  estimatedCost?: number;
  description?: string;
  address?: string;
  latitude?: number;
  longitude?: number;
  is_mock?: boolean;
  _isMock?: boolean;
}

interface PlaceDetailSheetProps {
  item: PlaceDetailItem | null;
  onClose: () => void;
}

// The hooks live in PlaceDetailSheetBody, which only mounts when there is an item,
// so they always run in the same order (no hooks after an early return).
export const PlaceDetailSheet: React.FC<PlaceDetailSheetProps> = ({ item, onClose }) => {
  if (!item) return null;
  return <PlaceDetailSheetBody item={item} onClose={onClose} />;
};

const PlaceDetailSheetBody: React.FC<{ item: PlaceDetailItem; onClose: () => void }> = ({ item, onClose }) => {
  const { openInAppNavigation, openCabModal, openAiAssistant } = useApp();

  const [isSaved, setIsSaved] = useState<boolean>(false);
  const { showToast } = useToast();
  const handleToggleSaveRef = React.useRef<(fromUndo?: boolean) => Promise<void>>(async () => {});
  const [isSaving, setIsSaving] = useState<boolean>(false);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    if (item.id) {
      checkPlaceSaved(item.id).then((saved) => {
        if (active) setIsSaved(saved);
      });
    } else {
      setIsSaved(false);
    }
    return () => {
      active = false;
    };
  }, [item.id]);

  const hasCoordinates = typeof item.latitude === 'number' && typeof item.longitude === 'number' && !isNaN(item.latitude) && !isNaN(item.longitude);

  const handleToggleSave = async (fromUndo = false) => {
    if (!item || isSaving) return;
    setIsSaving(true);
    const previous = isSaved;
    const nextState = !previous;
    setIsSaved(nextState);

    try {
      if (nextState) {
        await savePlace({
          place_id: item.id,
          title: item.name,
          category: item.category,
          rating: item.rating,
          location_name: item.address || item.name,
          location: item.address || item.name,
          coordinates: hasCoordinates ? [item.latitude!, item.longitude!] : undefined,
          distance_text: item.distanceText,
          duration_text: item.durationText,
          cost_text: item.estimatedCost ? `₹${item.estimatedCost}` : 'Free',
          description: item.description,
        });
        if (!fromUndo) showToast({ message: 'Saved to your places', undo: () => handleToggleSaveRef.current(true) });
      } else {
        await removeSavedPlace(item.id);
        if (!fromUndo) showToast({ message: 'Removed from saved places', undo: () => handleToggleSaveRef.current(true) });
      }
    } catch (err: any) {
      setIsSaved(previous);
      setToastMessage(err.message || 'Action failed. Please try again.');
    } finally {
      setIsSaving(false);
      setTimeout(() => setToastMessage(null), 3000);
    }
  };

  useEffect(() => {
    handleToggleSaveRef.current = handleToggleSave;
  });

  const handleNavigate = () => {
    if (!hasCoordinates || item.latitude === undefined || item.longitude === undefined) return;
    openInAppNavigation({
      title: item.name,
      locationName: item.address || item.name,
      coordinates: [item.latitude, item.longitude],
    });
    onClose();
  };

  const handleBookCab = () => {
    openCabModal(item.name);
    onClose();
  };

  const handleAskAI = () => {
    openAiAssistant(`Tell me more about ${item.name}, including timings, best entry spots, and history.`);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-[99999] flex items-end sm:items-center justify-center p-0 sm:p-4 bg-[#1F2522]/40 backdrop-blur-xs animate-fadeIn">
      <div className="w-full max-w-lg max-h-[85vh] sm:max-h-[90vh] overflow-y-auto bg-white border border-[#D9DEDA] rounded-t-3xl sm:rounded-3xl p-6 pb-20 sm:pb-6 mb-16 sm:mb-0 space-y-5 shadow-2xl animate-slideUp text-[#1F2522] relative">
        
        {/* Floating Toast Notification */}
        {toastMessage && (
          <div className="absolute top-3 left-1/2 -translate-x-1/2 z-50 px-4 py-2 rounded-xl bg-[#1F2522] text-white text-xs font-bold shadow-lg animate-fadeIn flex items-center gap-2">
            <Check className="w-4 h-4 text-teal-400" />
            <span>{toastMessage}</span>
          </div>
        )}

        {/* Header */}
        <div className="flex items-start justify-between gap-4 border-b border-[#D9DEDA] pb-4">
          <div className="space-y-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="px-2.5 py-0.5 rounded-md bg-[#E8F0EE] text-[#355F58] font-bold text-[11px] uppercase tracking-wider border border-[#D9DEDA]">
                {item.category || 'Attraction'}
              </span>
              {item.rating && (
                <div className="flex items-center gap-1 text-xs font-bold text-amber-700">
                  <Star className="w-3.5 h-3.5 fill-amber-500 text-amber-500" />
                  <span>{item.rating}</span>
                </div>
              )}
            </div>
            <h2 className="text-xl sm:text-2xl font-extrabold text-[#1F2522] truncate leading-tight">{item.name}</h2>
            {item.address && (
              <p className="text-xs text-[#5F6863] flex items-center gap-1 font-medium">
                <MapPin className="w-3.5 h-3.5 text-[#355F58] shrink-0" />
                <span className="truncate">{item.address}</span>
              </p>
            )}
          </div>

          <div className="flex items-center gap-2 shrink-0">
            <button
              type="button"
              onClick={() => handleToggleSave()}
              disabled={isSaving}
              className={`w-10 h-10 rounded-full flex items-center justify-center transition-all press-scale border ${
                isSaved
                  ? 'bg-rose-50 border-rose-200 text-rose-600'
                  : 'bg-[#F0F2EF] border-[#D9DEDA] text-[#5F6863] hover:text-rose-600'
              }`}
              aria-label={isSaved ? 'Remove from saved places' : 'Save this spot'}
              title={isSaved ? 'Saved to Favorites' : 'Save Spot'}
            >
              {isSaving ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Heart className={`w-5 h-5 transition-transform ${isSaved ? 'fill-rose-600 text-rose-600 scale-110' : ''}`} />
              )}
            </button>

            <button
              type="button"
              onClick={onClose}
              className="w-10 h-10 rounded-full bg-[#F0F2EF] border border-[#D9DEDA] flex items-center justify-center text-[#5F6863] hover:text-[#1F2522]"
              aria-label="Close details"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Info Blocks */}
        <div className="grid grid-cols-3 gap-2">
          <div className="p-3 rounded-2xl bg-[#F0F2EF] border border-[#D9DEDA] text-center">
            <span className="text-[10px] font-bold text-[#5F6863] uppercase block">Distance</span>
            <span className="text-sm font-extrabold text-[#1F2522]">{item.distanceText || 'Near you'}</span>
          </div>

          <div className="p-3 rounded-2xl bg-[#F0F2EF] border border-[#D9DEDA] text-center">
            <span className="text-[10px] font-bold text-[#5F6863] uppercase block">Duration</span>
            <span className="text-sm font-extrabold text-[#1F2522]">{item.durationText || '1 - 2 hrs'}</span>
          </div>

          <div className="p-3 rounded-2xl bg-[#F0F2EF] border border-[#D9DEDA] text-center">
            <span className="text-[10px] font-bold text-[#5F6863] uppercase block">Est. Cost</span>
            <span className="text-sm font-extrabold text-[#355F58]">
              {item.estimatedCost ? `₹${item.estimatedCost}` : 'Free'}
            </span>
          </div>
        </div>

        {/* Description */}
        <div className="space-y-1">
          <h4 className="text-xs font-bold text-[#5F6863] uppercase tracking-wider">About This Place</h4>
          <p className="text-sm text-[#1F2522] leading-relaxed font-medium">
            {item.description || 'Popular destination recommended for travelers. Beautiful views and cultural significance.'}
          </p>
        </div>

        {/* Action Buttons (Large, Thumb-Friendly) */}
        <div className="space-y-2.5 pt-2">
          {/* Primary Action Button */}
          <button
            type="button"
            onClick={handleNavigate}
            disabled={!hasCoordinates}
            className="w-full py-4 rounded-2xl bg-[#355F58] hover:bg-[#2C504A] disabled:opacity-50 disabled:cursor-not-allowed text-white font-extrabold text-base flex items-center justify-center gap-2 shadow-xs press-scale min-h-[54px]"
          >
            <Navigation className="w-5 h-5 text-white" />
            <span>{hasCoordinates ? 'Navigate / Get Directions' : 'Directions Unavailable'}</span>
          </button>

          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={handleBookCab}
              className="py-3.5 rounded-2xl bg-[#F0F2EF] border border-[#D9DEDA] text-[#1F2522] font-bold text-xs flex items-center justify-center gap-1.5 hover:border-[#355F58]/40 min-h-[48px]"
            >
              <Car className="w-4 h-4 text-[#355F58]" />
              <span>Book Ride</span>
            </button>

            <button
              type="button"
              onClick={handleAskAI}
              className="py-3.5 rounded-2xl bg-[#F0F2EF] border border-[#D9DEDA] text-[#355F58] font-bold text-xs flex items-center justify-center gap-1.5 hover:border-[#355F58]/40 min-h-[48px]"
            >
              <Sparkles className="w-4 h-4 text-[#355F58]" />
              <span>Ask AI Guide</span>
            </button>
          </div>
        </div>

      </div>
    </div>
  );
};
