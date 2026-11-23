/**
 * Travel time to each activity FROM THE DEVICE'S CURRENT LOCATION (never from the previous activity, a hotel or the
 * trip destination). One line per activity card with coordinates:
 *   "22 min by car from your location · 6.8 km"   (Google Routes; lazy, only once the card is in view, one at a time)
 *   "Aap yahin hain"                               (under 150 m, no call)
 *   "Aap is jagah se door hain (812 km)"           (over 300 km, no call)
 *   "4.1 km straight-line"                         (poor accuracy, over the 8-a-day limit, or Routes unavailable)
 *   "Location chahiye"                             (no location; TravelOriginBar says why)
 * A time is never invented. Tapping the line opens RouteOriginSheet.
 */
import React, { useEffect, useRef, useState } from 'react';
import { Car, LocateFixed, Navigation } from 'lucide-react';
import { deviceLocation, useDeviceLocation } from '../../services/useDeviceLocation';
import { farKm, noLocationReason, originLabel, travelPlan } from '../../services/deviceLocationLogic';
import { formatLegTime, formatStraightLine } from '../map/mapLogic';
import { RouteOriginSheet } from '../common/RouteOriginSheet';

interface Dest { latitude?: number; longitude?: number; title?: string; locationName?: string }

/** Top of the day: "From: Your location (accuracy 30 m)", or why there is none, and "Use my location again". */
export const TravelOriginBar: React.FC = () => {
  const loc = useDeviceLocation();
  const usable = loc.origin && loc.reading && loc.reading.accuracy_m <= 1000;
  let text: string;
  if (loc.status === 'loading' && !loc.reading) text = noLocationReason('loading');
  else if (!loc.reading) text = noLocationReason(loc.status === 'error' ? loc.error || 'unavailable' : 'idle');
  else if (!usable) text = noLocationReason('poor');
  else text = originLabel(loc.reading.accuracy_m);
  return (
    <div className="flex items-center justify-between gap-2 px-1 text-[11px] font-semibold text-[var(--color-text-secondary)]" aria-live="polite">
      <span className="flex items-center gap-1.5 min-w-0">
        <Navigation className="w-3.5 h-3.5 shrink-0 text-[#1A73E8]" aria-hidden="true" />
        <span className="truncate">{text}</span>
      </span>
      {(!usable || loc.status === 'error') && (
        <button type="button" onClick={loc.retry} disabled={loc.status === 'loading'}
          className="shrink-0 min-h-[32px] px-3 rounded-full border border-[var(--color-border)] text-[var(--color-primary)] font-bold flex items-center gap-1 disabled:opacity-60">
          <LocateFixed className="w-3.5 h-3.5" aria-hidden="true" /> Use my location again
        </button>
      )}
    </div>
  );
};

/** routeAllowed: false past the first 8 activities with coordinates of the day (straight-line only, no call). */
export const TravelFromHere: React.FC<{ dest: Dest; routeAllowed: boolean }> = ({ dest, routeAllowed }) => {
  const loc = useDeviceLocation(false); // the day's TravelOriginBar reads it on open
  const ref = useRef<HTMLButtonElement>(null);
  const [visible, setVisible] = useState(false);
  const [route, setRoute] = useState<{ key: string; text?: string; failed?: boolean } | null>(null);
  const [sheet, setSheet] = useState(false);
  const plan = travelPlan(loc, dest);
  const wantsRoute = plan.kind === 'route' && routeAllowed;
  const routeKey = plan.kind === 'route' ? `${plan.origin.lat},${plan.origin.lng}` : '';

  useEffect(() => {
    if (!wantsRoute || visible) return;
    const el = ref.current;
    if (!el || typeof IntersectionObserver === 'undefined') { setVisible(true); return; }
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) { setVisible(true); io.disconnect(); }
    }, { rootMargin: '120px' });
    io.observe(el);
    return () => io.disconnect();
  }, [wantsRoute, visible]);

  useEffect(() => {
    if (!wantsRoute || !visible || !routeKey) return;
    let cancelled = false;
    deviceLocation.route({ lat: Number(dest.latitude), lng: Number(dest.longitude) }, 'drive', 'itinerary', true)
      .then((r) => {
        if (!cancelled) setRoute({ key: routeKey, text: `${formatLegTime(r.duration_s, 'drive')} from your location · ${formatStraightLine(r.distance_m)}` });
      })
      .catch(() => { if (!cancelled) setRoute({ key: routeKey, failed: true }); });
    return () => { cancelled = true; };
  }, [wantsRoute, visible, routeKey, dest.latitude, dest.longitude]);

  if (plan.kind === 'no-coords') return null;
  const mine = route && route.key === routeKey ? route : null;
  let text: string;
  switch (plan.kind) {
    case 'no-location': text = plan.reason === 'loading' ? 'Location dekh rahe hain…' : 'Location chahiye'; break;
    case 'poor': text = `${formatStraightLine(plan.straightM)} straight-line (exact location nahi mili)`; break;
    case 'here': text = 'Aap yahin hain'; break;
    case 'far': text = `Aap is jagah se door hain (${farKm(plan.straightM)})`; break;
    default:
      if (!routeAllowed) text = `${formatStraightLine(plan.straightM)} straight-line`;
      else if (mine?.text) text = mine.text;
      else if (mine?.failed) text = `${formatStraightLine(plan.straightM)} straight-line · route abhi available nahi`;
      else text = '…';
  }
  const canOpen = Boolean(loc.reading) && plan.kind !== 'no-location';
  const destName = dest.title || dest.locationName || 'This place';
  return (
    <>
      <button ref={ref} type="button" disabled={!canOpen} onClick={() => setSheet(true)}
        className="flex items-center gap-1.5 min-h-[28px] text-left text-[11px] font-semibold text-[var(--color-text-secondary)] disabled:cursor-default"
        aria-live="polite">
        <Car className="w-3.5 h-3.5 shrink-0 text-[var(--color-primary)]" aria-hidden="true" />
        <span className="tabular-nums">{text}</span>
      </button>
      {sheet && loc.reading && (
        <RouteOriginSheet
          origin={loc.origin && plan.kind !== 'poor' ? loc.origin : loc.reading}
          dest={{ name: destName, lat: Number(dest.latitude), lng: Number(dest.longitude) }}
          summary={text}
          onClose={() => setSheet(false)}
        />
      )}
    </>
  );
};
