import React, { useState } from 'react';
import { useAuth } from '../auth/AuthContext';
import type { BudgetLevel } from '../auth/types';
import { PreferenceProgress } from '../components/preferences/PreferenceProgress';
import { PreferenceFooter } from '../components/preferences/PreferenceFooter';

export const BudgetScreen: React.FC = () => {
  const { userPreferences, updateOnboarding, isLoading } = useAuth();
  const initialBudget = userPreferences?.budgetLevel === 'BUDGET' ? 15000
    : userPreferences?.budgetLevel === 'PREMIUM' ? 60000
    : userPreferences?.budgetLevel === 'LUXURY' ? 120000
    : 30000;

  const [customBudget, setCustomBudget] = useState<number>(initialBudget);

  const presetBudgetChips = [15000, 30000, 50000, 100000, 150000];

  const handleContinue = async () => {
    const mappedBudgetLevel: BudgetLevel = customBudget < 20000 ? 'BUDGET'
      : customBudget < 45000 ? 'MODERATE'
      : customBudget < 90000 ? 'PREMIUM'
      : 'LUXURY';

    await updateOnboarding({
      budgetLevel: mappedBudgetLevel,
      onboardingStep: 'ready',
      onboardingStatus: 'COMPLETED',
    });
  };

  const handleSkip = async () => {
    await updateOnboarding({
      onboardingStep: 'ready',
      onboardingStatus: 'COMPLETED',
    });
  };

  return (
    <div className="space-y-6 animate-fadeIn pb-6 text-[#1F2522]">
      <PreferenceProgress currentStep={5} totalSteps={5} />

      <div className="space-y-1">
        <h2 className="text-2xl font-extrabold text-[#1F2522] tracking-tight">
          What is your travel budget?
        </h2>
        <p className="text-sm text-[#5F6863] font-medium">
          Set your custom budget amount or adjust using the range slider.
        </p>
      </div>

      <div className="space-y-5 bg-white border border-[#D9DEDA] p-5 rounded-3xl text-[#1F2522] shadow-xl">
        <div className="space-y-2">
          <label className="text-xs font-bold text-[#1F2522]">Target Budget Amount (₹)</label>
          <div className="relative flex items-center">
            <span className="absolute left-3.5 font-extrabold text-[#355F58] text-lg font-mono">₹</span>
            <input
              type="number"
              min={5000}
              max={500000}
              step={1000}
              value={customBudget}
              onChange={(e) => setCustomBudget(Math.max(0, Number(e.target.value)))}
              className="w-full bg-[#F6F7F5] border border-[#D9DEDA] focus:border-[#355F58] focus:bg-white rounded-2xl pl-8 pr-4 py-3 text-lg font-extrabold font-mono text-[#1F2522] outline-none transition-all"
              placeholder="Enter amount (e.g. 30000)"
            />
          </div>
        </div>

        {/* Range Slider */}
        <div className="space-y-2 pt-1">
          <div className="flex items-center justify-between text-xs text-[#5F6863] font-bold">
            <span>₹5,000</span>
            <span className="text-[#355F58] font-extrabold font-mono text-sm">₹{customBudget.toLocaleString()}</span>
            <span>₹2,00,000</span>
          </div>
          <input
            type="range"
            min={5000}
            max={200000}
            step={1000}
            value={Math.min(200000, Math.max(5000, customBudget))}
            onChange={(e) => setCustomBudget(Number(e.target.value))}
            className="w-full h-2.5 bg-[#F0F2EF] rounded-lg appearance-none cursor-pointer accent-[#355F58]"
          />
        </div>

        {/* Presets */}
        <div className="space-y-2 pt-1">
          <span className="text-xs font-bold text-[#5F6863] uppercase tracking-wider">Quick Presets</span>
          <div className="flex flex-wrap gap-2">
            {presetBudgetChips.map((amt) => (
              <button
                key={amt}
                type="button"
                onClick={() => setCustomBudget(amt)}
                className={`px-3.5 py-1.5 rounded-xl text-xs font-bold border transition-all ${
                  customBudget === amt
                    ? 'bg-[#355F58] text-white border-[#355F58] shadow-md font-extrabold'
                    : 'bg-[#F0F2EF] text-[#1F2522] border-[#D9DEDA] hover:bg-[#E8F0EE]'
                }`}
              >
                ₹{amt.toLocaleString()}
              </button>
            ))}
          </div>
        </div>
      </div>

      <PreferenceFooter
        onContinue={handleContinue}
        onSkip={handleSkip}
        continueText="Finish Setup"
        isLoading={isLoading}
      />
    </div>
  );
};
