import type { TravelStyle, TransportPreference, DietaryPreference, ActivityInterest, BudgetLevel } from '../../auth/types';

export type TripStatus = 'PLANNING' | 'UPCOMING' | 'ACTIVE' | 'COMPLETED' | 'CANCELLED' | 'ARCHIVED';
export type ItineraryStatus = 'GENERATING' | 'READY' | 'FAILED';

export interface DestinationReference {
  id?: string;
  name: string;
  city?: string;
  region?: string;
  country?: string;
  latitude?: number;
  longitude?: number;
  displayName?: string;
}

export interface CoverMedia {
  url: string;
  alt: string;
  provider: string;
}

export interface TripTraveler {
  id: string;
  userId?: string;
  name: string;
  type: 'ADULT' | 'CHILD';
  avatarUrl?: string;
}

export interface TripPreferencesSnapshot {
  travelStyles: TravelStyle[];
  transportPreferences: TransportPreference[];
  dietaryPreferences: DietaryPreference[];
  activityInterests: ActivityInterest[];
  budgetLevel?: BudgetLevel;
  snapshotVersion?: number;
}

export interface TripProgress {
  totalDays: number;
  currentDay: number;
  completedActivitiesCount: number;
  totalActivitiesCount: number;
}

export interface ItineraryActivity {
  id: string;
  timeSlot: string;
  title: string;
  description?: string;
  activityType: 'SIGHTSEEING' | 'DINING' | 'RELAXATION' | 'TRANSIT';
  locationName?: string;
  latitude?: number;
  longitude?: number;
  estimatedCostInr?: number;
  bookingRequired?: boolean;
  isConfirmed?: boolean;
  isDone?: boolean;
}

export interface ItineraryDay {
  id: string;
  dayNumber: number;
  date: string;
  title: string;
  summary?: string;
  activities: ItineraryActivity[];
}

export interface Itinerary {
  id: string;
  tripId: string;
  version: number;
  status: ItineraryStatus;
  providerName?: string;
  days: ItineraryDay[];
  createdAt?: string;
}

export interface Trip {
  id: string;
  userId: string;
  title: string;
  destination: DestinationReference;
  origin?: DestinationReference | null;
  coverImage?: string;
  coverMedia?: CoverMedia;
  startDate: string;
  endDate: string;
  totalDays?: number;
  travelers: TripTraveler[];
  adultsCount?: number;
  childrenCount?: number;
  budget?: TripBudget;
  status: TripStatus;
  itineraryStatus?: ItineraryStatus;
  tripStyle: TravelStyle[];
  transportPreferences: TransportPreference[];
  budgetLevel?: BudgetLevel;
  currency: string;
  preferencesSnapshot: TripPreferencesSnapshot;
  progress: TripProgress;
  createdAt: string;
  updatedAt: string;
}

export interface TripBudget {
  level?: BudgetLevel;
  targetAmount?: number | null;
  currency?: string;
}

export interface TripDraft {
  destination?: DestinationReference;
  origin?: DestinationReference | null;
  adultsCount?: number;
  childrenCount?: number;
  startDate?: string;
  endDate?: string;
  travelersCount?: number;
  tripStyle?: TravelStyle[];
  budgetLevel?: BudgetLevel;
  customBudgetAmount?: number;
  currentStep?: number;
  updatedAt?: string;
}

export interface CreateTripPayload {
  clientRequestId?: string;
  title?: string;
  destination: DestinationReference;
  origin?: DestinationReference | null;
  startDate: string;
  endDate: string;
  adultsCount: number;
  childrenCount: number;
  tripStyle?: TravelStyle[];
  budgetAmount: number;
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
  transportType: 'CAB' | 'FLIGHT' | 'TRAIN' | 'BUS' | 'RENTAL';
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
