import type { Hotel, Restaurant, ExperienceActivity, Booking, Expense, UserProfile, NotificationItem, CabOption } from '../types';

export const mockHotels: Hotel[] = [
  {
    id: 'htl-1',
    name: 'W Goa Oceanfront Resort',
    rating: 4.8,
    reviewsCount: 1420,
    location: 'Vagator Beach, North Goa',
    area: 'Vagator',
    coordinates: [15.6015, 73.7329],
    pricePerNight: 9500,
    totalPrice: 38000,
    photos: [
      'https://images.unsplash.com/photo-1566073771259-6a8506099945?auto=format&fit=crop&w=800&q=80',
      'https://images.unsplash.com/photo-1582719478250-c89cae4dc85b?auto=format&fit=crop&w=800&q=80',
      'https://images.unsplash.com/photo-1571896349842-33c89424de2d?auto=format&fit=crop&w=800&q=80'
    ],
    amenities: ['Private Beach', 'Infinity Pool', 'Spa & Wellness', 'Free High-speed Wi-Fi', '24/7 Room Service', 'Cliffside Bar'],
    propertyType: 'Luxury Hotel',
    cancellationPolicy: 'Free cancellation up to 48 hours before check-in',
    rooms: [
      { id: 'r1', type: 'Wonderful Ocean View Room', bed: '1 King Bed', price: 9500, capacity: '2 Adults' },
      { id: 'r2', type: 'Spectacular Villa with Plunge Pool', bed: '1 King Bed', price: 18500, capacity: '3 Adults' }
    ]
  },
  {
    id: 'htl-2',
    name: 'Taj Exotica Resort & Spa',
    rating: 4.9,
    reviewsCount: 2180,
    location: 'Benaulim, South Goa',
    area: 'Benaulim',
    coordinates: [15.2530, 73.9189],
    pricePerNight: 12500,
    totalPrice: 50000,
    photos: [
      'https://images.unsplash.com/photo-1542314831-068cd1dbfeeb?auto=format&fit=crop&w=800&q=80',
      'https://images.unsplash.com/photo-1571003123894-1f0594d2b5d9?auto=format&fit=crop&w=800&q=80'
    ],
    amenities: ['Private Beach', 'Golf Course', 'Multiple Restaurants', 'Kids Play Zone', 'Airport Shuttles'],
    propertyType: 'Resort',
    cancellationPolicy: 'Free cancellation up to 72 hours before check-in',
    rooms: [
      { id: 'r3', type: 'Garden Villa', bed: '1 King Bed', price: 12500, capacity: '2 Adults' }
    ]
  }
];

export const mockCabOptions: CabOption[] = [
  {
    id: 'cab-econ',
    type: 'Economy',
    name: 'GoaMiles Hatchback (WagonR / Tiago)',
    capacity: '4 Passengers',
    etaMinutes: 6,
    estimatedFare: 450,
    image: 'https://images.unsplash.com/photo-1549317661-bd32c8ce0db2?auto=format&fit=crop&w=300&q=80'
  },
  {
    id: 'cab-sedan',
    type: 'Sedan',
    name: 'Comfort Sedan (Dzire / Etios)',
    capacity: '4 Passengers + Extra Luggage',
    etaMinutes: 4,
    estimatedFare: 650,
    image: 'https://images.unsplash.com/photo-1550355291-bbee04a92027?auto=format&fit=crop&w=300&q=80'
  }
];

export const mockRestaurants: Restaurant[] = [
  {
    id: 'rst-1',
    name: 'Thalassa Greek Restaurant',
    rating: 4.7,
    cuisine: ['Greek', 'Mediterranean', 'Seafood'],
    priceRange: '₹₹₹',
    location: 'Siolim Waterfront, North Goa',
    coordinates: [15.6267, 73.7482],
    distanceKm: 2.4,
    openingHours: '12:00 PM – 1:00 AM',
    photos: ['https://images.unsplash.com/photo-1517248135467-4c7edcad34c4?auto=format&fit=crop&w=800&q=80'],
    dietary: ['Vegetarian Friendly', 'Gluten Free Options', 'Seafood Special']
  },
  {
    id: 'rst-2',
    name: "Fisherman's Wharf",
    rating: 4.6,
    cuisine: ['Goan', 'Continental', 'Indian'],
    priceRange: '₹₹',
    location: 'Cavelossim & Vagator',
    coordinates: [15.6030, 73.7360],
    distanceKm: 0.8,
    openingHours: '11:00 AM – 11:30 PM',
    photos: ['https://images.unsplash.com/photo-1534422298391-e4f8c172dddb?auto=format&fit=crop&w=800&q=80'],
    dietary: ['Fresh Catch', 'Authentic Curry']
  }
];

