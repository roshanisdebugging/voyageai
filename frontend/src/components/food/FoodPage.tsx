import React, { useState, useEffect } from 'react';
import { useToast } from '../common/UndoToast';
import { useNavigate } from 'react-router-dom';
import { useApp } from '../../context/AppContext';
import { useTrip } from '../../features/trip/TripContext';
import {
  UtensilsCrossed, ArrowLeft, Star, MapPin, Sparkles, Car, Navigation,
  Flame, Compass, RefreshCw
} from 'lucide-react';
import { wsClient } from '../../services/wsClient';
import { SafeImage } from '../common/SafeImage';

interface FoodItem {
  id: string;
  name: string;
  category: string;
  price: string;
  rating: number;
  isVeg: boolean;
  image: string;
  description: string;
}

const DESTINATION_FOOD_ITEMS: Record<string, FoodItem[]> = {
  'Kerala': [
    { id: 'k1', name: 'Kerala Sadya Feast', category: 'Traditional', price: '₹350', rating: 4.9, isVeg: true, image: 'https://images.unsplash.com/photo-1610192244261-3f33de3f55e4?auto=format&fit=crop&w=800&q=80', description: 'Elaborate 24-course traditional banana leaf banquet with Avial, Sambhar, Thoran & Payasam.' },
    { id: 'k2', name: 'Appam with Coconut Stew', category: 'Breakfast', price: '₹180', rating: 4.8, isVeg: true, image: 'https://images.unsplash.com/photo-1589301760014-d929f3979dbc?auto=format&fit=crop&w=800&q=80', description: 'Soft fluffy fermented rice pancakes with fragrant creamy coconut vegetable stew.' },
    { id: 'k3', name: 'Malabar Fish Curry', category: 'Seafood', price: '₹420', rating: 4.9, isVeg: false, image: 'https://images.unsplash.com/photo-1534422298391-e4f8c172dddb?auto=format&fit=crop&w=800&q=80', description: 'Fresh king fish cooked in spicy red chili tamarind coconut gravy.' },
    { id: 'k4', name: 'Karimeen Pollichathu', category: 'Seafood Special', price: '₹550', rating: 4.9, isVeg: false, image: 'https://images.unsplash.com/photo-1519708227418-c8fd9a32b7a2?auto=format&fit=crop&w=800&q=80', description: 'Pearl spot fish marinated in aromatic Kerala spices and slow-roasted inside a banana leaf.' },
    { id: 'k5', name: 'Kerala Parotta & Roast', category: 'Street Special', price: '₹260', rating: 4.8, isVeg: false, image: 'https://images.unsplash.com/photo-1626777552726-4a6b54c97e46?auto=format&fit=crop&w=800&q=80', description: 'Flaky layered Malabar parottas served with spicy caramelised onion roast curry.' }
  ],
  'Bihar': [
    { id: 'b1', name: 'Special Litti Chokha', category: 'Heritage', price: '₹120', rating: 4.9, isVeg: true, image: 'https://images.unsplash.com/photo-1626777552726-4a6b54c97e46?auto=format&fit=crop&w=800&q=80', description: 'Traditional wheat balls stuffed with spiced sattu, dipped in desi ghee & served with brinjal-potato chokha.' },
    { id: 'b2', name: 'Champaran Ahuna Curry', category: 'Local Special', price: '₹480', rating: 4.9, isVeg: false, image: 'https://images.unsplash.com/photo-1545247181-516773cae754?auto=format&fit=crop&w=800&q=80', description: 'Slow cooked in sealed clay handi with whole garlic cloves and mustard oil over wood coals.' },
    { id: 'b3', name: 'Patna Sweet Khaja', category: 'Sweets', price: '₹150', rating: 4.8, isVeg: true, image: 'https://images.unsplash.com/photo-1599488615731-7e5c2823ff28?auto=format&fit=crop&w=800&q=80', description: 'Crispy multi-layered golden deep-fried pastry soaked in sugar syrup.' },
    { id: 'b4', name: 'Sattu Paratha & Chutney', category: 'Breakfast', price: '₹90', rating: 4.7, isVeg: true, image: 'https://images.unsplash.com/photo-1601050690597-df0568f70950?auto=format&fit=crop&w=800&q=80', description: 'Protein-packed roasted gram flour stuffed flatbread with spicy garlic coriander chutney.' }
  ],
  'Patna': [
    { id: 'b1', name: 'Special Litti Chokha', category: 'Heritage', price: '₹120', rating: 4.9, isVeg: true, image: 'https://images.unsplash.com/photo-1626777552726-4a6b54c97e46?auto=format&fit=crop&w=800&q=80', description: 'Traditional wheat balls stuffed with spiced sattu, dipped in desi ghee & served with brinjal-potato chokha.' },
    { id: 'b2', name: 'Champaran Ahuna Curry', category: 'Local Special', price: '₹480', rating: 4.9, isVeg: false, image: 'https://images.unsplash.com/photo-1545247181-516773cae754?auto=format&fit=crop&w=800&q=80', description: 'Slow cooked in sealed clay handi with whole garlic cloves and mustard oil over wood coals.' },
    { id: 'b3', name: 'Patna Sweet Khaja', category: 'Sweets', price: '₹150', rating: 4.8, isVeg: true, image: 'https://images.unsplash.com/photo-1599488615731-7e5c2823ff28?auto=format&fit=crop&w=800&q=80', description: 'Crispy multi-layered golden deep-fried pastry soaked in sugar syrup.' }
  ],
  'Goa': [
    { id: 'g1', name: 'Goan Fish Curry Rice', category: 'Classic', price: '₹320', rating: 4.9, isVeg: false, image: 'https://images.unsplash.com/photo-1534422298391-e4f8c172dddb?auto=format&fit=crop&w=800&q=80', description: 'Tangy coconut kokum curry served with steamed red rice and fried pomfret.' },
    { id: 'g2', name: 'Pork Vindaloo', category: 'Portuguese Fusion', price: '₹420', rating: 4.8, isVeg: false, image: 'https://images.unsplash.com/photo-1545247181-516773cae754?auto=format&fit=crop&w=800&q=80', description: 'Spicy marinated meat slow cooked in palm vinegar and red Kashmiri chilies.' },
    { id: 'g3', name: 'Bebinca Dessert', category: 'Sweets', price: '₹220', rating: 4.9, isVeg: true, image: 'https://images.unsplash.com/photo-1587314168485-3236d6710814?auto=format&fit=crop&w=800&q=80', description: 'Traditional 7-layered Goan coconut milk pudding baked layer by layer.' }
  ]
};

