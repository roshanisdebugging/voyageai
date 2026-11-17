import React from 'react';
import { Loader2 } from 'lucide-react';
import { Portal } from '../components/common/Portal';

/**
 * Voice steps 4-5: the Confirm card for a big action (create a trip, add an expense, rebuild the itinerary).
 * Confirm here and saying "haan" run the same server action, once. Cancel saves nothing. For a new trip the
 * app then presses Proceed on the review page, so the page's values are what gets saved.
 */
export const ConfirmCard: React.FC<{
  summary: string;
  /** Step 5: "Add this expense?" / "Rebuild the itinerary?"; default is the trip one. */
  title?: string;
  busy?: boolean;
  /** CSS bottom offset; defaults to just above the bottom nav. */
  bottom?: string;
  onConfirm: () => void;
  onCancel: () => void;
}> = ({ summary, title = 'Create this trip?', busy = false, bottom, onConfirm, onCancel }) => (
  <Portal>
    <div
      role="dialog"
      aria-modal="false"
      aria-labelledby="voice-confirm-title"
      data-confirm-card
      className="fixed left-3 right-3 sm:left-auto sm:right-6 sm:w-[380px] z-[var(--z-modal)] rounded-2xl bg-white dark:bg-zinc-900 border border-[#D9DEDA] dark:border-zinc-700 shadow-2xl p-4 space-y-3 animate-fadeIn"
      style={{ bottom: bottom ?? 'calc(var(--bottom-nav-h, 72px) + env(safe-area-inset-bottom, 0px) + 12px)' }}
    >
      <h2 id="voice-confirm-title" className="text-sm font-bold text-[#1F2522] dark:text-zinc-100">{title}</h2>
      <p className="text-xs leading-relaxed text-[#5F6863] dark:text-zinc-400">{summary}</p>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={onCancel}
          disabled={busy}
          className="flex-1 min-h-[44px] rounded-xl border border-[#D9DEDA] dark:border-zinc-700 text-sm font-semibold text-[#1F2522] dark:text-zinc-100 press-scale disabled:opacity-60"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={onConfirm}
          disabled={busy}
          className="flex-1 min-h-[44px] rounded-xl bg-[#1F5A3F] hover:bg-[#194B34] text-white text-sm font-semibold flex items-center justify-center gap-1.5 press-scale disabled:opacity-60"
        >
          {busy && <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />} Confirm
        </button>
      </div>
    </div>
  </Portal>
);