export const mockExperiences: ExperienceActivity[] = [
  {
    id: 'exp-1',
    name: 'Scuba Diving & Coral Reef Exploration at Grand Island',
    category: 'Adventure',
    rating: 4.9,
    duration: '6 hrs',
    price: 3200,
    distanceKm: 12.0,
    image: 'https://images.unsplash.com/photo-1544551763-46a013bb70d5?auto=format&fit=crop&w=800&q=80',
    location: 'Grand Island Boat Point',
    coordinates: [15.3500, 73.7667]
  },
  {
    id: 'exp-2',
    name: 'Spice Plantation Tour & Elephant Bathing Experience',
    category: 'Nature',
    rating: 4.7,
    duration: '4 hrs',
    price: 1200,
    distanceKm: 18.5,
    image: 'https://images.unsplash.com/photo-1432405972618-c60b0225b8f9?auto=format&fit=crop&w=800&q=80',
    location: 'Tropical Spice Plantation, Ponda',
    coordinates: [15.4011, 74.0123]
  }
];

export const mockBookings: Booking[] = [
  {
    id: 'bk-1',
    type: 'hotel',
    title: 'W Goa Oceanfront Resort (4 Nights)',
    status: 'confirmed',
    dateTime: 'Check-in: 12 Sep 2026, 12:00 PM',
    location: 'Vagator Beach Rd, North Goa',
    confirmationCode: 'WGOA-982109',
    amount: 38000,
    paymentStatus: 'paid',
    details: {
      'Room Type': 'Wonderful Ocean View',
      'Guests': '4 Adults (2 Rooms)',
      'Inclusions': 'Breakfast, Wi-Fi, Sunset Lounge access'
    },
    image: 'https://images.unsplash.com/photo-1566073771259-6a8506099945?auto=format&fit=crop&w=800&q=80'
  },
  {
    id: 'bk-2',
    type: 'flight',
    title: 'IndiGo 6E-204 (BOM → GOX)',
    status: 'confirmed',
    dateTime: '12 Sep 2026, 08:15 AM',
    location: 'Terminal 2, Mumbai → GOX Mopa Airport',
    confirmationCode: '6E-IND-8812',
    amount: 18000,
    paymentStatus: 'paid',
    details: {
      'Seats': '12A, 12B, 12C, 12D',
      'Baggage': '15kg Check-in + 7kg Hand'
    },
    image: 'https://images.unsplash.com/photo-1542296332-2e4473faf563?auto=format&fit=crop&w=800&q=80'
  }
];

export const mockExpenses: Expense[] = [
  { id: 'exp-1', title: 'W Goa Resort Booking', amount: 9500, category: 'Hotel', date: '10 Sep', paidBy: 'Roshan', isSplit: true, splitWith: ['Aman', 'Priya', 'Rohan'] },
  { id: 'exp-2', title: 'Airport Cab Transfer', amount: 1400, category: 'Transport', date: '12 Sep', paidBy: 'Roshan', isSplit: true, splitWith: ['Aman', 'Priya', 'Rohan'] },
  { id: 'exp-3', title: "Seafood Lunch at Fisherman's Wharf", amount: 1800, category: 'Food', date: '12 Sep', paidBy: 'Aman', isSplit: true, splitWith: ['Roshan', 'Priya', 'Rohan'] }
];

export const mockUserProfile: UserProfile = {
  name: 'Roshan Sharma',
  email: 'roshan.sharma@example.com',
  phone: '+91 98765 12345',
  avatar: 'https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?auto=format&fit=crop&w=400&q=80',
  travelStyle: ['Beaches & Coast', 'Good Food & Fine Dining', 'Moderate Pace', 'Nightlife'],
  budgetPreference: 'Moderate',
  dietaryPreference: ['Non-Vegetarian', 'Seafood Enthusiast'],
  accommodationPreference: ['Oceanfront Resorts', '4 Star+', 'Boutique Villas'],
  savedPlaces: ['W Goa Oceanfront Resort', 'Fort Aguada', 'Thalassa Greek Restaurant', 'Munnar Tea Villa']
};

export const mockNotifications: NotificationItem[] = [
  {
    id: 'notif-1',
    title: 'Cab Arriving Soon',
    message: 'Your Sedan cab (GA-03-Z-8821) is 4 mins away at Mopa Airport Arrival Gate 4.',
    time: '2 mins ago',
    type: 'cab',
    read: false
  },
  {
    id: 'notif-2',
    title: 'Weather Update: Clear & Sunny',
    message: 'Ideal weather for sunset at Vagator Beach today. High of 31°C.',
    time: '1 hour ago',
    type: 'weather',
    read: false
  }
];