export const FoodPage: React.FC = () => {
  const navigate = useNavigate();
  const { openCabModal, openAiAssistant, openInAppNavigation, setTripView, setActiveTab, userLocationName } = useApp();
  const { currentTrip } = useTrip();

  const activeDestName = currentTrip?.destination?.name || 'Kerala';
  const destFoodItems = DESTINATION_FOOD_ITEMS[activeDestName] || DESTINATION_FOOD_ITEMS['Kerala'];

  const [activeCategory, setActiveCategoryState] = useState<string>('All');
  const { showToast } = useToast();
  const setActiveCategory = (cat: string) => {
    if (cat === activeCategory) return;
    const previous = activeCategory;
    setActiveCategoryState(cat);
    showToast({ message: `Showing ${cat}`, undo: () => setActiveCategoryState(previous) });
  };
  const [nearbyRestaurants, setNearbyRestaurants] = useState<any[]>([]);
  const [isLoadingRestaurants, setIsLoadingRestaurants] = useState<boolean>(true);
  const [filterVegOnly, setFilterVegOnly] = useState<boolean>(false);

  // Fetch real nearby dining spots via WebSocket
  useEffect(() => {
    let isMounted = true;
    const fetchDining = async () => {
      setIsLoadingRestaurants(true);
      try {
        const data = await wsClient.sendRequest('places:nearby', { query: activeDestName, category: 'restaurant' });
        if (isMounted && Array.isArray(data) && data.length > 0) {
          setNearbyRestaurants(data);
        }
      } catch (err) {
        console.warn('Failed to fetch nearby restaurants over WebSocket:', err);
      } finally {
        if (isMounted) setIsLoadingRestaurants(false);
      }
    };

    fetchDining();
    return () => { isMounted = false; };
  }, [activeDestName]);

  const categories = ['All', 'Popular Regional', 'Street Food', 'Sweets', 'Fine Dining'];

  const filteredDishes = destFoodItems.filter(dish => {
    if (filterVegOnly && !dish.isVeg) return false;
    if (activeCategory === 'All') return true;
    return dish.category.toLowerCase().includes(activeCategory.toLowerCase()) || activeCategory === 'Popular Regional';
  });

  return (
    <div className="space-y-6 pb-28 max-w-xl mx-auto animate-fadeIn">
      {/* Header Bar */}
      <div className="flex items-center justify-between pt-1">
        <button
          type="button"
          onClick={() => {
            setTripView('home');
            setActiveTab('trips');
            navigate('/');
          }}
          className="px-3 py-1.5 rounded-xl bg-white hover:bg-[#E8F0EE] text-[#355F58] text-xs font-black flex items-center gap-1.5 border border-[#D9DEDA] transition-all press-scale"
        >
          <ArrowLeft className="w-4 h-4 text-[#355F58]" />
          <span>Back to Trip</span>
        </button>

        <div className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-[#E8F0EE] text-[#355F58] border border-[#D9DEDA] text-xs font-bold">
          <UtensilsCrossed className="w-3.5 h-3.5" />
          <span>{activeDestName} Food Guide</span>
        </div>
      </div>

      {/* Hero Banner */}
      <div className="relative rounded-3xl p-6 bg-white border border-[#D9DEDA] shadow-xs space-y-3 overflow-hidden">
        <div className="flex items-center gap-2">
          <span className="px-2.5 py-1 rounded-full bg-amber-100 text-amber-800 text-[10px] font-black uppercase tracking-wider border border-amber-200 flex items-center gap-1">
            <Flame className="w-3 h-3 text-amber-600" />
            Popular Dining & Local Dishes
          </span>
          <span className="text-xs text-[#5F6863] font-bold">• {userLocationName || activeDestName}</span>
        </div>

        <h1 className="text-2xl font-black text-[#1F2522] tracking-tight">
          What to Eat in {activeDestName}
        </h1>
        <p className="text-xs text-[#5F6863] leading-relaxed">
          Discover authentic culinary specialties, famous street food, and top-rated restaurants curated specifically for your {activeDestName} journey.
        </p>

        {/* Veg Only Toggle */}
        <div className="pt-2 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setFilterVegOnly(!filterVegOnly)}
              className={`px-3 py-1.5 rounded-xl text-xs font-extrabold flex items-center gap-1.5 transition-all border ${
                filterVegOnly
                  ? 'bg-emerald-700 text-white border-emerald-600 shadow-xs'
                  : 'bg-[#F0F2EF] text-[#1F2522] border-[#D9DEDA] hover:border-emerald-600/50'
              }`}
            >
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-600 border border-emerald-700" />
              <span>Pure Veg Only</span>
            </button>
          </div>

          <button
            type="button"
            onClick={() => openAiAssistant(`Recommend top 3 must-try food dishes and best places to eat in ${activeDestName}`)}
            className="px-3.5 py-1.5 rounded-xl bg-[#355F58] hover:bg-[#2C504A] text-white font-black text-xs shadow-xs transition-all flex items-center gap-1.5 press-scale"
          >
            <Sparkles className="w-3.5 h-3.5 text-white" />
            <span>Ask AI Food Recommender</span>
          </button>
        </div>
      </div>

      {/* Categories Bar */}
      <div className="flex gap-2 overflow-x-auto no-scrollbar pb-1">
        {categories.map((cat) => (
          <button
            key={cat}
            onClick={() => setActiveCategory(cat)}
            className={`press-scale shrink-0 px-3.5 py-1.5 rounded-xl text-xs font-extrabold shadow-xs transition-all border ${
              activeCategory === cat
                ? 'bg-[#355F58] text-white border-[#355F58]'
                : 'bg-white text-[#1F2522] border-[#D9DEDA] hover:border-[#355F58]/40'
            }`}
          >
            {cat}
          </button>
        ))}
      </div>

      {/* Section 1: Must-Try Authentic Regional Dishes */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-black uppercase tracking-wider text-amber-700 flex items-center gap-1.5">
            <Flame className="w-4 h-4" />
            Famous Dishes of {activeDestName}
          </h2>
          <span className="text-xs text-[#5F6863] font-mono">{filteredDishes.length} Items</span>
        </div>

        <div className="grid grid-cols-1 gap-3">
          {filteredDishes.map((dish) => (
            <div
              key={dish.id}
              className="p-3.5 rounded-2xl bg-white border border-[#D9DEDA] hover:border-[#355F58]/40 transition-all flex gap-3.5 shadow-xs group"
            >
              <SafeImage
                src={dish.image}
                alt={dish.name}
                className="w-24 h-24 rounded-xl object-cover shrink-0 border border-[#D9DEDA] group-hover:scale-105 transition-all"
              />

              <div className="flex-1 min-w-0 space-y-1.5">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <div className="flex items-center gap-1.5">
                      <span className={`w-2.5 h-2.5 rounded-full shrink-0 ${dish.isVeg ? 'bg-emerald-600' : 'bg-rose-600'}`} />
                      <h3 className="font-extrabold text-sm text-[#1F2522] truncate">{dish.name}</h3>
                    </div>
                    <span className="text-[10px] font-bold text-amber-700 uppercase tracking-wider">{dish.category}</span>
                  </div>

                  <span className="text-sm font-black font-mono text-[#355F58] shrink-0">{dish.price}</span>
                </div>

                <p className="text-xs text-[#5F6863] line-clamp-2 leading-relaxed">{dish.description}</p>

                <div className="flex items-center justify-between pt-1">
                  <div className="flex items-center gap-1 text-amber-700 font-bold text-xs">
                    <Star className="w-3.5 h-3.5 fill-amber-500 text-amber-500" />
                    <span>{dish.rating}</span>
                  </div>

                  <div className="flex items-center gap-1.5">
                    <button
                      type="button"
                      onClick={() => openAiAssistant(`Tell me where to get authentic ${dish.name} in ${activeDestName}`)}
                      className="px-2.5 py-1 rounded-lg bg-[#F0F2EF] hover:bg-[#E8F0EE] text-[#355F58] text-[11px] font-bold border border-[#D9DEDA] transition-all flex items-center gap-1"
                    >
                      <Sparkles className="w-3 h-3 text-[#355F58]" />
                      <span>Ask AI</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => openCabModal(`Best ${dish.name} Spot in ${activeDestName}`)}
                      className="px-2.5 py-1 rounded-lg bg-[#355F58] hover:bg-[#2C504A] text-white text-[11px] font-black shadow-xs transition-all flex items-center gap-1"
                    >
                      <Car className="w-3 h-3 text-white" />
                      <span>Ride Here</span>
                    </button>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Section 2: Popular Nearby Restaurants */}
      <div className="space-y-3 pt-2">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-black uppercase tracking-wider text-[#355F58] flex items-center gap-1.5">
            <Compass className="w-4 h-4" />
            Top Restaurants Near You
          </h2>
          <span className="text-xs text-[#5F6863] font-mono">Live Places</span>
        </div>

        {isLoadingRestaurants ? (
          <div className="p-8 text-center bg-white rounded-2xl border border-[#D9DEDA] space-y-2">
            <RefreshCw className="w-6 h-6 text-[#355F58] animate-spin mx-auto" />
            <p className="text-xs text-[#5F6863] font-bold">Finding top restaurants in {activeDestName}...</p>
          </div>
        ) : (
          <div className="space-y-3">
            {nearbyRestaurants.slice(0, 6).map((rst, idx) => (
              <div
                key={rst.id || idx}
                className="p-4 rounded-2xl bg-white border border-[#D9DEDA] hover:border-[#355F58]/40 transition-all space-y-2.5 shadow-xs"
              >
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <h3 className="font-extrabold text-sm text-[#1F2522]">{rst.name}</h3>
                    <p className="text-xs text-[#5F6863] flex items-center gap-1 mt-0.5">
                      <MapPin className="w-3.5 h-3.5 text-[#355F58] shrink-0" />
                      <span className="truncate">{rst.location || activeDestName}</span>
                    </p>
                  </div>

                  <div className="text-right shrink-0">
                    <span className="px-2 py-0.5 rounded-md bg-amber-100 text-amber-800 text-xs font-black flex items-center gap-1 border border-amber-200">
                      <Star className="w-3 h-3 fill-amber-500 text-amber-500" />
                      {rst.rating || 4.8}
                    </span>
                    <span className="text-[10px] text-[#355F58] font-mono font-bold block mt-1">{rst.priceRange || '₹₹'}</span>
                  </div>
                </div>

                <div className="flex flex-wrap gap-1.5 text-[10px] text-[#5F6863] font-semibold">
                  {(rst.cuisine || ['Regional Special', 'North Indian']).map((c: string) => (
                    <span key={c} className="px-2 py-0.5 rounded-md bg-[#F0F2EF] border border-[#D9DEDA]">
                      {c}
                    </span>
                  ))}
                </div>

                <div className="flex items-center justify-between pt-1 border-t border-[#D9DEDA]">
                  <button
                    type="button"
                    disabled={!rst.coordinates}
                    onClick={() => {
                      if (rst.coordinates) {
                        openInAppNavigation({
                          title: rst.name,
                          locationName: rst.location || activeDestName,
                          coordinates: rst.coordinates
                        });
                      }
                    }}
                    className="px-3 py-1.5 rounded-xl bg-[#F0F2EF] hover:bg-[#E8F0EE] disabled:opacity-50 disabled:cursor-not-allowed text-[#355F58] text-xs font-bold flex items-center gap-1 border border-[#D9DEDA] transition-all"
                  >
                    <Navigation className="w-3.5 h-3.5 text-[#355F58]" />
                    <span>Navigate</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => openCabModal(rst.name)}
                    className="px-3.5 py-1.5 rounded-xl bg-[#355F58] hover:bg-[#2C504A] text-white font-black text-xs shadow-xs transition-all flex items-center gap-1.5 press-scale"
                  >
                    <Car className="w-3.5 h-3.5 text-white" />
                    <span>Book Ride Here</span>
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
