import type { Trip, Hotel, Restaurant, ExperienceActivity, Destination, Booking, Expense, UserProfile, NotificationItem, CabOption, TourPackage } from '../types';

export const mockGoaTrip: Trip = {
  id: 'trip-goa-2026',
  destination: 'Goa',
  dates: '12 – 16 September 2026',
  status: 'active',
  travellersCount: 4,
  budgetTotal: 30000,
  budgetSpent: 18400,
  currentDay: 2,
  totalDays: 4,
  coverImage: 'https://images.unsplash.com/photo-1512343879784-a960bf40e7f2?auto=format&fit=crop&w=1200&q=80',
  tagline: 'Beach resorts, Portuguese forts & oceanfront fine dining',
  inclusions: {
    hotelName: 'W Goa Oceanfront Resort',
    hotelNights: 4,
    transfers: 'Private Sedan Airport Transfers',
    activitiesCount: 8,
    diningCount: 4,
  },
  weather: {
    temp: 31,
    condition: 'Sunny with sea breeze',
    icon: 'Sun'
  },
  itinerary: [
    {
      dayNumber: 1,
      date: '12 Sep',
      title: 'Arrival & North Goa Vibes',
      tagline: 'Your first day in coastal paradise',
      activities: [
        {
          id: 'act-101',
          time: '09:30',
          duration: '1 hr',
          title: 'Arrive at Mopa International Airport (GOX)',
          category: 'flight',
          location: 'North Goa Airport (GOX)',
          coordinates: [15.7533, 73.8767],
          cost: 4500,
          description: 'Flight 6E-204 landed safely. Collect baggage at Belt 3.',
          photos: ['https://images.unsplash.com/photo-1542296332-2e4473faf563?auto=format&fit=crop&w=800&q=80'],
          bookingRef: '6E-GOA982',
          isBooked: true,
          isCompleted: true
        },
        {
          id: 'act-102',
          time: '10:30',
          duration: '45 mins',
          title: 'Private Airport Transfer to W Goa',
          category: 'cab',
          location: 'Vagator Beach Rd, North Goa',
          coordinates: [15.6022, 73.7336],
          cost: 1400,
          description: 'Chauffeur Sedan. Driver: Rajesh (GA-03-Z-8821).',
          photos: ['https://images.unsplash.com/photo-1549317661-bd32c8ce0db2?auto=format&fit=crop&w=800&q=80'],
          bookingRef: 'CAB-882109',
          isBooked: true,
          isCompleted: true
        },
        {
          id: 'act-103',
          time: '12:00',
          duration: '1 hr',
          title: 'Check-in at W Goa Resort & Villa',
          category: 'hotel',
          location: 'Vagator Beach, Bardez',
          coordinates: [15.6015, 73.7329],
          cost: 9500,
          description: 'Wonderful Ocean View Room with complimentary welcome mocktail.',
          photos: ['https://images.unsplash.com/photo-1566073771259-6a8506099945?auto=format&fit=crop&w=800&q=80'],
          bookingRef: 'HTL-WGOA-992',
          isBooked: true,
          isCompleted: true
        },
        {
          id: 'act-104',
          time: '13:30',
          duration: '1.5 hrs',
          title: 'Authentic Goan Seafood Lunch',
          category: 'food',
          location: "Fisherman's Wharf, Vagator",
          coordinates: [15.6030, 73.7360],
          cost: 1800,
          description: 'Try the Prawn Balchão and Goan Fish Curry Thali.',
          photos: ['https://images.unsplash.com/photo-1534422298391-e4f8c172dddb?auto=format&fit=crop&w=800&q=80'],
          isCompleted: true
        },
        {
          id: 'act-105',
          time: '16:00',
          duration: '2.5 hrs',
          title: 'Sunset at Vagator Beach & Chapora Fort',
          category: 'beach',
          location: 'Chapora Fort Trail',
          coordinates: [15.6056, 73.7372],
          cost: 0,
          description: 'Iconic panoramic viewpoint famous from Dil Chahta Hai.',
          photos: ['https://images.unsplash.com/photo-1507525428034-b723cf961d3e?auto=format&fit=crop&w=800&q=80'],
          isCompleted: true
        },
        {
          id: 'act-106',
          time: '21:00',
          duration: '2 hrs',
          title: 'Dinner & Greek Vibes at Thalassa',
          category: 'nightlife',
          location: 'Siolim Waterfront',
          coordinates: [15.6267, 73.7482],
          cost: 2200,
          description: 'Cliffside sunset dining with live fire dancers.',
          photos: ['https://images.unsplash.com/photo-1517248135467-4c7edcad34c4?auto=format&fit=crop&w=800&q=80'],
          isCompleted: true
        }
      ]
    },
    {
      dayNumber: 2,
      date: '13 Sep',
      title: 'Heritage Forts & Sunset Cruise',
      tagline: 'Historical Portuguese forts and Mandovi River sailing',
      activities: [
        {
          id: 'act-201',
          time: '09:00',
          duration: '1 hr',
          title: 'Breakfast at Olive Bar & Kitchen',
          category: 'food',
          location: 'Vagator Cliff',
          coordinates: [15.6010, 73.7310],
          cost: 800,
          description: 'Smoothie bowls and espresso over oceanic view.',
          photos: ['https://images.unsplash.com/photo-1533089860892-a7c6f0a88666?auto=format&fit=crop&w=800&q=80'],
          isCompleted: true
        },
        {
          id: 'act-202',
          time: '10:00',
          duration: '2.5 hrs',
          title: 'Baga Beach Watersports & Sunbathing',
          category: 'beach',
          location: 'Baga Beach Boardwalk',
          coordinates: [15.5553, 73.7517],
          cost: 1500,
          description: 'Parasailing and jet ski sessions on golden sands.',
          photos: ['https://images.unsplash.com/photo-1507525428034-b723cf961d3e?auto=format&fit=crop&w=800&q=80'],
          isCompleted: false
        },
        {
          id: 'act-203',
          time: '13:00',
          duration: '1.5 hrs',
          title: 'Shack Lunch at Brittos',
          category: 'food',
          location: 'Baga Beach Boardwalk',
          coordinates: [15.5553, 73.7517],
          cost: 1200,
          description: 'Classic Baga beach shack serving crab xacuti and cold drinks.',
          photos: ['https://images.unsplash.com/photo-1555396273-367ea4eb4db5?auto=format&fit=crop&w=800&q=80'],
          isCompleted: false
        },
        {
          id: 'act-204',
          time: '16:00',
          duration: '2 hrs',
          title: 'Historical Tour of Fort Aguada & Lighthouse',
          category: 'culture',
          location: 'Sinquerim, Candolim',
          coordinates: [15.4927, 73.7736],
          cost: 200,
          description: '17th-century Portuguese fortress with massive freshwater storage cistern.',
          photos: ['https://images.unsplash.com/photo-1590050752117-238cb0fb12b1?auto=format&fit=crop&w=800&q=80'],
          isCompleted: false
        },
        {
          id: 'act-205',
          time: '18:30',
          duration: '2 hrs',
          title: 'Catamaran Sunset Cruise on Mandovi River',
          category: 'activity',
          location: 'Panjim Jetty',
          coordinates: [15.4989, 73.8278],
          cost: 1500,
          description: 'Live Goan folk music, open bar snacks, and dolphin sighting opportunity.',
          photos: ['https://images.unsplash.com/photo-1500530855697-b586d89ba3ee?auto=format&fit=crop&w=800&q=80'],
          isCompleted: false
        }
      ]
    },
    {
      dayNumber: 3,
      date: '14 Sep',
      title: 'Old Goa Latin Quarter & Water Sports',
      tagline: 'Colonial heritage walks and high-speed water adventures',
      activities: [
        {
          id: 'act-301',
          time: '10:00',
          duration: '2 hrs',
          title: 'Fontainhas Heritage Walk (Latin Quarter)',
          category: 'culture',
          location: 'Fontainhas, Panaji',
          coordinates: [15.4942, 73.8322],
          cost: 500,
          description: 'Cobblestone streets, colorful Portuguese homes, and art bakeries.',
          photos: ['https://images.unsplash.com/photo-1582510003544-4d00b7f74220?auto=format&fit=crop&w=800&q=80'],
          isCompleted: false
        },
        {
          id: 'act-302',
          time: '14:30',
          duration: '3 hrs',
          title: 'Jet Skiing & Parasailing Adventure',
          category: 'activity',
          location: 'Calangute Beach Watersports Hub',
          coordinates: [15.5439, 73.7553],
          cost: 2500,
          description: 'High-speed sea jet ride & tandem aerial parasailing with boat launch.',
          photos: ['https://images.unsplash.com/photo-1544551763-46a013bb70d5?auto=format&fit=crop&w=800&q=80'],
          isCompleted: false
        }
      ]
    },
    {
      dayNumber: 4,
      date: '15 Sep',
      title: 'South Goa Tranquility & Departure Prep',
      tagline: 'Waterfall safari and departure transfer',
      activities: [
        {
          id: 'act-401',
          time: '10:30',
          duration: '3 hrs',
          title: 'Dudhsagar Waterfalls Jeep Safari',
          category: 'activity',
          location: 'Mollem National Park',
          coordinates: [15.3144, 74.3143],
          cost: 1800,
          description: 'Four-wheel drive through dense jungle streams to the multi-tiered waterfall.',
          photos: ['https://images.unsplash.com/photo-1432405972618-c60b0225b8f9?auto=format&fit=crop&w=800&q=80'],
          isCompleted: false
        }
      ]
    }
  ]
};

