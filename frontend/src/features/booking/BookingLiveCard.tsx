import React, { useEffect, useRef, useState } from 'react';
import type { BookingCard } from './bookingApi';
import { changedKeys, rowValues } from './bookingLogic';

const FLASH_MS = 1000;

/**
 * Booking stage 2: the live summary above the current question. It fills in as answers arrive (by voice through
 * the refresh event, or by tap). A changed row is highlighted for about a second: background only, so the layout
 * never moves; with prefers-reduced-motion the colour changes without a transition.
 * Names, ages and the phone number are shown only here and on this screen's review, never logged.
 */
export const BookingLiveCard: React.FC<{ card: BookingCard }> = ({ card }) => {
  const prev = useRef<Record<string, string> | null>(null);
  const [flash, setFlash] = useState<string[]>([]);

  useEffect(() => {
    const changed = changedKeys(prev.current, card.rows);
    prev.current = rowValues(card.rows);
    if (!changed.length) return;
    setFlash(changed);
    const t = setTimeout(() => setFlash([]), FLASH_MS);
    return () => clearTimeout(t);
  }, [card]);

  return (
    <section aria-label="Booking details" className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-3 dark:border-zinc-700">
      {card.now && (
        <p className="mb-2 text-xs font-extrabold text-[var(--color-primary)]" aria-live="polite">{card.now}</p>
      )}
      <dl className="space-y-0.5">
        {card.rows.map((row) => {
          const lit = flash.includes(row.key);
          return (
            <div
              key={row.key}
              data-row={row.key}
              data-flash={lit ? 'true' : undefined}
              aria-current={row.current ? 'step' : undefined}
              className={[
                'flex items-baseline justify-between gap-3 rounded-lg px-2 py-1 text-xs border-l-2',
                'motion-safe:transition-colors motion-safe:duration-500',
                row.current ? 'border-[var(--color-primary)] bg-[#E8F0EE] dark:bg-[#12332B]' : 'border-transparent',
                lit ? 'bg-amber-100 dark:bg-amber-900/40' : '',
              ].join(' ')}
            >
              <dt className="shrink-0 font-bold text-[var(--color-text-secondary)]">{row.label}</dt>
              <dd className={`min-w-0 wrap-anywhere text-right font-extrabold ${row.value === '-' ? 'text-[var(--color-text-secondary)]' : 'text-[var(--color-text-primary)]'}`}>
                {row.value}
              </dd>
            </div>
          );
        })}
      </dl>
    </section>
  );
};
