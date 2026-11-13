// src/utils/mockIndicator.ts

/**
 * If data is mock or error flag is set,
 * generates a repeated "MOCK MOCK" string pattern for watermarks.
 */
export const getMockRepeater = (count: number = 8): string => {
  return Array(count).fill("MOCK").join(" • ");
};

/**
 * Checks whether a payload or item is mock data from backend fallbacks.
 */
export const isMockPayload = (item: any): boolean => {
  if (!item) return false;
  if (item._isMock || item.is_mock || item.isMock) return true;
  if (typeof item === 'string' && item.toUpperCase().includes('MOCK')) return true;
  
  const titleOrName = (item.title || item.name || '').toUpperCase();
  if (titleOrName.includes('MOCK') ||
      titleOrName.includes('LOCAL CULTURAL') ||
      titleOrName.includes('REGIONAL ARTISAN') ||
      titleOrName.includes('SCENIC SUNSET') ||
      titleOrName.includes('NO_LIVE_DATA')) {
    return true;
  }

  if (item.destination && typeof item.destination === 'string' && item.destination.toUpperCase().includes('MOCK')) return true;
  if (item.id && typeof item.id === 'string' && (item.id.toLowerCase().startsWith('mock_') || item.id.toLowerCase().startsWith('fb_near_'))) return true;
  return false;
};
