import React, { useState } from 'react';
import { useAuth } from '../auth/AuthContext';
import { User, ArrowRight } from 'lucide-react';

interface BasicProfileProps {
  onNext: () => void;
}

export const BasicProfileScreen: React.FC<BasicProfileProps> = ({ onNext }) => {
  const { userProfile, updateOnboarding } = useAuth();
  const [firstName, setFirstName] = useState(userProfile?.firstName || 'Roshan');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!firstName.trim()) return;
    await updateOnboarding({ firstName: firstName.trim() });
    onNext();
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-6 text-center animate-fadeIn">
      <div className="w-14 h-14 rounded-2xl bg-[#355F58]/10 text-[#355F58] border border-[#355F58]/20 flex items-center justify-center mx-auto shadow-sm">
        <User className="w-7 h-7" />
      </div>

      <div className="space-y-1">
        <h2 className="text-2xl font-extrabold text-[#1F2522]">How should we call you?</h2>
        <p className="text-xs text-[#5F6863] font-medium">We auto-filled this from your login account.</p>
      </div>

      <div className="pt-2 max-w-xs mx-auto">
        <input
          type="text"
          value={firstName}
          onChange={e => setFirstName(e.target.value)}
          placeholder="First Name"
          className="w-full bg-white border border-[#D9DEDA] focus:border-[#355F58] rounded-2xl text-center font-extrabold text-lg text-[#1F2522] py-3.5 outline-none shadow-sm transition-all"
          required
        />
      </div>

      <button
        type="submit"
        disabled={!firstName.trim()}
        className="w-full h-14 bg-[#355F58] hover:bg-[#2A4D47] text-white font-extrabold text-base rounded-2xl flex items-center justify-center gap-2 shadow-md transition-all select-none touch-manipulation press-scale disabled:opacity-40"
      >
        <span>Continue</span>
        <ArrowRight className="w-5 h-5" />
      </button>
    </form>
  );
};
