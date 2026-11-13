// Primary Navigation
export type NavTab = 'home' | 'trips' | 'explore' | 'guide';

// Trip sub-views (accessed via Trip Tools / Package detail)
export type TripView = 'home' | 'timeline' | 'map' | 'reservations' | 'expenses' | 'guide' | 'food' | 'rides';

// UI State vs Product State
export type AppUIState = 'ready' | 'loading' | 'error';
export type TripStatus = 'none' | 'planning' | 'upcoming' | 'active' | 'completed';

export interface SwapActivityPayload {
  tripId: string;
  itineraryId?: string;
  dayId?: string;
  activityId: string;
  selectedDay?: number | string;
  activityName: string;
  activityDescription?: string;
  activityTime?: string;
  duration?: string;
  locationName?: string;
  latitude?: number;
  longitude?: number;
  estimatedCost?: number;
  destination?: string;
}

export interface NavigationTarget {
  activityId?: string;
  title: string;
  locationName: string;
  coordinates: [number, number];
  dayNumber?: number;
  tripTitle?: string;
}

export interface AppNavigation {
  navigationTarget: NavigationTarget | null;
  setNavigationTarget: (target: NavigationTarget | null) => void;
  openInAppNavigation: (target: NavigationTarget, navigateFn?: (path: string) => void) => void;
}

export interface MapFocusTarget {
  id: string;
  name: string;
  category?: string;
  coordinates: [number, number]; // [lat, lng]
  zoom?: number;
  highlight?: boolean;
  address?: string;
}

export interface EventItem {
  id: string;
  title: string;
  date: string;
  time: string;
  location: string;
  coordinates: [number, number];
  category: string;
  image: string;
  price: number;
  description: string;
  tag?: string;
}

export interface ActivityItem {
  id: string;
  time: string;
  duration: string;
  title: string;
  category: 'flight' | 'cab' | 'hotel' | 'food' | 'beach' | 'culture' | 'nightlife' | 'activity' | 'Adventure' | 'Heritage' | 'Culinary' | 'Sights' | string;
  location: string;
  coordinates: [number, number];
  cost: number;
  description: string;
  photos: string[];
  bookingRef?: string;
  isBooked?: boolean;
  isCompleted?: boolean;
  tag?: string;
  rating?: number;
}

export interface ItineraryDay {
  dayNumber: number;
  date: string;
  title: string;
  tagline?: string;
  activities: ActivityItem[];
}

export interface Hotel {
  id: string;
  name: string;
  rating: number;
  reviewsCount: number;
  location: string;
  area: string;
  coordinates: [number, number];
  pricePerNight: number;
  totalPrice: number;
  photos: string[];
  amenities: string[];
  propertyType: 'Resort' | 'Boutique Hotel' | 'Luxury Hotel' | 'Villa';
  cancellationPolicy: string;
  rooms: {
    id: string;
    type: string;
    bed: string;
    price: number;
    capacity: string;
  }[];
}

export interface CabOption {
  id: string;
  type: 'Economy' | 'Sedan' | 'SUV' | 'Premium';
  name: string;
  capacity: string;
  etaMinutes: number;
  estimatedFare: number;
  image: string;
}

export interface Restaurant {
  id: string;
  name: string;
  rating: number;
  cuisine: string[];
  priceRange: '₹' | '₹₹' | '₹₹₹' | '₹₹₹₹';
  location: string;
  coordinates: [number, number];
  distanceKm: number;
  openingHours: string;
  photos: string[];
  dietary: string[];
}

export interface ExperienceActivity {
  id: string;
  name: string;
  category: 'Adventure' | 'Culture' | 'Nature' | 'Nightlife' | 'Food' | 'Shopping' | 'Family' | 'Photography';
  rating: number;
  duration: string;
  price: number;
  distanceKm: number;
  image: string;
  location: string;
  coordinates: [number, number];
}

