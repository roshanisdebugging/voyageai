import React, { useState } from 'react';
import { useAuth } from '../../auth/AuthContext';
import type {
  TravelStyle,
  TransportPreference,
  DietaryPreference,
  FoodInterest,
  ActivityInterest,
  BudgetLevel
} from '../../auth/types';
import { PreferenceOption } from './PreferenceOption';
import {
  X, Check, Sun, Compass, UtensilsCrossed, Landmark, Trees, Sparkles, Wallet, Moon,
  Footprints, Bike, Car, Bus, Apple, Leaf, Utensils, Coffee, Wine, Fish, Theater
} from 'lucide-react';

interface PreferenceEditModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const PreferenceEditModal: React.FC<PreferenceEditModalProps> = ({
  isOpen,
  onClose,
}) => {
  const { userPreferences, updateOnboarding, isLoading } = useAuth();

  const [activeTab, setActiveTab] = useState<'vibe' | 'transport' | 'food' | 'activities' | 'budget'>('vibe');

  const [styles, setStyles] = useState<TravelStyle[]>(userPreferences?.travelStyles || []);
  const [transports, setTransports] = useState<TransportPreference[]>(userPreferences?.transportPreferences || []);
  const [dietary, setDietary] = useState<DietaryPreference[]>(userPreferences?.dietaryPreferences || ['EVERYTHING']);
  const [foodTypes, setFoodTypes] = useState<FoodInterest[]>(userPreferences?.foodInterests || []);
  const [activities, setActivities] = useState<ActivityInterest[]>(userPreferences?.activityInterests || []);
  
  // Custom numeric budget state (defaults to 30,000 or mapped from budgetLevel)
  const initialBudgetAmount = userPreferences?.budgetLevel === 'BUDGET' ? 15000
    : userPreferences?.budgetLevel === 'PREMIUM' ? 60000
    : userPreferences?.budgetLevel === 'LUXURY' ? 120000
    : 30000;

  const [customBudgetAmount, setCustomBudgetAmount] = useState<number>(initialBudgetAmount);

  if (!isOpen) return null;

  const handleSave = async () => {
    // Map numeric budget to BudgetLevel enum for backend compatibility
    const mappedBudgetLevel: BudgetLevel = customBudgetAmount < 20000 ? 'BUDGET'
      : customBudgetAmount < 45000 ? 'MODERATE'
      : customBudgetAmount < 90000 ? 'PREMIUM'
      : 'LUXURY';

    await updateOnboarding({
      travelStyles: styles,
      transportPreferences: transports,
      dietaryPreferences: dietary,
      foodInterests: foodTypes,
      activityInterests: activities,
      budgetLevel: mappedBudgetLevel,
    });
    onClose();
  };

  const presetBudgetChips = [15000, 30000, 50000, 100000, 150000];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6 pb-[80px] lg:pb-6 bg-[#1F2522]/50 backdrop-blur-xs animate-fadeIn">
      <div className="w-full max-w-lg bg-white border border-[#D9DEDA] rounded-3xl max-h-[calc(100dvh-100px)] lg:max-h-[85vh] flex flex-col shadow-2xl overflow-hidden my-auto text-[#1F2522]">
        
        {/* Header */}
        <div className="flex items-center justify-between p-5 border-b border-[#D9DEDA] shrink-0 bg-white">
          <div>
            <h3 className="text-lg font-black text-[#1F2522]">Edit Travel Preferences</h3>
            <p className="text-xs text-[#5F6863] font-medium">Tune how Cruiser personalizes your trips</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="w-8 h-8 rounded-full bg-[#F0F2EF] flex items-center justify-center text-[#5F6863] hover:text-[#1F2522] transition-all press-scale"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Tab Pills */}
        <div className="flex items-center gap-1.5 p-3 overflow-x-auto no-scrollbar border-b border-[#D9DEDA] bg-[#F0F2EF] shrink-0">
          {[
            { id: 'vibe', label: 'Vibe' },
            { id: 'transport', label: 'Transport' },
            { id: 'food', label: 'Food' },
            { id: 'activities', label: 'Activities' },
            { id: 'budget', label: 'Budget' },
          ].map(tab => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setActiveTab(tab.id as any)}
              className={`
                px-3.5 py-1.5 rounded-full text-xs font-bold whitespace-nowrap transition-all
                ${activeTab === tab.id
                  ? 'bg-[#355F58] text-white shadow-xs font-extrabold'
                  : 'bg-white text-[#5F6863] hover:text-[#1F2522] border border-[#D9DEDA]'
                }
              `}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Body content */}
        <div className="p-5 overflow-y-auto space-y-4 flex-1 bg-[#F6F7F5]">
          {activeTab === 'vibe' && (
            <div className="space-y-3">
              <span className="text-xs font-bold text-[#5F6863] uppercase tracking-wider">Travel Vibe</span>
              <div className="grid grid-cols-2 gap-2.5">
                {[
                  { id: 'RELAXED', label: 'Relaxed', icon: <Sun className="w-5 h-5 text-[#355F58]" /> },
                  { id: 'ADVENTURE', label: 'Adventure', icon: <Compass className="w-5 h-5 text-[#355F58]" /> },
                  { id: 'FOODIE', label: 'Foodie', icon: <UtensilsCrossed className="w-5 h-5 text-[#355F58]" /> },
                  { id: 'CULTURE', label: 'Culture', icon: <Landmark className="w-5 h-5 text-[#355F58]" /> },
                  { id: 'NATURE', label: 'Nature', icon: <Trees className="w-5 h-5 text-[#355F58]" /> },
                  { id: 'LUXURY', label: 'Luxury', icon: <Sparkles className="w-5 h-5 text-[#355F58]" /> },
                  { id: 'BUDGET', label: 'Budget', icon: <Wallet className="w-5 h-5 text-[#355F58]" /> },
                  { id: 'NIGHTLIFE', label: 'Nightlife', icon: <Moon className="w-5 h-5 text-[#355F58]" /> },
                ].map(item => (
                  <PreferenceOption
                    key={item.id}
                    id={item.id}
                    label={item.label}
                    icon={item.icon}
                    selected={styles.includes(item.id as TravelStyle)}
                    onSelect={id => {
                      const val = id as TravelStyle;
                      setStyles(prev => prev.includes(val) ? prev.filter(x => x !== val) : [...prev, val]);
                    }}
                  />
                ))}
              </div>
            </div>
          )}

          {activeTab === 'transport' && (
            <div className="space-y-3">
              <span className="text-xs font-bold text-[#5F6863] uppercase tracking-wider">Getting Around</span>
              <div className="space-y-2.5">
                {[
                  { id: 'WALK', label: 'Walk', icon: <Footprints className="w-5 h-5 text-[#355F58]" /> },
                  { id: 'BIKE', label: 'Bike / Scooter', icon: <Bike className="w-5 h-5 text-[#355F58]" /> },
                  { id: 'AUTO', label: 'Auto Rickshaw', icon: <Car className="w-5 h-5 text-[#355F58]" /> },
                  { id: 'CAB', label: 'Cab / Taxi', icon: <Car className="w-5 h-5 text-[#355F58]" /> },
                  { id: 'PUBLIC_TRANSPORT', label: 'Public Transport', icon: <Bus className="w-5 h-5 text-[#355F58]" /> },
                ].map(item => (
                  <PreferenceOption
                    key={item.id}
                    id={item.id}
                    label={item.label}
                    icon={item.icon}
                    selected={transports.includes(item.id as TransportPreference)}
                    onSelect={id => {
                      const val = id as TransportPreference;
                      setTransports(prev => prev.includes(val) ? prev.filter(x => x !== val) : [...prev, val]);
                    }}
                  />
                ))}
              </div>
            </div>
          )}

          {activeTab === 'food' && (
            <div className="space-y-4">
              <div className="space-y-2.5">
                <span className="text-xs font-bold text-[#5F6863] uppercase tracking-wider">Primary Diet</span>
                <div className="grid grid-cols-2 gap-2">
                  {[
                    { id: 'EVERYTHING', label: 'Everything', icon: <UtensilsCrossed className="w-5 h-5 text-[#355F58]" /> },
                    { id: 'VEGETARIAN', label: 'Vegetarian', icon: <Apple className="w-5 h-5 text-[#355F58]" /> },
                    { id: 'VEGAN', label: 'Vegan', icon: <Leaf className="w-5 h-5 text-[#355F58]" /> },
                    { id: 'HALAL', label: 'Halal', icon: <Utensils className="w-5 h-5 text-[#355F58]" /> },
                  ].map(item => (
                    <PreferenceOption
                      key={item.id}
                      id={item.id}
                      label={item.label}
                      icon={item.icon}
                      selected={dietary.includes(item.id as DietaryPreference)}
                      onSelect={id => {
                        const val = id as DietaryPreference;
                        setDietary(prev => prev.includes(val) ? prev.filter(x => x !== val) : [...prev, val]);
                      }}
                    />
                  ))}
                </div>
              </div>

              <div className="space-y-2.5 pt-2">
                <span className="text-xs font-bold text-[#5F6863] uppercase tracking-wider">Food Interests</span>
                <div className="grid grid-cols-2 gap-2">
                  {[
                    { id: 'LOCAL', label: 'Local Food', icon: <Utensils className="w-5 h-5 text-[#355F58]" /> },
                    { id: 'STREET_FOOD', label: 'Street Food', icon: <Coffee className="w-5 h-5 text-[#355F58]" /> },
                    { id: 'FINE_DINING', label: 'Fine Dining', icon: <Wine className="w-5 h-5 text-[#355F58]" /> },
                    { id: 'SEAFOOD', label: 'Seafood', icon: <Fish className="w-5 h-5 text-[#355F58]" /> },
                  ].map(item => (
                    <PreferenceOption
                      key={item.id}
                      id={item.id}
                      label={item.label}
                      icon={item.icon}
                      selected={foodTypes.includes(item.id as FoodInterest)}
                      onSelect={id => {
                        const val = id as FoodInterest;
                        setFoodTypes(prev => prev.includes(val) ? prev.filter(x => x !== val) : [...prev, val]);
                      }}
                    />
                  ))}
                </div>
              </div>
            </div>
          )}

          {activeTab === 'activities' && (
            <div className="space-y-3">
              <span className="text-xs font-bold text-[#5F6863] uppercase tracking-wider">Activities</span>
              <div className="grid grid-cols-2 gap-2.5">
                {[
                  { id: 'BEACHES', label: 'Beaches', icon: <Sun className="w-5 h-5 text-[#355F58]" /> },
                  { id: 'NATURE', label: 'Nature', icon: <Trees className="w-5 h-5 text-[#355F58]" /> },
                  { id: 'HISTORY', label: 'History', icon: <Landmark className="w-5 h-5 text-[#355F58]" /> },
                  { id: 'CULTURE', label: 'Culture', icon: <Theater className="w-5 h-5 text-[#355F58]" /> },
                  { id: 'ADVENTURE', label: 'Adventure', icon: <Compass className="w-5 h-5 text-[#355F58]" /> },
                  { id: 'NIGHTLIFE', label: 'Nightlife', icon: <Moon className="w-5 h-5 text-[#355F58]" /> },
                ].map(item => (
                  <PreferenceOption
                    key={item.id}
                    id={item.id}
                    label={item.label}
                    icon={item.icon}
                    selected={activities.includes(item.id as ActivityInterest)}
                    onSelect={id => {
                      const val = id as ActivityInterest;
                      setActivities(prev => prev.includes(val) ? prev.filter(x => x !== val) : [...prev, val]);
                    }}
                  />
                ))}
              </div>
            </div>
          )}

          {/* CUSTOM BUDGET SECTION (NO PREDEFINED TIERS - SLIDER & NUMERIC INPUT) */}
          {activeTab === 'budget' && (
            <div className="space-y-5">
              <div>
                <span className="text-xs font-extrabold text-[#5F6863] uppercase tracking-wider">Custom Trip Budget</span>
                <p className="text-xs text-[#5F6863] mt-0.5 font-medium">Enter your exact target budget or adjust using the slider below.</p>
              </div>

              {/* Custom Numeric Entry Box */}
              <div className="p-4 rounded-2xl bg-white border border-[#D9DEDA] space-y-3 shadow-xs">
                <label className="text-xs font-bold text-[#5F6863]">Target Budget Amount (₹)</label>
                <div className="relative flex items-center">
                  <span className="absolute left-3.5 font-extrabold text-[#355F58] text-lg font-mono">₹</span>
                  <input
                    type="number"
                    min={5000}
                    max={500000}
                    step={1000}
                    value={customBudgetAmount}
                    onChange={(e) => setCustomBudgetAmount(Math.max(0, Number(e.target.value)))}
                    className="w-full bg-[#F0F2EF] border border-[#D9DEDA] focus:border-[#355F58] rounded-2xl pl-8 pr-4 py-3.5 text-xl font-extrabold font-mono text-[#1F2522] outline-none"
                    placeholder="Enter amount (e.g. 25000)"
                  />
                </div>

                {/* Range Slider */}
                <div className="space-y-2 pt-2">
                  <div className="flex items-center justify-between text-xs text-[#5F6863] font-bold">
                    <span>₹5,000</span>
                    <span className="text-[#355F58] font-extrabold font-mono">₹{customBudgetAmount.toLocaleString()}</span>
                    <span>₹2,00,000</span>
                  </div>
                  <input
                    type="range"
                    min={5000}
                    max={200000}
                    step={1000}
                    value={Math.min(200000, Math.max(5000, customBudgetAmount))}
                    onChange={(e) => setCustomBudgetAmount(Number(e.target.value))}
                    className="w-full h-2.5 bg-[#D9DEDA] rounded-lg appearance-none cursor-pointer accent-[#355F58]"
                  />
                </div>
              </div>

              {/* Quick Budget Shortcuts */}
              <div className="space-y-2">
                <span className="text-xs font-bold text-[#5F6863] uppercase tracking-wider">Quick Preset Amounts</span>
                <div className="flex flex-wrap gap-2">
                  {presetBudgetChips.map((amt) => (
                    <button
                      key={amt}
                      type="button"
                      onClick={() => setCustomBudgetAmount(amt)}
                      className={`px-3.5 py-2 rounded-xl text-xs font-bold border transition-all ${
                        customBudgetAmount === amt
                          ? 'bg-[#355F58] text-white border-[#355F58] shadow-xs'
                          : 'bg-white text-[#1F2522] border-[#D9DEDA] hover:bg-[#F0F2EF]'
                      }`}
                    >
                      ₹{amt.toLocaleString()}
                    </button>
                  ))}
                </div>
              </div>

              {/* Budget Breakdown Indicator */}
              <div className="p-3.5 rounded-2xl bg-[#E8F0EE] border border-[#D9DEDA] flex items-center justify-between text-xs">
                <span className="font-bold text-[#355F58]">Estimated Daily Spend (4 Days):</span>
                <span className="font-extrabold font-mono text-[#1F2522] text-sm">
                  ₹{Math.round(customBudgetAmount / 4).toLocaleString()} / day
                </span>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-[#D9DEDA] bg-white shrink-0">
          <button
            type="button"
            onClick={handleSave}
            disabled={isLoading}
            className="w-full h-12 bg-[#355F58] hover:bg-[#2C504A] text-white font-extrabold text-sm rounded-2xl flex items-center justify-center gap-2 shadow-xs transition-all press-scale"
          >
            <Check className="w-4 h-4 text-white" />
            <span>Save Preferences</span>
          </button>
        </div>

      </div>
    </div>
  );
};
