import React, { useState } from 'react';
import { useAuth } from '../auth/AuthContext';
import type { ActivityInterest } from '../auth/types';
import { PreferenceOption } from '../components/preferences/PreferenceOption';
import { PreferenceProgress } from '../components/preferences/PreferenceProgress';
import { PreferenceFooter } from '../components/preferences/PreferenceFooter';

import { Sun, Trees, Landmark, Theater, Compass, ShoppingBag, Moon, Camera, Heart, UtensilsCrossed } from 'lucide-react';

interface OptionItem {
  id: ActivityInterest;
  label: string;
  subtitle: string;
  icon: React.ReactNode;
}

const ACTIVITIES: OptionItem[] = [
  { id: 'BEACHES', label: 'Beaches', subtitle: 'Sand, sea, ocean sunsets', icon: <Sun className="w-5 h-5 text-[#355F58]" /> },
  { id: 'NATURE', label: 'Nature & Parks', subtitle: 'Hikes, waterfalls, greenery', icon: <Trees className="w-5 h-5 text-[#355F58]" /> },
  { id: 'HISTORY', label: 'History & Forts', subtitle: 'Heritage monuments & ruins', icon: <Landmark className="w-5 h-5 text-[#355F58]" /> },
  { id: 'CULTURE', label: 'Culture & Arts', subtitle: 'Temples, museums, local crafts', icon: <Theater className="w-5 h-5 text-[#355F58]" /> },
  { id: 'ADVENTURE', label: 'Adventure Sports', subtitle: 'Trekking, rafting, water sports', icon: <Compass className="w-5 h-5 text-[#355F58]" /> },
  { id: 'SHOPPING', label: 'Local Shopping', subtitle: 'Bazaars, flea markets, souvenirs', icon: <ShoppingBag className="w-5 h-5 text-[#355F58]" /> },
  { id: 'NIGHTLIFE', label: 'Nightlife & Parties', subtitle: 'Beach shacks, clubs, live music', icon: <Moon className="w-5 h-5 text-[#355F58]" /> },
  { id: 'PHOTOGRAPHY', label: 'Photography', subtitle: 'Scenic spots & viewpoints', icon: <Camera className="w-5 h-5 text-[#355F58]" /> },
  { id: 'WELLNESS', label: 'Wellness & Spa', subtitle: 'Yoga, relaxation, massageries', icon: <Heart className="w-5 h-5 text-[#355F58]" /> },
  { id: 'FOOD', label: 'Culinary Experiences', subtitle: 'Food walks & tasting tours', icon: <UtensilsCrossed className="w-5 h-5 text-[#355F58]" /> },
];

export const ActivitiesScreen: React.FC = () => {
  const { userPreferences, updateOnboarding, isLoading } = useAuth();
  const [selected, setSelected] = useState<ActivityInterest[]>(
    userPreferences?.activityInterests || []
  );

  const toggleSelect = (id: string) => {
    const actId = id as ActivityInterest;
    setSelected(prev => {
      if (prev.includes(actId)) {
        return prev.filter(item => item !== actId);
      }
      if (prev.length >= 5) {
        // Soft recommendation max of 5 favorites
        return [...prev.slice(1), actId];
      }
      return [...prev, actId];
    });
  };

  const handleContinue = async () => {
    await updateOnboarding({
      activityInterests: selected,
      onboardingStep: 'budget',
      onboardingStatus: 'IN_PROGRESS',
    });
  };

  const handleSkip = async () => {
    await updateOnboarding({
      activityInterests: [],
      onboardingStep: 'budget',
      onboardingStatus: 'IN_PROGRESS',
    });
  };

  return (
    <div className="space-y-6 animate-fadeIn pb-6">
      <PreferenceProgress currentStep={4} totalSteps={5} />

      <div className="space-y-1">
        <h2 className="text-2xl font-bold text-[#1F2522] tracking-tight">
          What activities excite you?
        </h2>
        <p className="text-sm text-[#5F6863] font-medium">
          Pick your top choices for things to do.
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {ACTIVITIES.map(act => (
          <PreferenceOption
            key={act.id}
            id={act.id}
            label={act.label}
            subtitle={act.subtitle}
            icon={act.icon}
            selected={selected.includes(act.id)}
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
