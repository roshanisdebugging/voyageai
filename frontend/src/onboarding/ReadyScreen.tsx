import React from 'react';
import { useAuth } from '../auth/AuthContext';
import { Sparkles, ArrowRight, CheckCircle2 } from 'lucide-react';

export const ReadyScreen: React.FC = () => {
  const { userProfile, updateOnboarding } = useAuth();

  const handleStartExploring = async () => {
    await updateOnboarding({
      onboardingStep: 'ready',
      onboardingStatus: 'COMPLETED',
    });
    window.location.href = '/';
  };

  return (
    <div className="space-y-8 animate-fadeIn text-center py-6">
      <div className="relative w-20 h-20 mx-auto flex items-center justify-center">
        <div className="absolute inset-0 rounded-full bg-[#355F58]/15 blur-xl animate-pulse" />
        <div className="relative w-20 h-20 rounded-3xl bg-[#355F58]/10 border border-[#355F58]/30 flex items-center justify-center text-[#355F58] shadow-lg">
          <Sparkles className="w-10 h-10" />
        </div>
      </div>

      <div className="space-y-3 max-w-xs mx-auto">
        <h2 className="text-3xl font-extrabold text-[#1F2522] tracking-tight">
          You're all set
        </h2>
        <p className="text-sm text-[#5F6863] leading-relaxed font-medium">
          We'll use your preferences to make your trips, food, and ride recommendations feel tailored just for you, {userProfile?.firstName || 'Traveler'}.
        </p>
      </div>

      <div className="bg-white border border-[#D9DEDA] rounded-2xl p-4 text-left max-w-xs mx-auto space-y-2 text-xs text-[#1F2522] shadow-sm">
        <div className="flex items-center gap-2 text-[#355F58] font-extrabold">
          <CheckCircle2 className="w-4 h-4" />
          <span>Travel Personality Active</span>
        </div>
        <p className="text-[#5F6863] leading-normal font-medium">
          You can update your travel styles, food choices, or budget anytime from your Profile.
        </p>
      </div>

      <div className="pt-4">
        <button
          type="button"
          onClick={handleStartExploring}
          className="w-full h-14 bg-[#355F58] hover:bg-[#2A4D47] active:bg-[#1F3B36] text-white font-extrabold text-base rounded-2xl flex items-center justify-center gap-2 shadow-md transition-all select-none touch-manipulation"
        >
          <span>Start Exploring</span>
          <ArrowRight className="w-5 h-5" />
        </button>
      </div>
    </div>
  );
};
