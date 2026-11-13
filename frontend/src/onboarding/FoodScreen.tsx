import React, { useState } from 'react';
import { useAuth } from '../auth/AuthContext';
import type { DietaryPreference, FoodInterest } from '../auth/types';
import { PreferenceOption } from '../components/preferences/PreferenceOption';
import { PreferenceProgress } from '../components/preferences/PreferenceProgress';
import { PreferenceFooter } from '../components/preferences/PreferenceFooter';

import { UtensilsCrossed, Apple, Leaf, Utensils, Wheat, Coffee, Wine, Cake, Fish } from 'lucide-react';

interface DietItem {
  id: DietaryPreference;
  label: string;
  icon: React.ReactNode;
}

interface FoodTypeItem {
  id: FoodInterest;
  label: string;
  icon: React.ReactNode;
}

const DIETARY_OPTIONS: DietItem[] = [
  { id: 'EVERYTHING', label: 'Everything', icon: <UtensilsCrossed className="w-5 h-5 text-[#355F58]" /> },
  { id: 'VEGETARIAN', label: 'Vegetarian', icon: <Apple className="w-5 h-5 text-[#355F58]" /> },
  { id: 'VEGAN', label: 'Vegan', icon: <Leaf className="w-5 h-5 text-[#355F58]" /> },
  { id: 'JAIN', label: 'Jain', icon: <Leaf className="w-5 h-5 text-[#355F58]" /> },
  { id: 'HALAL', label: 'Halal', icon: <Utensils className="w-5 h-5 text-[#355F58]" /> },
  { id: 'GLUTEN_FREE', label: 'Gluten Free', icon: <Wheat className="w-5 h-5 text-[#355F58]" /> },
  { id: 'OTHER', label: 'Other', icon: <Utensils className="w-5 h-5 text-[#355F58]" /> },
];

const FOOD_INTERESTS: FoodTypeItem[] = [
  { id: 'LOCAL', label: 'Local Food', icon: <Utensils className="w-5 h-5 text-[#355F58]" /> },
  { id: 'STREET_FOOD', label: 'Street Food', icon: <UtensilsCrossed className="w-5 h-5 text-[#355F58]" /> },
  { id: 'CAFE', label: 'Cafes & Bakery', icon: <Coffee className="w-5 h-5 text-[#355F58]" /> },
  { id: 'FINE_DINING', label: 'Fine Dining', icon: <Wine className="w-5 h-5 text-[#355F58]" /> },
  { id: 'FAST_FOOD', label: 'Fast Food', icon: <Utensils className="w-5 h-5 text-[#355F58]" /> },
  { id: 'DESSERTS', label: 'Desserts', icon: <Cake className="w-5 h-5 text-[#355F58]" /> },
  { id: 'SEAFOOD', label: 'Seafood', icon: <Fish className="w-5 h-5 text-[#355F58]" /> },
];

export const FoodScreen: React.FC = () => {
  const { userPreferences, updateOnboarding, isLoading } = useAuth();

  const [dietary, setDietary] = useState<DietaryPreference[]>(
    userPreferences?.dietaryPreferences?.length ? userPreferences.dietaryPreferences : ['EVERYTHING']
  );
  const [interests, setInterests] = useState<FoodInterest[]>(
    userPreferences?.foodInterests || []
  );

  const toggleDietary = (id: string) => {
    const dietId = id as DietaryPreference;
    setDietary(prev => {
      if (dietId === 'EVERYTHING') return ['EVERYTHING'];
      const filtered = prev.filter(d => d !== 'EVERYTHING');
      if (filtered.includes(dietId)) {
        const next = filtered.filter(d => d !== dietId);
        return next.length ? next : ['EVERYTHING'];
      }
      return [...filtered, dietId];
    });
  };

  const toggleInterest = (id: string) => {
    const foodId = id as FoodInterest;
    setInterests(prev =>
      prev.includes(foodId)
        ? prev.filter(item => item !== foodId)
        : [...prev, foodId]
    );
  };

  const handleContinue = async () => {
    await updateOnboarding({
      dietaryPreferences: dietary,
      foodInterests: interests,
      onboardingStep: 'activities',
      onboardingStatus: 'IN_PROGRESS',
    });
  };

  const handleSkip = async () => {
    await updateOnboarding({
      dietaryPreferences: ['EVERYTHING'],
      foodInterests: [],
      onboardingStep: 'activities',
      onboardingStatus: 'IN_PROGRESS',
    });
  };

  return (
    <div className="space-y-6 animate-fadeIn pb-6">
      <PreferenceProgress currentStep={3} totalSteps={5} />

      <div className="space-y-1">
        <h2 className="text-2xl font-bold text-[#1F2522] tracking-tight">
          What should we keep in mind for food?
        </h2>
        <p className="text-sm text-[#5F6863] font-medium">
          Select dietary needs & types of food you enjoy.
        </p>
      </div>

      {/* Dietary Section */}
      <div className="space-y-3">
        <span className="text-xs font-bold uppercase tracking-wider text-[#5F6863]">
          Primary Diet
        </span>
        <div className="grid grid-cols-2 gap-2.5">
          {DIETARY_OPTIONS.map(diet => (
            <PreferenceOption
              key={diet.id}
              id={diet.id}
              label={diet.label}
              icon={diet.icon}
              selected={dietary.includes(diet.id)}
              onSelect={toggleDietary}
              mode="multiple"
            />
          ))}
        </div>
      </div>

      {/* Food Interests */}
      <div className="space-y-3 pt-2">
        <span className="text-xs font-bold uppercase tracking-wider text-[#5F6863]">
          Food Types You Love (Optional)
        </span>
        <div className="grid grid-cols-2 gap-2.5">
          {FOOD_INTERESTS.map(food => (
            <PreferenceOption
              key={food.id}
              id={food.id}
              label={food.label}
              icon={food.icon}
              selected={interests.includes(food.id)}
              onSelect={toggleInterest}
              mode="multiple"
            />
          ))}
        </div>
      </div>

      <PreferenceFooter
        onContinue={handleContinue}
        onSkip={handleSkip}
        isLoading={isLoading}
      />
    </div>
  );
};
