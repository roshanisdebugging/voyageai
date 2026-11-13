/**
 * VoyageAI — Unified Map Category Taxonomy & Visual Styles
 * 
 * Single source of truth for map category definitions, pill labels, icons, 
 * marker color schemes, and fallback images.
 */

export interface CategoryStyle {
  id: string;
  label: string;
  emoji: string;
  bg: string;
  text: string;
  ring: string;
  dot: string;
  shadow: string;
  coverImage: string;
}

export const MAP_CATEGORY_CONFIG: Record<string, CategoryStyle> = {
  food: {
    id: 'food',
    label: 'Food & Cafes',
    emoji: '🍽️',
    bg: '#FFFFFF',
    text: '#B5762A',
    ring: '#D9A15A',
    dot: '#B5762A',
    shadow: '0 2px 10px rgba(15, 23, 42, 0.18)',
    coverImage: 'https://images.unsplash.com/photo-1555396273-367ea4eb4db5?auto=format&fit=crop&w=400&q=80',
  },
  sights: {
    id: 'sights',
    label: 'Sights & Landmarks',
    emoji: '🏰',
    bg: '#FFFFFF',
    text: '#A9663F',
    ring: '#C68B63',
    dot: '#A9663F',
    shadow: '0 2px 10px rgba(15, 23, 42, 0.18)',
    coverImage: 'https://images.unsplash.com/photo-1564507592333-c60657eea523?auto=format&fit=crop&w=400&q=80',
  },
  culture: {
    id: 'culture',
    label: 'Culture & Heritage',
    emoji: '🏛️',
    bg: '#FFFFFF',
    text: '#7C6A9C',
    ring: '#A797BE',
    dot: '#7C6A9C',
    shadow: '0 2px 10px rgba(15, 23, 42, 0.18)',
    coverImage: 'https://images.unsplash.com/photo-1564507592333-c60657eea523?auto=format&fit=crop&w=400&q=80',
  },
  hotels: {
    id: 'hotels',
    label: 'Stays',
    emoji: '🏨',
    bg: '#FFFFFF',
    text: '#5C6B8C',
    ring: '#8C99B5',
    dot: '#5C6B8C',
    shadow: '0 2px 10px rgba(15, 23, 42, 0.18)',
    coverImage: 'https://images.unsplash.com/photo-1566073771259-6a8506099945?auto=format&fit=crop&w=400&q=80',
  },
  experiences: {
    id: 'experiences',
    label: 'Experiences',
    emoji: '🎯',
    bg: '#FFFFFF',
    text: '#4F8272',
    ring: '#82AC9E',
    dot: '#4F8272',
    shadow: '0 2px 10px rgba(15, 23, 42, 0.18)',
    coverImage: 'https://images.unsplash.com/photo-1469854523086-cc02fe5d8800?auto=format&fit=crop&w=400&q=80',
  },
  all: {
    id: 'all',
    label: 'All Places',
    emoji: '🗺️',
    bg: '#FFFFFF',
    text: '#1F5A3F',
    ring: '#1F5A3F',
    dot: '#1F5A3F',
    shadow: '0 2px 10px rgba(15, 23, 42, 0.18)',
    coverImage: 'https://images.unsplash.com/photo-1469854523086-cc02fe5d8800?auto=format&fit=crop&w=400&q=80',
  }
};

export type CanonicalCategoryKey = 'all' | 'sights' | 'food' | 'hotels' | 'experiences';

/**
 * Maps raw place categories and names to one of 4 unified categories:
 * - 'food': Restaurants, cafes, dhabas, bakeries, eateries
 * - 'hotels': Stays, resorts, guest houses, lodging
 * - 'experiences': Activities, markets, entertainment, adventures
 * - 'sights': Landmarks, monuments, temples, forts, parks, points of interest
 */
export const getCanonicalCategory = (category: string = '', name: string = ''): 'sights' | 'food' | 'hotels' | 'experiences' => {
  const cat = (category || '').toLowerCase();
  const n = (name || '').toLowerCase();

  // 1. Food & Dining
  if (
    cat.includes('food') || cat.includes('restaurant') || cat.includes('cafe') || 
    cat.includes('dhaba') || cat.includes('bakery') || cat.includes('bar') || 
    cat.includes('meal') || cat.includes('dining') || cat.includes('sweet') ||
    cat.includes('bistro') || n.includes('dhaba') || n.includes('bhojanalay') || 
    n.includes('sweets') || n.includes('kitchen') || n.includes('restro') || n.includes('tandoori')
  ) {
    return 'food';
  }

  // 2. Stays / Lodging (hotels, guest houses, resorts)
  if (
    cat.includes('lodging') || cat.includes('resort') || cat.includes('stay') ||
    cat.includes('motel') || cat.includes('inn') || cat.includes('guest house') || 
    cat.includes('guesthouse') || cat.includes('hostel') || cat.includes('bed and breakfast') || 
    cat.includes('villa') || (cat.includes('hotel') && !cat.includes('restaurant') && !n.includes('dhaba') && !n.includes('restro'))
  ) {
    return 'hotels';
  }

  // 3. Experiences & Activities
  if (
    cat.includes('experience') || cat.includes('activity') || cat.includes('tour') || 
    cat.includes('adventure') || cat.includes('entertainment') || cat.includes('amusement') ||
    cat.includes('cinema') || cat.includes('theater') || cat.includes('zoo') || 
    cat.includes('aquarium') || cat.includes('stadium') || cat.includes('sports') ||
    cat.includes('market') || cat.includes('shopping') || n.includes('bazaar') || n.includes('market') ||
    cat.includes('fair') || n.includes('mela')
  ) {
    return 'experiences';
  }

  // 4. Sights & Landmarks (default for points of interest, temples, monuments, parks, nature, etc.)
  return 'sights';
};

/**
 * Returns canonical category config object based on category string and place name.
 */
export const getCategoryConfig = (category: string, name: string = ''): CategoryStyle => {
  const cat = (category || '').toLowerCase();
  if (cat === 'all') return MAP_CATEGORY_CONFIG.all;
  const canonical = getCanonicalCategory(category, name);
  return MAP_CATEGORY_CONFIG[canonical] || MAP_CATEGORY_CONFIG.sights;
};

/**
 * Returns high-quality cover photo URL based on category.
 */
export const getPlaceImage = (category: string, name?: string): string => {
  const cfg = getCategoryConfig(category, name);
  return cfg.coverImage;
};
