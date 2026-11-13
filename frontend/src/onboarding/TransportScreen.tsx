import React, { useState } from 'react';
import { useAuth } from '../auth/AuthContext';
import type { TransportPreference } from '../auth/types';
import { PreferenceOption } from '../components/preferences/PreferenceOption';
import { PreferenceProgress } from '../components/preferences/PreferenceProgress';
import { PreferenceFooter } from '../components/preferences/PreferenceFooter';

import { Footprints, Bike, Car, Bus } from 'lucide-react';

interface OptionItem {
  id: TransportPreference;
  label: string;
  subtitle: string;
  icon: React.ReactNode;
}

const TRANSPORTS: OptionItem[] = [
  { id: 'WALK', label: 'Walk', subtitle: 'Explore streets on foot', icon: <Footprints className="w-5 h-5 text-[#355F58]" /> },
  { id: 'BIKE', label: 'Bike / Scooter', subtitle: 'Self-ride two wheelers', icon: <Bike className="w-5 h-5 text-[#355F58]" /> },
  { id: 'AUTO', label: 'Auto Rickshaw', subtitle: 'Quick local rides', icon: <Car className="w-5 h-5 text-[#355F58]" /> },
  { id: 'CAB', label: 'Cab / Taxi', subtitle: 'Comfortable air-con rides', icon: <Car className="w-5 h-5 text-[#355F58]" /> },
  { id: 'PUBLIC_TRANSPORT', label: 'Public Transport', subtitle: 'Buses, trains & metros', icon: <Bus className="w-5 h-5 text-[#355F58]" /> },
];

export const TransportScreen: React.FC = () => {
  const { userPreferences, updateOnboarding, isLoading } = useAuth();
  const [selected, setSelected] = useState<TransportPreference[]>(
    userPreferences?.transportPreferences || []
  );

  const toggleSelect = (id: string) => {
    const transportId = id as TransportPreference;
    setSelected(prev =>
      prev.includes(transportId)
        ? prev.filter(item => item !== transportId)
        : [...prev, transportId]
    );
  };

  const handleContinue = async () => {
    await updateOnboarding({
      transportPreferences: selected,
      onboardingStep: 'food',
      onboardingStatus: 'IN_PROGRESS',
    });
  };

  const handleSkip = async () => {
    await updateOnboarding({
      transportPreferences: [],
      onboardingStep: 'food',
      onboardingStatus: 'IN_PROGRESS',
    });
  };

  return (
    <div className="space-y-6 animate-fadeIn pb-6">
      <PreferenceProgress currentStep={2} totalSteps={5} />

      <div className="space-y-1">
        <h2 className="text-2xl font-bold text-[#1F2522] tracking-tight">
          How do you like getting around?
        </h2>
        <p className="text-sm text-[#5F6863] font-medium">
          Pick your preferred ways to commute during trips.
        </p>
      </div>

      <div className="space-y-3">
        {TRANSPORTS.map(item => (
          <PreferenceOption
            key={item.id}
            id={item.id}
            label={item.label}
            subtitle={item.subtitle}
            icon={item.icon}
            selected={selected.includes(item.id)}
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
