import React, { useState } from 'react';
import { useAuth } from '../auth/AuthContext';
import type { TravelStyle } from '../auth/types';
import { PreferenceOption } from '../components/preferences/PreferenceOption';
import { PreferenceProgress } from '../components/preferences/PreferenceProgress';
import { PreferenceFooter } from '../components/preferences/PreferenceFooter';

import { Sun, Compass, UtensilsCrossed, Landmark, Trees, Sparkles, Wallet, Moon } from 'lucide-react';

interface OptionItem {
  id: TravelStyle;
  label: string;
  subtitle: string;
  icon: React.ReactNode;
}

const TRAVEL_STYLES: OptionItem[] = [
  { id: 'RELAXED', label: 'Relaxed', subtitle: 'Unwind, beaches, slow pace', icon: <Sun className="w-5 h-5 text-[#355F58]" /> },
  { id: 'ADVENTURE', label: 'Adventure', subtitle: 'Hiking, sports, thrill-seeking', icon: <Compass className="w-5 h-5 text-[#355F58]" /> },
  { id: 'FOODIE', label: 'Foodie', subtitle: 'Street food, fine dining, cafes', icon: <UtensilsCrossed className="w-5 h-5 text-[#355F58]" /> },
  { id: 'CULTURE', label: 'Culture', subtitle: 'History, museums, traditions', icon: <Landmark className="w-5 h-5 text-[#355F58]" /> },
  { id: 'NATURE', label: 'Nature', subtitle: 'Wildlife, mountains, scenic views', icon: <Trees className="w-5 h-5 text-[#355F58]" /> },
  { id: 'LUXURY', label: 'Luxury', subtitle: 'Resorts, spas, premium comfort', icon: <Sparkles className="w-5 h-5 text-[#355F58]" /> },
  { id: 'BUDGET', label: 'Budget', subtitle: 'Smart spends, hostels, local routes', icon: <Wallet className="w-5 h-5 text-[#355F58]" /> },
  { id: 'NIGHTLIFE', label: 'Nightlife', subtitle: 'Clubs, lounge bars, evening vibe', icon: <Moon className="w-5 h-5 text-[#355F58]" /> },
];

export const TravelStyleScreen: React.FC = () => {
  const { userPreferences, updateOnboarding, isLoading } = useAuth();
  const [selected, setSelected] = useState<TravelStyle[]>(
    userPreferences?.travelStyles || []
  );

  const toggleSelect = (id: string) => {
    const styleId = id as TravelStyle;
    setSelected(prev => {
      if (prev.includes(styleId)) {
        return prev.filter(item => item !== styleId);
      }
      if (prev.length >= 3) {
        // Max 3 recommendation preferred
        return [...prev.slice(1), styleId];
      }
      return [...prev, styleId];
    });
  };

  const handleContinue = async () => {
    await updateOnboarding({
      travelStyles: selected,
      onboardingStep: 'transport',
      onboardingStatus: 'IN_PROGRESS',
    });
  };

  const handleSkip = async () => {
    await updateOnboarding({
      travelStyles: [],
      onboardingStep: 'transport',
      onboardingStatus: 'IN_PROGRESS',
    });
  };

  return (
    <div className="space-y-6 animate-fadeIn pb-6">
      <PreferenceProgress currentStep={1} totalSteps={5} />

      <div className="space-y-1">
        <h2 className="text-2xl font-bold text-[#1F2522] tracking-tight">
          What's your travel vibe?
        </h2>
        <p className="text-sm text-[#5F6863] font-medium">
          Pick up to 3 that sound most like you.
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {TRAVEL_STYLES.map(style => (
          <PreferenceOption
            key={style.id}
            id={style.id}
            label={style.label}
            subtitle={style.subtitle}
            icon={style.icon}
            selected={selected.includes(style.id)}
            onSelect={toggleSelect}
            mode="multiple"
          />
        ))}
      </div>

      <PreferenceFooter
        onContinue={handleContinue}
        onSkip={handleSkip}
        isLoading={isLoading}
      />
    </div>
  );
};
