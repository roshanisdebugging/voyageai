import L from 'leaflet';
import { getCategoryConfig } from './mapCategoryConfig';

// Module-level icon memoization cache
const iconCache = new Map<string, L.DivIcon>();

/**
 * DivIcon for the user's live location: a solid dot with a soft pulsing ring.
 * Memoized at module level since it never changes.
 */
export const createUserLocationIcon = (): L.DivIcon => {
  const icon = L.divIcon({
    className: 'custom-user-marker',
    html: `
      <div style="position: relative; width: 36px; height: 36px; display: flex; align-items: center; justify-content: center;">
        <div class="user-radar-ring"></div>
        <div style="width: 20px; height: 20px; border-radius: 50%; background: #1F5A3F; border: 3px solid #ffffff; box-shadow: 0 0 0 4px rgba(31,90,63,0.16), 0 2px 6px rgba(15,23,42,0.25); z-index: 2; position: relative;"></div>
      </div>
    `,
    iconSize: [36, 36],
    iconAnchor: [18, 18],
  });

  return icon;
};

/**
 * DivIcon for a place marker, colored by category (see mapCategoryConfig.ts).
 * Memoized by `${category}-${isSelected}` so repeated renders reuse the same instance.
 */
export const createPoiIcon = (category: string, isSelected: boolean): L.DivIcon => {
  const config = getCategoryConfig(category);
  const cacheKey = `${config.id}-${isSelected ? 'selected' : 'normal'}`;

  if (iconCache.has(cacheKey)) {
    return iconCache.get(cacheKey)!;
  }

  const transform = isSelected ? 'transform: scale(1.3); z-index: 999;' : '';
  const markerBg = isSelected ? config.ring : '#FFFFFF';
  const dotBg = isSelected ? '#FFFFFF' : config.dot;
  const borderColor = isSelected ? '#FFFFFF' : config.ring;
  const shadow = isSelected ? '0 4px 14px rgba(15,23,42,0.28)' : config.shadow;

  const icon = L.divIcon({
    className: 'custom-poi-marker',
    html: `
      <div style="${transform} display: flex; align-items: center; justify-content: center; width: 32px; height: 32px; border-radius: 14px; background: ${markerBg}; border: 2px solid ${borderColor}; box-shadow: ${shadow}; transition: transform 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);">
        <div style="width: 9px; height: 9px; border-radius: 50%; background: ${dotBg};"></div>
      </div>
    `,
    iconSize: [32, 32],
    iconAnchor: [16, 16],
  });

  iconCache.set(cacheKey, icon);
  return icon;
};

/**
 * DivIcon for a cluster of markers (used once marker density gets high).
 * Memoized by count.
 */
export const createClusterIcon = (count: number): L.DivIcon => {
  const cacheKey = `cluster-${count}`;
  if (iconCache.has(cacheKey)) {
    return iconCache.get(cacheKey)!;
  }

  const icon = L.divIcon({
    className: 'custom-cluster-marker',
    html: `
      <div style="display: flex; align-items: center; justify-content: center; width: 38px; height: 38px; border-radius: 50%; background: #FFFFFF; border: 2px solid #1F5A3F; color: #1F5A3F; font-weight: 700; font-size: 13px; box-shadow: 0 2px 10px rgba(15,23,42,0.2);">
        ${count}
      </div>
    `,
    iconSize: [38, 38],
    iconAnchor: [19, 19],
  });

  iconCache.set(cacheKey, icon);
  return icon;
};