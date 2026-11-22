/**
 * "22 min by car" between two consecutive activities of the open day (Google Routes, via /api/routes/compute).
 * Lazy: only once the leg scrolls into view, one leg at a time across the page (a shared queue), cached on the
 * server and in memory. No coordinates (or no route) -> nothing is shown; a time is never invented.
 */
import React, { useEffect, useRef, useState } from 'react';
import { Car } from 'lucide-react';
import { computeRoute, RouteError } from '../../services/routesApi';
import { formatLegTime, haversineMeters, legHasCoords } from '../map/mapLogic';

// One leg at a time; after a quota/paused answer, stop asking for a while.
let chain: Promise<unknown> = Promise.resolve();
let pausedUntil = 0;
function enqueue<T>(fn: () => Promise<T>): Promise<T> {
  const p = chain.then(fn, fn);
  chain = p.catch(() => undefined);
  return p;
}

interface Point { latitude?: number; longitude?: number }

export const TravelLeg: React.FC<{ from: Point; to: Point }> = ({ from, to }) => {
  const ref = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);
  const [text, setText] = useState<string | null>(null);
  const usable = legHasCoords(from, to)
    && haversineMeters(from.latitude!, from.longitude!, to.latitude!, to.longitude!) > 50;

  useEffect(() => {
    if (!usable || visible) return;
    const el = ref.current;
    if (!el || typeof IntersectionObserver === 'undefined') { setVisible(true); return; }
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) { setVisible(true); io.disconnect(); }
    }, { rootMargin: '120px' });
    io.observe(el);
    return () => io.disconnect();
  }, [usable, visible]);

  useEffect(() => {
    if (!usable || !visible) return;
    let cancelled = false;
    enqueue(async () => {
      if (cancelled || Date.now() < pausedUntil) return;
      try {
        const r = await computeRoute({ lat: from.latitude!, lng: from.longitude! }, { lat: to.latitude!, lng: to.longitude! }, 'drive');
        if (!cancelled) setText(formatLegTime(r.duration_s, 'drive'));
      } catch (err) {
        if (err instanceof RouteError && (err.status === 503 || err.status === 429)) pausedUntil = Date.now() + 10 * 60 * 1000;
      }
    });
    return () => { cancelled = true; };
  }, [usable, visible, from.latitude, from.longitude, to.latitude, to.longitude]);

  if (!usable) return null;
  return (
    <div ref={ref} className="flex items-center gap-2 pl-4 min-h-[20px] text-[11px] font-semibold text-[var(--color-text-secondary)]" aria-live="polite">
      {text && (<><Car className="w-3.5 h-3.5 text-[var(--color-primary)]" aria-hidden="true" /> {text}</>)}
    </div>
  );
};
