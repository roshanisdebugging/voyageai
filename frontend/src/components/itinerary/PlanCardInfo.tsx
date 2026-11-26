import React from 'react';
import { BadgeCheck, ExternalLink, MapPinOff, Sparkles } from 'lucide-react';
import type { PlanCardMeta } from '../../features/trip/types';

const verifiedText = (lastVerified: string | null | undefined): string => {
  if (!lastVerified) return 'Not yet verified';
  const d = new Date(`${lastVerified}T00:00:00`);
  return Number.isNaN(d.getTime())
    ? 'Not yet verified'
    : `Verified on ${d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })}`;
};

const safeUrl = (url: string | null | undefined): string | null =>
  typeof url === 'string' && /^https:\/\/[^\s]+$/.test(url) ? url : null;

/** Plan name, verification state and the booking notes with their official links. */
export const PlanCardInfo: React.FC<{ meta: PlanCardMeta }> = ({ meta }) => (
  <section
    aria-label="Checked plan"
    className="rounded-2xl border border-(--itinerary-border) bg-(--color-surface) p-4 space-y-3 shadow-xs"
  >
    <div className="flex flex-wrap items-center gap-2">
      <BadgeCheck className="w-4 h-4 shrink-0 text-(--itinerary-accent)" aria-hidden="true" />
      <h2 className="min-w-0 text-sm font-extrabold text-[var(--color-text-primary)] break-words">{meta.nameEn}</h2>
      <span
        className={`px-2 py-0.5 rounded-md text-[11px] font-bold border ${
          meta.lastVerified
            ? 'bg-emerald-50 text-emerald-800 border-emerald-200 dark:bg-emerald-950 dark:text-emerald-200 dark:border-emerald-800'
            : 'bg-amber-50 text-amber-900 border-amber-300 dark:bg-amber-950 dark:text-amber-200 dark:border-amber-800'
        }`}
      >
        {verifiedText(meta.lastVerified)}
      </span>
    </div>
    {(meta.bookingNotes?.length ?? 0) > 0 && (
      <ul className="space-y-2">
        {meta.bookingNotes!.map((note, i) => {
          const url = safeUrl(note.officialUrl);
          return (
            <li key={i} className="text-xs leading-relaxed text-[var(--color-text-primary)] break-words">
              {note.text}
              {url && (
                <>
                  {' '}
                  <a
                    href={url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 font-bold text-(--itinerary-accent) underline underline-offset-2 break-all"
                  >
                    Official website <ExternalLink className="w-3 h-3 shrink-0" aria-hidden="true" />
                  </a>
                </>
              )}
            </li>
          );
        })}
      </ul>
    )}
    <p className="text-xs font-bold text-[var(--color-text-primary)]">
      Please confirm timings and registration on the official website
    </p>
  </section>
);

/** "From a checked plan" / "AI suggested" for one day; nothing for a free day or a trip without a plan. */
export const PlanDayLabel: React.FC<{ meta: PlanCardMeta | null; dayNumber: number }> = ({ meta, dayNumber }) => {
  const source = meta?.days?.find((d) => d.dayNumber === dayNumber)?.source;
  if (source === 'card') {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-bold bg-(--itinerary-accent-surface) text-(--itinerary-accent) border border-(--itinerary-border)">
        <BadgeCheck className="w-3 h-3 shrink-0" aria-hidden="true" /> From a checked plan
      </span>
    );
  }
  if (source === 'ai') {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-bold bg-[var(--color-surface-elevated)] text-[var(--color-text-primary)] border border-[var(--color-border)]">
        <Sparkles className="w-3 h-3 shrink-0" aria-hidden="true" /> AI suggested
      </span>
    );
  }
  return null;
};

/** A stop Google could not place: said plainly, with no location shown for it. */
export const UnresolvedStopNote: React.FC<{ meta: PlanCardMeta | null; activityId: string }> = ({ meta, activityId }) => {
  if (!meta?.stops?.[activityId]?.unresolved) return null;
  return (
    <p className="inline-flex items-center gap-1.5 px-2 py-1 rounded-md text-[11px] font-bold bg-amber-50 text-amber-900 border border-amber-300 dark:bg-amber-950 dark:text-amber-200 dark:border-amber-800">
      <MapPinOff className="w-3.5 h-3.5 shrink-0" aria-hidden="true" /> Location not found: not shown on the map
    </p>
  );
};
