import React from 'react';
import { useApp } from '../../context/AppContext';
import { useAuth } from '../../auth/AuthContext';
import { BottomSheet } from '../common/BottomSheet';
import { Check, LogOut, ChevronRight, User, Sliders, Bell, Palette, Shield } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

export const ProfileSheet: React.FC = () => {
  const { isProfileOpen, setIsProfileOpen } = useApp();
  const { userProfile, userPreferences, authUser, signOut } = useAuth();
  const navigate = useNavigate();

  const handleLogout = async () => {
    setIsProfileOpen(false);
    await signOut();
    navigate('/login');
  };

  const name = userProfile?.firstName
    ? `${userProfile.firstName} ${userProfile.lastName || ''}`.trim()
    : authUser?.email
    ? authUser.email.split('@')[0]
    : 'Traveler';

  const emailOrPhone = authUser?.email || authUser?.phone || 'user@cruiser.local';
  const avatarUrl = userProfile?.avatarUrl || 'https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?auto=format&fit=crop&w=400&q=80';
  const travelStyles = userPreferences?.travelStyles?.length ? userPreferences.travelStyles : ['RELAXED', 'FOODIE'];

  const sections = [
    { label: 'Account', icon: User, detail: emailOrPhone },
    { label: 'Preferences', icon: Sliders, detail: `${travelStyles.length} styles set` },
    { label: 'Notifications', icon: Bell, detail: 'On' },
    { label: 'Appearance', icon: Palette, detail: 'Dark' },
    { label: 'Privacy', icon: Shield, detail: 'Encrypted' },
  ];

  return (
    <BottomSheet isOpen={isProfileOpen} onClose={() => setIsProfileOpen(false)} height="expanded" title="Profile & Account">
      <div className="px-5 py-4 space-y-6 bg-white">

        {/* Dynamic Profile Header */}
        <div className="flex items-center gap-3.5 p-3 rounded-2xl bg-[#F0F2EF] border border-[#D9DEDA]">
          <img
            src={avatarUrl}
            alt={name}
            className="w-14 h-14 rounded-full object-cover border-2 border-[#355F58]/40 shrink-0 bg-[#D9DEDA]"
            loading="lazy"
            decoding="async"
          />
          <div className="min-w-0 flex-1">
            <h2 className="text-lg font-black text-[#1F2522] truncate">{name}</h2>
            <p className="text-xs text-[#5F6863] truncate font-medium">{emailOrPhone}</p>
          </div>
        </div>

        {/* Travel Preferences Chips */}
        <div className="space-y-2">
          <h3 className="text-xs uppercase font-extrabold tracking-wider text-[#5F6863]">Travel Style</h3>
          <div className="flex flex-wrap gap-2">
            {travelStyles.map((s, i) => (
              <span key={i} className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-[#E8F0EE] text-[#355F58] text-xs font-extrabold border border-[#D9DEDA]">
                <Check className="w-3.5 h-3.5 text-[#355F58]" /> {s}
              </span>
            ))}
          </div>
        </div>

        {/* Settings List */}
        <div className="space-y-1">
          {sections.map(s => (
            <button
              key={s.label}
              type="button"
              className="w-full press-scale flex items-center justify-between p-3.5 rounded-xl hover:bg-[#F0F2EF] transition-colors border-b border-[#D9DEDA] last:border-0"
            >
              <div className="flex items-center gap-3">
                <s.icon className="w-5 h-5 text-[#355F58]" />
                <span className="text-sm font-bold text-[#1F2522]">{s.label}</span>
              </div>
              <div className="flex items-center gap-1">
                {s.detail && <span className="text-xs font-semibold text-[#5F6863] truncate max-w-[140px]">{s.detail}</span>}
                <ChevronRight className="w-4 h-4 text-[#7C8580]" />
              </div>
            </button>
          ))}
        </div>

        {/* Working Sign Out Action */}
        <button
          type="button"
          onClick={handleLogout}
          className="w-full touch-target press-scale flex items-center justify-center gap-2 py-3.5 rounded-2xl bg-rose-600 hover:bg-rose-700 active:bg-rose-800 text-white text-sm font-extrabold shadow-sm transition-all border border-rose-700"
        >
          <LogOut className="w-4 h-4 text-white" />
          <span>Sign Out</span>
        </button>
      </div>
    </BottomSheet>
  );
};
