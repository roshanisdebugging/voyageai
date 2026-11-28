import React, { useEffect, useRef, useState } from 'react';
import type { BookingCard } from './bookingApi';
import { changedKeys, rowValues } from './bookingLogic';

const FLASH_MS = 1000;

/**
 * Booking stage 2: the live summary beside the question on wide screens. It fills in as answers arrive (by voice through
 * the refresh event, or by tap). A changed row is highlighted for about a second: background only, with transitions disabled for reduced motion.
 * Names, ages and the phone number are shown only here and on this screen's review, never logged.
 */
export const BookingLiveCard: React.FC<{ card: BookingCard }> = ({ card }) => {
  const prev = useRef<Record<string, string> | null>(null);
  const [flash, setFlash] = useState<string[]>([]);

  useEffect(() => {
    const changed = changedKeys(prev.current, card.rows);
    prev.current = rowValues(card.rows);
    setFlash(changed);
    if (!changed.length) return;
    const timer = setTimeout(() => setFlash([]), FLASH_MS);
    return () => clearTimeout(timer);
  }, [card]);

  return (
    <section className="booking-summary" aria-label="Booking details">
      <h2>Booking details</h2>
      <dl className="booking-answers">
        {card.rows.filter(row => row.current || row.value !== '-').map(row => (
          <div key={row.key} data-row={row.key} data-flash={flash.includes(row.key) || undefined}
            aria-current={row.current ? 'step' : undefined}>
            <dt>{row.label}</dt>
            <dd>{row.value === '-' ? 'In progress' : row.value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
};
