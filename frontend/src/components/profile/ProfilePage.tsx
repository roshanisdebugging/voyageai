import React from 'react';
import { useApp } from '../../context/AppContext';
import { useTheme } from '../../context/ThemeContext';
import { useAuth } from '../../auth/AuthContext';
import { BottomSheet } from '../common/BottomSheet';
import { Check, LogOut, ChevronRight, User, Sliders, Bell, Palette, Shield } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

export const ProfileSheet: React.FC = () => {
  const { isProfileOpen, setIsProfileOpen } = useApp();
  const { userProfile, userPreferences, authUser, signOut } = useAuth();
  const { theme } = useTheme();
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
    { label: 'Appearance', icon: Palette, detail: theme === 'dark' ? 'Dark' : 'Light' },
    { label: 'Privacy', icon: Shield, detail: 'Encrypted' },
  ];

  return (
    <BottomSheet isOpen={isProfileOpen} onClose={() => setIsProfileOpen(false)} height="expanded" title="Profile & Account">
      <div className="mx-auto max-w-lg px-5 py-4 space-y-4">

        {/* Dynamic Profile Header */}
        <div className="flex flex-col items-center gap-2 text-center">
          <img
            src={avatarUrl}
            alt={name}
            className="w-14 h-14 rounded-full object-cover border-2 border-[var(--color-border)] shrink-0 bg-[var(--color-surface-elevated)]"
            loading="lazy"
            decoding="async"
          />
          <div className="min-w-0 max-w-full">
            <h2 className="text-lg font-black text-[var(--color-text-primary)] truncate">{name}</h2>
            <p className="text-xs text-[var(--color-text-secondary)] truncate font-medium">{emailOrPhone}</p>
          </div>
        </div>

        {/* Travel Preferences Chips */}
        <div className="flex flex-wrap items-center justify-center gap-2">
          <h3 className="text-xs uppercase font-extrabold tracking-wider text-[var(--color-text-secondary)]">Travel Style</h3>
          <div className="flex min-w-0 flex-wrap justify-center gap-2">
            {travelStyles.map((s, i) => (
              <span key={i} className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-[var(--color-surface-elevated)] text-[var(--color-primary)] text-xs font-extrabold border border-[var(--color-border)]">
                <Check className="w-3.5 h-3.5 text-[var(--color-primary)]" /> {s}
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
              className="w-full min-h-11 press-scale flex items-center justify-between gap-2 px-2 py-2 text-left rounded-lg hover:bg-[var(--color-surface-elevated)] focus-visible:outline-2 focus-visible:outline-[var(--color-primary)] transition-colors border-b border-[var(--color-border)] last:border-0"
            >
              <div className="flex items-center gap-3">
                <s.icon className="w-5 h-5 text-[var(--color-primary)]" />
                <span className="text-sm font-bold text-[var(--color-text-primary)]">{s.label}</span>
              </div>
              <div className="flex min-w-0 items-center gap-1">
                {s.detail && <span className="text-xs font-semibold text-[var(--color-text-secondary)] truncate max-w-[140px]">{s.detail}</span>}
                <ChevronRight className="w-4 h-4 shrink-0 text-[var(--color-text-secondary)]" />
              </div>
            </button>
          ))}
        </div>

        {/* Working Sign Out Action */}
        <button
          type="button"
          onClick={handleLogout}
          className="w-full touch-target press-scale flex items-center justify-center gap-2 py-3.5 rounded-2xl border border-rose-700 dark:border-rose-500 text-rose-800 dark:text-rose-300 hover:bg-rose-50 dark:hover:bg-rose-950 focus-visible:outline-2 focus-visible:outline-offset-2 text-sm font-extrabold transition-colors"
        >
          <LogOut className="w-4 h-4" aria-hidden="true" />
          <span>Sign Out</span>
        </button>
      </div>
    </BottomSheet>
  );
};