export const mockTourPackages: TourPackage[] = [
  {
    id: 'pkg-goa-weekend',
    title: 'Goa Coastal Escape',
    destination: 'Goa, India',
    tagline: 'Oceanfront resort stay, Portuguese fort sunset, catamaran cruise & seafood dining',
    duration: '4 Days / 3 Nights',
    nights: 3,
    days: 4,
    pricePerPerson: 22000,
    originalPrice: 28000,
    rating: 4.9,
    reviewsCount: 342,
    coverImage: 'https://images.unsplash.com/photo-1512343879784-a960bf40e7f2?auto=format&fit=crop&w=1000&q=80',
    photos: [
      'https://images.unsplash.com/photo-1512343879784-a960bf40e7f2?auto=format&fit=crop&w=800&q=80',
      'https://images.unsplash.com/photo-1566073771259-6a8506099945?auto=format&fit=crop&w=800&q=80',
      'https://images.unsplash.com/photo-1507525428034-b723cf961d3e?auto=format&fit=crop&w=800&q=80',
    ],
    category: 'Trending',
    highlights: [
      '3 Nights luxury oceanfront stay at W Goa',
      'Private airport sedan transfers included',
      'Mandovi River catamaran sunset cruise',
      'Fontainhas Latin Quarter guided heritage walk',
      'Curated seafood dining at Thalassa & Brittos'
    ],
    inclusions: {
      hotelName: 'W Goa Oceanfront Resort',
      hotelRating: 4.8,
      hotelImage: 'https://images.unsplash.com/photo-1566073771259-6a8506099945?auto=format&fit=crop&w=800&q=80',
      transfersCount: 2,
      activitiesCount: 6,
      diningCount: 3
    },
    itinerarySummary: [
      { dayNumber: 1, title: 'Arrival & Cliffside Sunset at Chapora' },
      { dayNumber: 2, title: 'Baga Watersports & Mandovi River Cruise' },
      { dayNumber: 3, title: 'Latin Quarter Heritage Walk & Thalassa Dinner' },
      { dayNumber: 4, title: 'Dudhsagar Jeep Safari & Departure' }
    ]
  },
  {
    id: 'pkg-kerala-backwaters',
    title: 'Kerala Backwaters & Tea Hills',
    destination: 'Kerala, India',
    tagline: 'Private luxury houseboat cruise in Alleppey & tea estate villa in Munnar',
    duration: '5 Days / 4 Nights',
    nights: 4,
    days: 5,
    pricePerPerson: 26500,
    originalPrice: 32000,
    rating: 4.95,
    reviewsCount: 512,
    coverImage: 'https://images.unsplash.com/photo-1602216056096-3b40cc0c9944?auto=format&fit=crop&w=1000&q=80',
    photos: [
      'https://images.unsplash.com/photo-1602216056096-3b40cc0c9944?auto=format&fit=crop&w=800&q=80',
      'https://images.unsplash.com/photo-1593693397690-362cb9666fc2?auto=format&fit=crop&w=800&q=80',
    ],
    category: 'Popular',
    highlights: [
      '1 Night private luxury houseboat stay in Alleppey',
      '3 Nights mist-covered tea estate villa in Munnar',
      'Kathakali cultural dance & Ayurvedic spa session',
      'Spice plantation guided tour with chef lunch'
    ],
    inclusions: {
      hotelName: 'Spice Tree Munnar & Alleppey Houseboat',
      hotelRating: 4.9,
      hotelImage: 'https://images.unsplash.com/photo-1593693397690-362cb9666fc2?auto=format&fit=crop&w=800&q=80',
      transfersCount: 3,
      activitiesCount: 7,
      diningCount: 5
    },
    itinerarySummary: [
      { dayNumber: 1, title: 'Cochin Arrival & Drive to Munnar Tea Gardens' },
      { dayNumber: 2, title: 'Eravikulam National Park & Tea Factory Tour' },
      { dayNumber: 3, title: 'Scenic Transfer to Alleppey & Houseboat Boarding' },
      { dayNumber: 4, title: 'Tranquil Lake Sailing & Traditional Sadya Feast' },
      { dayNumber: 5, title: 'Fort Kochi Heritage Walk & Airport Drop' }
    ]
  },
  {
    id: 'pkg-kashmir-heaven',
    title: 'Kashmir Paradise & Gulmarg Snow',
    destination: 'Srinagar & Gulmarg, India',
    tagline: 'Nigeen lake luxury shikara houseboat & Gulmarg Gondola snow ride',
    duration: '6 Days / 5 Nights',
    nights: 5,
    days: 6,
    pricePerPerson: 38000,
    originalPrice: 46000,
    rating: 4.98,
    reviewsCount: 689,
    coverImage: 'https://images.unsplash.com/photo-1566837945700-30057527ade0?auto=format&fit=crop&w=1000&q=80',
    photos: [
      'https://images.unsplash.com/photo-1566837945700-30057527ade0?auto=format&fit=crop&w=800&q=80',
      'https://images.unsplash.com/photo-1595815771614-ade9d652a65d?auto=format&fit=crop&w=800&q=80',
    ],
    category: 'Luxury',
    highlights: [
      '2 Nights heritage carved cedarwood houseboat on Nigeen Lake',
      '2 Nights snow mountain resort in Gulmarg',
      'Phase 2 Gulmarg Gondola high-altitude cable car passes',
      'Private Shikara sunset ride with Kahwa tea service'
    ],
    inclusions: {
      hotelName: 'The Khyber Himalayan Resort & Sukoon Houseboat',
      hotelRating: 4.95,
      hotelImage: 'https://images.unsplash.com/photo-1595815771614-ade9d652a65d?auto=format&fit=crop&w=800&q=80',
      transfersCount: 4,
      activitiesCount: 9,
      diningCount: 6
    },
    itinerarySummary: [
      { dayNumber: 1, title: 'Srinagar Arrival & Nigeen Lake Sunset Shikara' },
      { dayNumber: 2, title: 'Mughal Gardens Tour & Kashmiri Wazwan Feast' },
      { dayNumber: 3, title: 'Scenic Alpine Drive to Gulmarg' },
      { dayNumber: 4, title: 'Gondola Ride to Apharwat Peak (13,780 ft)' },
      { dayNumber: 5, title: 'Pahalgam Valley & Betaab Valley Exploration' },
      { dayNumber: 6, title: 'Souvenir Shopping & Departure' }
    ]
  },
  {
    id: 'pkg-udaipur-rajasthan',
    title: 'Udaipur Royal Palaces & Lakes',
    destination: 'Udaipur & Jaipur, India',
    tagline: 'Lake Pichola heritage palace villa, private Amber Fort tour & royal Thali dining',
    duration: '6 Days / 5 Nights',
    nights: 5,
    days: 6,
    pricePerPerson: 42000,
    originalPrice: 52000,
    rating: 4.96,
    reviewsCount: 428,
    coverImage: 'https://images.unsplash.com/photo-1599661046289-e318977467cac?auto=format&fit=crop&w=1000&q=80',
    photos: [
      'https://images.unsplash.com/photo-1599661046289-e318977467cac?auto=format&fit=crop&w=800&q=80'
    ],
    category: 'Luxury',
    highlights: [
      'Lakeview suite at Taj Lake Palace Udaipur',
      'Private boat cruise on Lake Pichola at sunset',
      'Amber Fort guided tour & Royal Rajasthani Thali feast'
    ],
    inclusions: {
      hotelName: 'Taj Lake Palace Udaipur',
      hotelRating: 4.95,
      hotelImage: 'https://images.unsplash.com/photo-1599661046289-e318977467cac?auto=format&fit=crop&w=800&q=80',
      transfersCount: 3,
      activitiesCount: 8,
      diningCount: 6
    },
    itinerarySummary: [
      { dayNumber: 1, title: 'Udaipur Arrival & Lake Pichola Sunset Cruise' },
      { dayNumber: 2, title: 'City Palace & Jagdish Temple Tour' },
      { dayNumber: 3, title: 'Scenic Transfer to Jaipur via Chittorgarh Fort' },
      { dayNumber: 4, title: 'Amber Fort & Hawa Mahal Heritage Walk' },
      { dayNumber: 5, title: 'Johari Bazaar Shopping & Royal Thali Feast' },
      { dayNumber: 6, title: 'Departure' }
    ]
  }
];

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

