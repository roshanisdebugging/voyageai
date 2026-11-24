import React from 'react';
import { Landmark, UtensilsCrossed, Waves, ShoppingBag, Music, Mountain, MapPin, Moon, PartyPopper } from 'lucide-react';
import { placeholderKind, type PlaceholderKind } from '../../utils/imageSources';

const ICONS: Record<PlaceholderKind, React.ComponentType<{ className?: string; 'aria-hidden'?: boolean }>> = {
  food: UtensilsCrossed,
  beach: Waves,
  market: ShoppingBag,
  music: Music,
  nightlife: Moon,
  nature: Mountain,
  heritage: Landmark,
  festival: PartyPopper,
  place: MapPin,
};

interface ImagePlaceholderProps {
  name?: string;
  category?: string | null;
  className?: string;
  /** Small tiles: icon only, no name. */
  compact?: boolean;
}

/** Shown when there is no real picture (or it failed to load): a gradient, the category icon and the name. */
export const ImagePlaceholder: React.FC<ImagePlaceholderProps> = ({ name, category, className = '', compact = false }) => {
  const Icon = ICONS[placeholderKind(category)];
  return (
    <div
      role="img"
      aria-label={name ? `${name} (no photo)` : 'No photo'}
      data-testid="image-placeholder"
      className={`w-full h-full bg-gradient-to-br from-[#1F2522] via-[#2C504A] to-[#355F58] flex flex-col items-center justify-center gap-2 p-3 text-center ${className}`}
    >
      <Icon className={compact ? 'w-6 h-6 text-white/80' : 'w-8 h-8 text-white/80'} aria-hidden />
      {!compact && name && (
        <span className="text-white/90 font-semibold text-xs tracking-wide line-clamp-2 max-w-full">{name}</span>
      )}
    </div>
  );
};
