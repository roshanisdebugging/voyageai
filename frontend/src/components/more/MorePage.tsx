import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../auth/AuthContext';
import { useApp } from '../../context/AppContext';
import { useTheme } from '../../context/ThemeContext';
import { PreferenceEditModal } from '../preferences/PreferenceEditModal';
import { Heart, ShieldAlert, SlidersHorizontal, LogOut, ChevronRight, HelpCircle, PhoneCall, Sparkles } from 'lucide-react';

export const MorePage: React.FC = () => {
  const navigate = useNavigate();
  const { userProfile, userPreferences, authUser, signOut } = useAuth();
  const { setIsEmergencyOpen, openAiAssistant } = useApp();
  const { theme, setTheme } = useTheme();

  const [isEditPrefsOpen, setIsEditPrefsOpen] = useState(false);
  const [showSignOutConfirm, setShowSignOutConfirm] = useState(false);

  const name = userProfile ? `${userProfile.firstName} ${userProfile.lastName || ''}`.trim() : 'Traveler';
  const email = authUser?.email || 'Registered User';
  const avatarUrl = userProfile?.avatarUrl || 'https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?auto=format&fit=crop&w=400&q=80';

  const handleLogout = async () => {
    await signOut();
    navigate('/login');
  };

  return (
    <div className="space-y-6 pb-28 max-w-xl mx-auto animate-fadeIn">
      {/* Edit Preferences Modal */}
      <PreferenceEditModal
        isOpen={isEditPrefsOpen}
        onClose={() => setIsEditPrefsOpen(false)}
      />

      {/* Page Heading */}
      <div className="space-y-1 pt-1">
        <h1 className="text-2xl sm:text-3xl font-extrabold text-[#1F2522] dark:text-zinc-100">More Options & Profile</h1>
        <p className="text-sm text-[#5F6863] dark:text-zinc-400">Account settings, saved places, and support</p>
      </div>

      {/* User Profile Banner Card */}
      <div className="bg-white dark:bg-zinc-900 p-5 flex items-center justify-between gap-4 rounded-3xl border border-[#D9DEDA] dark:border-zinc-800 shadow-xs transition-colors">
        <div className="flex items-center gap-4 min-w-0">
          <img
            src={avatarUrl}
            alt={name}
            className="w-16 h-16 rounded-full object-cover border-2 border-[#355F58]/40 dark:border-emerald-500/40 shrink-0 bg-[#D9DEDA] dark:bg-zinc-800"
            loading="lazy"
            decoding="async"
          />
          <div className="min-w-0">
            <h2 className="text-lg sm:text-xl font-extrabold text-[#1F2522] dark:text-zinc-100 truncate">{name}</h2>
            <p className="text-xs text-[#5F6863] dark:text-zinc-400 truncate font-medium">{email}</p>
            <span className="inline-block mt-1 px-2.5 py-0.5 rounded-full bg-[#E8F0EE] dark:bg-emerald-950/60 text-[#355F58] dark:text-emerald-400 font-bold text-[10px] uppercase border border-[#D9DEDA] dark:border-emerald-800/50">
              Verified User
            </span>
          </div>
        </div>

        <button
          type="button"
          onClick={() => setIsEditPrefsOpen(true)}
          className="px-3.5 py-2.5 rounded-2xl bg-[#F0F2EF] dark:bg-zinc-800 hover:border-[#355F58]/40 dark:hover:border-zinc-600 text-[#355F58] dark:text-zinc-200 font-bold text-xs border border-[#D9DEDA] dark:border-zinc-700 flex items-center gap-1 shrink-0 transition-colors"
        >
          <SlidersHorizontal className="w-4 h-4 text-[#355F58] dark:text-emerald-400" />
          <span>Edit</span>
        </button>
      </div>

      {/* Grouped Elderly Menu Actions */}
      <div className="space-y-3">
        <span className="text-xs font-bold text-[#5F6863] dark:text-zinc-400 uppercase tracking-wider block">
          Menu & Settings
        </span>

        <div className="space-y-2.5">
          {/* Action 1: Travel Preferences */}
          <button
            type="button"
            onClick={() => setIsEditPrefsOpen(true)}
            className="w-full p-4 rounded-2xl bg-white dark:bg-zinc-900 border border-[#D9DEDA] dark:border-zinc-800 hover:border-[#355F58]/40 dark:hover:border-zinc-700 text-left flex items-center justify-between transition-all press-scale shadow-xs min-h-[60px]"
          >
            <div className="flex items-center gap-3.5">
              <div className="w-11 h-11 rounded-xl bg-[#E8F0EE] dark:bg-zinc-800 text-[#355F58] dark:text-emerald-400 border border-[#D9DEDA] dark:border-zinc-700 flex items-center justify-center shrink-0">
                <SlidersHorizontal className="w-6 h-6" />
              </div>
              <div>
                <h3 className="text-base font-bold text-[#1F2522] dark:text-zinc-100">Travel Preferences</h3>
                <p className="text-xs text-[#5F6863] dark:text-zinc-400 font-medium">
                  {userPreferences?.travelStyles?.slice(0, 2).join(', ') || 'Relaxed, Foodie'} · {userPreferences?.budgetLevel || 'Moderate'}
                </p>
              </div>
            </div>
            <ChevronRight className="w-5 h-5 text-[#7C8580] dark:text-zinc-500" />
          </button>

          {/* Action 2: Saved Places */}
          <button
            type="button"
            onClick={() => navigate('/saved-places')}
            className="w-full p-4 rounded-2xl bg-white dark:bg-zinc-900 border border-[#D9DEDA] dark:border-zinc-800 hover:border-[#355F58]/40 dark:hover:border-zinc-700 text-left flex items-center justify-between transition-all press-scale shadow-xs min-h-[60px]"
          >
            <div className="flex items-center gap-3.5">
              <div className="w-11 h-11 rounded-xl bg-rose-50 dark:bg-rose-950/40 text-rose-600 dark:text-rose-400 border border-rose-200 dark:border-rose-900/40 flex items-center justify-center shrink-0">
                <Heart className="w-6 h-6" />
              </div>
              <div>
                <h3 className="text-base font-bold text-[#1F2522] dark:text-zinc-100">Saved Places & Favorites</h3>
                <p className="text-xs text-[#5F6863] dark:text-zinc-400 font-medium">View bookmarked hotels, restaurants, & POIs</p>
              </div>
            </div>
            <ChevronRight className="w-5 h-5 text-[#7C8580] dark:text-zinc-500" />
          </button>

          {/* Action 3: Appearance Row (Segmented Pill Switch) - directly after Saved Places and before Emergency */}
          <div className="flex items-center justify-between p-4 rounded-2xl border border-gray-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 transition-colors min-h-[60px] shadow-xs">
            <div>
              <h3 className="text-base font-bold text-gray-900 dark:text-zinc-100">Appearance</h3>
              <p className="text-xs text-gray-500 dark:text-zinc-400 font-medium">Choose interface display mode</p>
            </div>

            <div className="flex items-center rounded-xl bg-gray-100 dark:bg-zinc-800 p-1 border border-gray-200 dark:border-zinc-700/60">
              <button
                type="button"
                onClick={() => setTheme('light')}
                className={`px-3.5 py-1.5 text-xs font-semibold rounded-lg transition-all ${
                  theme === 'light'
                    ? 'bg-white text-gray-900 shadow-sm'
                    : 'text-gray-500 hover:text-gray-800 dark:text-zinc-400 dark:hover:text-zinc-200'
                }`}
              >
                Light
              </button>
              <button
                type="button"
                onClick={() => setTheme('dark')}
                className={`px-3.5 py-1.5 text-xs font-semibold rounded-lg transition-all ${
                  theme === 'dark'
                    ? 'bg-zinc-900 text-white shadow-sm'
                    : 'text-gray-500 hover:text-gray-800 dark:text-zinc-400 dark:hover:text-zinc-200'
                }`}
              >
                Dark
              </button>
            </div>
          </div>

          {/* Action 4: Emergency Assistance */}
          <button
            type="button"
            onClick={() => setIsEmergencyOpen(true)}
            className="w-full p-4 rounded-2xl bg-white dark:bg-zinc-900 border border-rose-200 dark:border-rose-900/50 hover:border-rose-400 dark:hover:border-rose-800 text-left flex items-center justify-between transition-all press-scale shadow-xs min-h-[60px]"
          >
            <div className="flex items-center gap-3.5">
              <div className="w-11 h-11 rounded-xl bg-rose-100 dark:bg-rose-950/70 text-rose-700 dark:text-rose-300 border border-rose-200 dark:border-rose-800/60 flex items-center justify-center shrink-0">
                <ShieldAlert className="w-6 h-6" />
              </div>
              <div>
                <h3 className="text-base font-bold text-rose-700 dark:text-rose-400">Emergency & Help Desk</h3>
                <p className="text-xs text-[#5F6863] dark:text-zinc-400 font-medium">Medical emergency numbers & live SOS guide</p>
              </div>
            </div>
            <PhoneCall className="w-5 h-5 text-rose-600 dark:text-rose-400" />
          </button>

          {/* Action 5: Ask AI Support */}
          <button
            type="button"
            onClick={() => openAiAssistant('How do I use Cruiser to plan trips or get directions?')}
            className="w-full p-4 rounded-2xl bg-white dark:bg-zinc-900 border border-[#D9DEDA] dark:border-zinc-800 hover:border-[#355F58]/40 dark:hover:border-zinc-700 text-left flex items-center justify-between transition-all press-scale shadow-xs min-h-[60px]"
          >
            <div className="flex items-center gap-3.5">
              <div className="w-11 h-11 rounded-xl bg-[#E8F0EE] dark:bg-zinc-800 text-[#355F58] dark:text-emerald-400 border border-[#D9DEDA] dark:border-zinc-700 flex items-center justify-center shrink-0">
                <HelpCircle className="w-6 h-6" />
              </div>
              <div>
                <h3 className="text-base font-bold text-[#1F2522] dark:text-zinc-100">Help & User Guide</h3>
                <p className="text-xs text-[#5F6863] dark:text-zinc-400 font-medium">Common questions & travel tips</p>
              </div>
            </div>
            <Sparkles className="w-5 h-5 text-[#355F58] dark:text-emerald-400" />
          </button>
        </div>
      </div>

      {/* Logout Action */}
      <div className="pt-3">
        {!showSignOutConfirm ? (
          <button
            type="button"
            onClick={() => setShowSignOutConfirm(true)}
            className="w-full py-4 rounded-2xl bg-rose-50 dark:bg-rose-950/30 hover:bg-rose-100 dark:hover:bg-rose-950/50 border border-rose-200 dark:border-rose-900/50 text-rose-700 dark:text-rose-400 font-extrabold text-base flex items-center justify-center gap-2 press-scale transition-all"
          >
            <LogOut className="w-5 h-5 text-rose-600 dark:text-rose-400" />
            <span>Sign Out of Cruiser</span>
          </button>
        ) : (
          <div className="p-5 rounded-2xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-900/50 space-y-3 text-center animate-fadeIn">
            <h4 className="text-base font-extrabold text-[#1F2522] dark:text-zinc-100">Are you sure you want to sign out?</h4>
            <p className="text-xs text-[#5F6863] dark:text-zinc-400">Your session cookie will be deleted securely from this browser.</p>
            <div className="grid grid-cols-2 gap-3 pt-1">
              <button
                type="button"
                onClick={() => setShowSignOutConfirm(false)}
                className="py-3 rounded-xl bg-[#F0F2EF] dark:bg-zinc-800 text-[#1F2522] dark:text-zinc-200 border border-[#D9DEDA] dark:border-zinc-700 font-bold text-xs"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleLogout}
                className="py-3 rounded-xl bg-rose-600 hover:bg-rose-700 text-white font-black text-xs shadow-xs"
              >
                Yes, Sign Out
              </button>
            </div>
          </div>
        )}
      </div>

    </div>
  );
};

