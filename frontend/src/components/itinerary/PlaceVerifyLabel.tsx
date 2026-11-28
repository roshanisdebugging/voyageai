import React from 'react';
import { MapPinCheck, MapPinOff, Route } from 'lucide-react';
import { placeVerifyLabel } from './placeVerify';

/** "Found on Google" / "Not found on Google" / "Far from the rest of this day" ("Far from your base area" on a trip
 *  with a base area); nothing when not checked.
 *  Same look as the "AI suggested" day label. */
export const PlaceVerifyLabel: React.FC<{ status?: string | null; hasBaseArea?: boolean }> = ({ status, hasBaseArea = false }) => {
  const label = placeVerifyLabel(status, hasBaseArea);
  if (!label) return null;
  const Icon = status === 'verified' ? MapPinCheck : status === 'far' ? Route : MapPinOff;
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-bold bg-[var(--color-surface-elevated)] text-[var(--color-text-primary)] border border-[var(--color-border)]">
      <Icon className="w-3 h-3 shrink-0" aria-hidden="true" /> {label.text}
    </span>
  );
};
