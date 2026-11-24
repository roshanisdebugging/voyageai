import React from 'react';
import { Bookmark, Check, ExternalLink, Plus } from 'lucide-react';
import type { AddToTripState } from '../../features/trip/useCanAddToTrip';
import { placeActions } from './mapLogic';

interface PlaceCardActionsProps {
  placeName: string;
  add: AddToTripState;
  saved: boolean;
  onAdd: () => void;
  onToggleSave: () => void;
  onDetails: () => void;
}

/**
 * The button row of a map place card. Add to Itinerary only for places in the open trip's area (or already added);
 * without it Save place takes its room.
 */
export const PlaceCardActions: React.FC<PlaceCardActionsProps> = ({ placeName, add, saved, onAdd, onToggleSave, onDetails }) => {
  const showAdd = placeActions(add.showAdd).includes('add');
  const tap = (fn: () => void) => (e: React.MouseEvent) => { e.stopPropagation(); fn(); };
  return (
    <>
      {add.hint && <p className="text-[11px] text-[color:var(--color-text-secondary)] truncate">{add.hint}</p>}
      <div className="flex items-center justify-between gap-2 pt-2 border-t border-gray-100 dark:border-zinc-800">
        {showAdd && (
          <button
            type="button"
            onClick={tap(onAdd)}
            disabled={!add.canAdd}
            className={`flex-1 min-h-[44px] px-3 rounded-xl font-semibold text-xs flex items-center justify-center gap-1.5 transition-colors press-scale ${add.addedDay !== undefined
                ? 'bg-[#1F5A3F]/10 dark:bg-emerald-950/60 text-[#1F5A3F] dark:text-emerald-400 border border-[#1F5A3F]/30 dark:border-emerald-800/40'
                : 'bg-[#1F5A3F] hover:bg-[#194B34] text-white shadow-sm'
              }`}
          >
            {add.addedDay !== undefined ? (
              <><Check className="w-4 h-4" aria-hidden="true" /> Added to Day {add.addedDay}</>
            ) : (
              <><Plus className="w-4 h-4" aria-hidden="true" /> Add to Itinerary</>
            )}
          </button>
        )}

        <button
          type="button"
          onClick={tap(onToggleSave)}
          aria-label={saved ? `Remove ${placeName} from saved places` : `Save ${placeName}`}
          aria-pressed={saved}
          className={`min-h-[44px] min-w-[44px] px-3 rounded-xl border font-semibold text-xs flex items-center justify-center gap-1.5 press-scale transition-colors ${showAdd ? '' : 'flex-1'} ${saved
              ? 'bg-[#1F5A3F]/10 dark:bg-emerald-950/60 text-[#1F5A3F] dark:text-emerald-400 border-[#1F5A3F]/30 dark:border-emerald-800/40'
              : 'bg-white dark:bg-zinc-800 text-gray-900 dark:text-zinc-100 border-gray-200 dark:border-zinc-700 hover:bg-gray-50 dark:hover:bg-zinc-700'
            }`}
        >
          <Bookmark className={`w-4 h-4 ${saved ? 'fill-current' : ''}`} aria-hidden="true" />
          {!showAdd && (saved ? 'Saved' : 'Save place')}
        </button>

        <button
          type="button"
          onClick={tap(onDetails)}
          className="min-h-[44px] px-4 rounded-xl bg-white dark:bg-zinc-800 hover:bg-gray-50 dark:hover:bg-zinc-700 text-gray-900 dark:text-zinc-100 border border-gray-200 dark:border-zinc-700 font-semibold text-xs flex items-center gap-1.5 press-scale transition-colors"
        >
          <span>Details</span>
          <ExternalLink className="w-3.5 h-3.5 text-[#1F5A3F] dark:text-emerald-400" aria-hidden="true" />
        </button>
      </div>
    </>
  );
};
