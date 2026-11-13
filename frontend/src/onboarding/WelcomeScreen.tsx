import React from 'react';
import { useAuth } from '../auth/AuthContext';
import { Sparkles, ArrowRight } from 'lucide-react';

interface WelcomeScreenProps {
  onNext: () => void;
  onSkip: () => void;
}

export const WelcomeScreen: React.FC<WelcomeScreenProps> = ({ onNext, onSkip }) => {
  const { userProfile } = useAuth();
  const name = userProfile?.firstName || 'Traveler';

  return (
    <div className="space-y-6 text-center animate-fadeIn">
      {/* Personal Avatar / Icon */}
      <div className="relative w-24 h-24 mx-auto">
        <img
          src={userProfile?.avatarUrl || 'https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?auto=format&fit=crop&w=400&q=80'}
          alt={name}
          className="w-full h-full rounded-full object-cover border-4 border-[#355F58]/20 shadow-lg"
        />
        <div className="absolute bottom-0 right-0 p-2 rounded-full bg-[#355F58] text-white shadow-md">
          <Sparkles className="w-4 h-4" />
        </div>
      </div>

      <div className="space-y-2">
        <h2 className="text-3xl font-extrabold text-[#1F2522]">
          Welcome, {name}
        </h2>
        <p className="text-sm text-[#5F6863] max-w-xs mx-auto font-medium">
          Let's make Cruiser work better for you in 30 seconds.
        </p>
      </div>

      {/* Action Buttons */}
      <div className="space-y-3 pt-4">
        <button
          onClick={onNext}
          className="w-full h-14 bg-[#355F58] hover:bg-[#2A4D47] text-white font-extrabold text-base rounded-2xl flex items-center justify-center gap-2 shadow-md transition-all select-none touch-manipulation press-scale"
        >
          <span>Let's personalize</span>
          <ArrowRight className="w-5 h-5" />
        </button>

        <button
          onClick={onSkip}
          className="text-xs font-semibold text-[#5F6863] hover:text-[#1F2522] transition-colors"
        >
          Skip for now
        </button>
      </div>
    </div>
  );
};
