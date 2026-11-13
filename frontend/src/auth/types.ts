export type AuthProvider = 'GOOGLE' | 'APPLE' | 'PHONE' | 'EMAIL';
export type AccountStatus = 'ACTIVE' | 'SUSPENDED' | 'DELETED';
export type OnboardingStatus = 'NOT_STARTED' | 'IN_PROGRESS' | 'COMPLETED' | 'SKIPPED';

export type OnboardingStep = 'welcome' | 'profile' | 'travel_style' | 'transport' | 'food' | 'activities' | 'budget' | 'ready' | 'preferences' | 'PREFERENCES';

export type TravelStyle = 'RELAXED' | 'ADVENTURE' | 'CULTURE' | 'FOODIE' | 'NATURE' | 'LUXURY' | 'BUDGET' | 'NIGHTLIFE';
export type TransportPreference = 'WALK' | 'BIKE' | 'AUTO' | 'CAB' | 'PUBLIC_TRANSPORT';
export type DietaryPreference = 'EVERYTHING' | 'VEGETARIAN' | 'VEGAN' | 'JAIN' | 'HALAL' | 'GLUTEN_FREE' | 'OTHER';
export type FoodInterest = 'LOCAL' | 'STREET_FOOD' | 'CAFE' | 'FINE_DINING' | 'FAST_FOOD' | 'DESSERTS' | 'SEAFOOD';
export type ActivityInterest = 'BEACHES' | 'NATURE' | 'HISTORY' | 'CULTURE' | 'ADVENTURE' | 'SHOPPING' | 'NIGHTLIFE' | 'PHOTOGRAPHY' | 'WELLNESS' | 'FOOD';
export type BudgetLevel = 'BUDGET' | 'MODERATE' | 'PREMIUM' | 'LUXURY';

export interface AuthUser {
  id: string;
  provider: AuthProvider;
  providerUserId: string;
  email?: string;
  phone?: string;
  emailVerified: boolean;
  phoneVerified: boolean;
  status: AccountStatus;
  createdAt: string;
  lastLoginAt: string;
}

export interface UserProfile {
  userId: string;
  firstName: string;
  lastName?: string;
  avatarUrl?: string;
  preferredLanguage: string;
  preferredCurrency: string;
  timezone: string;
  onboardingStatus: OnboardingStatus;
  onboardingStep: OnboardingStep;
  createdAt: string;
  updatedAt: string;
}

export interface UserPreferences {
  userId: string;
  travelStyles: TravelStyle[];
  transportPreferences: TransportPreference[];
  dietaryPreferences: DietaryPreference[];
  foodInterests: FoodInterest[];
  activityInterests: ActivityInterest[];
  budgetLevel?: BudgetLevel;
  createdAt: string;
  updatedAt: string;
}

export interface SessionData {
  token?: string;
  authUser: AuthUser;
  userProfile: UserProfile;
  userPreferences: UserPreferences;
}

export interface LoginPayload {
  provider: AuthProvider;
  email?: string;
  password?: string;
  phone?: string;
  name?: string;
  avatarUrl?: string;
  isRegister?: boolean;
}

export interface OnboardingUpdatePayload {
  firstName?: string;
  lastName?: string;
  travelStyles?: TravelStyle[];
  transportPreferences?: TransportPreference[];
  dietaryPreferences?: DietaryPreference[];
  foodInterests?: FoodInterest[];
  activityInterests?: ActivityInterest[];
  budgetLevel?: BudgetLevel;
  onboardingStep?: OnboardingStep;
  onboardingStatus?: OnboardingStatus;
}

export interface RegisterPayload {
  name: string;
  email: string;
  password: string;
}