export const mockDestinations: Destination[] = [
  {
    id: 'dest-goa',
    name: 'Goa',
    stateCountry: 'India',
    tagline: 'Sun-kissed beaches, Portuguese heritage, and vibrant nightlife.',
    category: 'Trending',
    bestTimeToVisit: 'November to February',
    estimatedBudget: '₹22,000 / person',
    recommendedDuration: '4 Days / 3 Nights',
    image: 'https://images.unsplash.com/photo-1512343879784-a960bf40e7f2?auto=format&fit=crop&w=800&q=80',
    description: 'A coastal paradise blending colonial Portuguese architecture with palm-lined golden sands.'
  },
  {
    id: 'dest-kerala',
    name: 'Kerala Backwaters',
    stateCountry: 'India',
    tagline: "God's Own Country with serene houseboats and lush tea gardens.",
    category: 'Popular',
    bestTimeToVisit: 'September to March',
    estimatedBudget: '₹26,500 / person',
    recommendedDuration: '5 Days / 4 Nights',
    image: 'https://images.unsplash.com/photo-1602216056096-3b40cc0c9944?auto=format&fit=crop&w=800&q=80',
    description: 'Cruise tranquil backwaters in Alleppey, wander through Munnar tea hills, and experience Ayurveda.'
  },
  {
    id: 'dest-jaipur',
    name: 'Jaipur & Udaipur',
    stateCountry: 'Rajasthan, India',
    tagline: 'Royal palaces, lakefront forts, and rich Rajasthani heritage.',
    category: 'Popular',
    bestTimeToVisit: 'October to March',
    estimatedBudget: '₹24,000 / person',
    recommendedDuration: '5 Days / 4 Nights',
    image: 'https://images.unsplash.com/photo-1477587458883-47145ed94245?auto=format&fit=crop&w=800&q=80',
    description: 'Immerse in royal heritage, grand palaces, vibrant bazaars, and sunset boat rides on Lake Pichola.'
  },
  {
    id: 'dest-amalfi',
    name: 'Amalfi Coast',
    stateCountry: 'Italy',
    tagline: 'Dramatic cliffside villages, turquoise waters, and Mediterranean dining.',
    category: 'Luxury',
    bestTimeToVisit: 'May to September',
    estimatedBudget: '₹145,000 / person',
    recommendedDuration: '6 Days / 5 Nights',
    image: 'https://images.unsplash.com/photo-1533105079780-92b9be482077?auto=format&fit=crop&w=800&q=80',
    description: 'Savor limoncello overlooking Positano cliffs and sail past Capri grottos.'
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