export interface Booking {
  id: string;
  type: 'hotel' | 'flight' | 'train' | 'cab' | 'activity' | 'restaurant';
  title: string;
  status: 'confirmed' | 'pending' | 'cancelled' | 'in-transit';
  dateTime: string;
  location: string;
  confirmationCode: string;
  amount: number;
  paymentStatus: 'paid' | 'pay-at-venue' | 'refunded';
  details: Record<string, string>;
  image?: string;
}

export interface Expense {
  id: string;
  title: string;
  amount: number;
  category: 'Transport' | 'Hotel' | 'Food' | 'Activities' | 'Shopping' | 'Other';
  date: string;
  paidBy: string;
  isSplit: boolean;
  splitWith?: string[];
}

export interface TourPackage {
  id: string;
  title: string;
  destination: string;
  tagline: string;
  duration: string;
  nights: number;
  days: number;
  pricePerPerson: number;
  originalPrice?: number;
  rating: number;
  reviewsCount: number;
  coverImage: string;
  photos: string[];
  category: 'Trending' | 'Popular' | 'Luxury' | 'Weekend' | 'Adventure' | 'Beach';
  highlights: string[];
  inclusions: {
    hotelName: string;
    hotelRating: number;
    hotelImage: string;
    transfersCount: number;
    activitiesCount: number;
    diningCount: number;
  };
  itinerarySummary: { dayNumber: number; title: string }[];
}

export interface Destination {
  id: string;
  name: string;
  stateCountry: string;
  tagline: string;
  category: 'Trending' | 'Popular' | 'Hidden Gems' | 'Weekend' | 'Budget' | 'Luxury';
  bestTimeToVisit: string;
  estimatedBudget: string;
  recommendedDuration: string;
  image: string;
  description: string;
}

export interface UserProfile {
  name: string;
  email: string;
  phone: string;
  avatar: string;
  travelStyle: string[];
  budgetPreference: 'Budget' | 'Moderate' | 'Luxury';
  dietaryPreference: string[];
  accommodationPreference: string[];
  savedPlaces: string[];
}

export interface NotificationItem {
  id: string;
  title: string;
  message: string;
  time: string;
  type: 'reminder' | 'cab' | 'weather' | 'booking' | 'ai';
  read: boolean;
}

export interface Trip {
  id: string;
  destination: string;
  dates: string;
  status: TripStatus;
  travellersCount: number;
  budgetTotal: number;
  budgetSpent: number;
  coverImage?: string;
  tagline?: string;
  currentDay?: number;
  totalDays?: number;
  inclusions?: {
    hotelName: string;
    hotelNights: number;
    transfers: string;
    activitiesCount: number;
    diningCount: number;
  };
  weather: {
    temp: number;
    condition: string;
    icon: string;
  };
  itinerary: ItineraryDay[];
}

export type PackageItemStatus = 'RECOMMENDED' | 'SELECTED' | 'PENDING' | 'CONFIRMED' | 'CANCELLED';

export interface TripStay {
  id: string;
  tripId: string;
  activityId?: string;
  hotelName: string;
  locationName: string;
  checkInDate: string;
  checkOutDate: string;
  nights: number;
  pricePerNight: number;
  totalPrice: number;
  status: PackageItemStatus;
  confirmationCode?: string;
  createdAt: string;
  updatedAt?: string;
}

export interface TripTransport {
  id: string;
  tripId: string;
  activityId?: string;
  transportType: 'CAB' | 'FLIGHT' | 'TRAIN' | 'RENTAL';
  providerName: string;
  pickupLocation: string;
  dropoffLocation: string;
  pickupTime: string;
  estimatedFare: number;
  status: PackageItemStatus;
  bookingReference?: string;
  createdAt: string;
  updatedAt?: string;
}

export interface TripExpense {
  id: string;
  tripId: string;
  activityId?: string;
  title: string;
  amount: number;
  category: 'Transport' | 'Hotel' | 'Food' | 'Activities' | 'Shopping' | 'Other';
  paidBy: string;
  isSplit: boolean;
  createdAt: string;
}
