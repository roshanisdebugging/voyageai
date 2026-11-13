/**
 * Resolves a reliable image URL for a Trip or Destination with high quality fallbacks
 */
export const getTripCoverImage = (trip: any): string => {
  if (!trip) {
    return 'https://images.unsplash.com/photo-1512343879784-a960bf40e7f2?auto=format&fit=crop&w=800&q=80';
  }

  // 1. Direct coverImage property
  if (trip.coverImage && typeof trip.coverImage === 'string' && trip.coverImage.startsWith('http')) {
    return trip.coverImage;
  }

  // 2. coverMedia object property
  if (trip.coverMedia && trip.coverMedia.url && typeof trip.coverMedia.url === 'string' && trip.coverMedia.url.startsWith('http')) {
    return trip.coverMedia.url;
  }

  // 3. Fallback based on destination or trip title
  const name = ((trip.destination?.name || trip.title || '') + '').toLowerCase();

  if (name.includes('goa')) {
    return 'https://images.unsplash.com/photo-1512343879784-a960bf40e7f2?auto=format&fit=crop&w=800&q=80';
  }
  if (name.includes('kerala')) {
    return 'https://images.unsplash.com/photo-1602216056096-3b40cc0c9944?auto=format&fit=crop&w=800&q=80';
  }
  if (name.includes('manali') || name.includes('shimla') || name.includes('himachal')) {
    return 'https://images.unsplash.com/photo-1626621341517-bbf3d9990a23?auto=format&fit=crop&w=800&q=80';
  }
  if (name.includes('jaipur') || name.includes('rajasthan') || name.includes('udaipur')) {
    return 'https://images.unsplash.com/photo-1477587458883-47145ed94245?auto=format&fit=crop&w=800&q=80';
  }
  if (name.includes('patna') || name.includes('bihar')) {
    return 'https://images.unsplash.com/photo-1599487488170-d11ec9c172f0?auto=format&fit=crop&w=800&q=80';
  }
  if (name.includes('mumbai')) {
    return 'https://images.unsplash.com/photo-1570168007204-dfb528c6958f?auto=format&fit=crop&w=800&q=80';
  }
  if (name.includes('delhi')) {
    return 'https://images.unsplash.com/photo-1587474260584-136574528ed5?auto=format&fit=crop&w=800&q=80';
  }

  // Default travel fallback image
  return 'https://images.unsplash.com/photo-1488646953014-85cb44e25828?auto=format&fit=crop&w=800&q=80';
};

/**
 * Appends responsive format, width, and quality parameters to Unsplash image URLs
 * to prevent requesting full raw photos and minimize payload size.
 */
export const optimizeUnsplashUrl = (url: string, width: number = 600, quality: number = 80): string => {
  if (!url || typeof url !== 'string' || !url.includes('images.unsplash.com')) return url;
  const [base] = url.split('?');
  return `${base}?auto=format&fit=crop&w=${width}&q=${quality}`;
};
