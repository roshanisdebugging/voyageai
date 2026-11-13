import React, { useState, useRef, useEffect } from 'react';
import { useApp } from '../../context/AppContext';
import { useAuth } from '../../auth/AuthContext';
import { useTrip } from '../../features/trip/TripContext';
import { ArrowLeft, MapPin, Compass, ChevronDown, Check } from 'lucide-react';
import { useNavigate, useLocation } from 'react-router-dom';

export const MobileHeader: React.FC = () => {
  const {
    setIsProfileOpen,
    userLocationName,
    setIsLocationModalOpen,
    activeContextMode,
    setActiveContextMode,
  } = useApp();
  const { userProfile } = useAuth();
  const { currentTrip } = useTrip();

  const navigate = useNavigate();
  const location = useLocation();

  const [dropdownOpen, setDropdownOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const isSubRoute = location.pathname.startsWith('/trip/') && location.pathname !== '/trip';
  const avatarUrl = userProfile?.avatarUrl || 'https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?auto=format&fit=crop&w=80&q=80';
  const destinationName = currentTrip?.destination?.name || 'Trip';

  const routeTitles: Record<string, string> = {
    '/trip/itinerary': 'Itinerary',
    '/trip/map': 'Live Map',
    '/trip/bookings': 'Reservations',
    '/trip/expenses': 'Expenses',
    '/trip/guide': 'Guide',
  };

  // Close dropdown on outside click
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setDropdownOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  return (
    <header
      className="sticky top-0 z-[2000] bg-white/95 dark:bg-zinc-900/95 backdrop-blur-md border-b border-[#D9DEDA] dark:border-zinc-800 transition-colors"
      style={{ paddingTop: 'env(safe-area-inset-top, 0px)' }}
    >
      <div className="flex items-center justify-between h-14 px-4 max-w-xl mx-auto gap-2">

        {/* Left Side: Brand Logo or Sub-Route Back Action */}
        {isSubRoute ? (
          <button
            type="button"
            onClick={() => navigate('/trip')}
            className="flex items-center gap-2 text-[#1F2522] dark:text-zinc-100 font-bold text-sm min-w-0 press-scale"
            aria-label="Back to trip"
          >
            <ArrowLeft className="w-5 h-5 text-[#355F58] dark:text-emerald-400 shrink-0" />
            <span className="truncate">
              {destinationName}
              <span className="text-[#5F6863] dark:text-zinc-400 font-normal"> · {routeTitles[location.pathname] || 'Back'}</span>
            </span>
          </button>
        ) : (
          <div
            className="flex items-center gap-2 cursor-pointer shrink-0 press-scale"
            onClick={() => navigate('/')}
          >
            <div className="w-8 h-8 rounded-xl overflow-hidden bg-[#E8F0EE] dark:bg-zinc-800 border border-[#D9DEDA] dark:border-zinc-700 flex items-center justify-center shadow-xs">
              <img src="/favicon.png" alt="Cruiser" className="w-full h-full object-cover" />
            </div>
            <span className="text-lg font-extrabold text-[#1F2522] dark:text-zinc-100 tracking-tight">
              Cruiser
            </span>
          </div>
        )}

        {/* Center: Single Interactive Context Switcher Pill */}
        <div className="relative" ref={dropdownRef}>
          <button
            type="button"
            onClick={() => setDropdownOpen(prev => !prev)}
            className="px-3 py-1.5 rounded-full bg-[#F0F2EF] dark:bg-zinc-800 border border-[#D9DEDA] dark:border-zinc-700 hover:border-[#355F58]/40 dark:hover:border-zinc-600 text-[#1F2522] dark:text-zinc-100 text-xs font-bold flex items-center gap-1.5 max-w-[175px] truncate shadow-xs transition-all press-scale"
            title="Tap to switch active context mode"
          >
            {activeContextMode === 'trip' && currentTrip ? (
              <>
                <Compass className="w-3.5 h-3.5 text-amber-600 dark:text-amber-400 shrink-0" />
                <span className="truncate">{currentTrip?.destination?.name || 'Trip Mode'}</span>
              </>
            ) : (
              <>
                <MapPin className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400 shrink-0" />
                <span className="truncate">{userLocationName || 'Near You'}</span>
              </>
            )}
            <ChevronDown className={`w-3 h-3 text-[#5F6863] dark:text-zinc-400 shrink-0 transition-transform duration-200 ${dropdownOpen ? 'rotate-180 text-[#355F58] dark:text-emerald-400' : ''}`} />
          </button>

          {/* Context Switcher Dropdown */}
          {dropdownOpen && (
            <div className="absolute top-full mt-2 left-1/2 -translate-x-1/2 w-64 p-2 rounded-2xl bg-white dark:bg-zinc-900 border border-[#D9DEDA] dark:border-zinc-800 shadow-2xl z-[2001] animate-fadeIn">
              <div className="text-[10px] font-bold uppercase tracking-wider text-[#5F6863] dark:text-zinc-400 px-2.5 py-1 flex items-center justify-between border-b border-[#D9DEDA] dark:border-zinc-800 mb-1">
                <span>Active Mode</span>
                <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
              </div>

              {/* Option A: Physical GPS Mode */}
              <button
                type="button"
                onClick={() => {
                  setActiveContextMode('local');
                  setDropdownOpen(false);
                }}
                className={`w-full flex items-center justify-between p-2.5 rounded-xl text-xs transition-all ${
                  activeContextMode === 'local'
                    ? 'bg-[#E8F0EE] dark:bg-emerald-950/60 text-[#1F2522] dark:text-zinc-100 font-bold'
                    : 'hover:bg-[#F0F2EF] dark:hover:bg-zinc-800 text-[#5F6863] dark:text-zinc-400'
                }`}
              >
                <div className="flex items-center gap-2.5 text-left min-w-0">
                  <div className="w-7 h-7 rounded-lg bg-emerald-100 dark:bg-emerald-950/80 text-emerald-700 dark:text-emerald-300 flex items-center justify-center shrink-0">
                    <MapPin className="w-4 h-4" />
                  </div>
                  <div className="min-w-0">
                    <p className="font-bold text-[#1F2522] dark:text-zinc-100 truncate">Near Me (GPS)</p>
                    <p className="text-[10px] text-[#5F6863] dark:text-zinc-400 truncate">{userLocationName || 'Live Location'}</p>
                  </div>
                </div>
                {activeContextMode === 'local' && <Check className="w-4 h-4 text-[#355F58] dark:text-emerald-400 shrink-0" />}
              </button>

              {/* Option B: Trip Mode */}
              {currentTrip && (
                <button
                  type="button"
                  onClick={() => {
                    setActiveContextMode('trip');
                    setDropdownOpen(false);
                  }}
                  className={`w-full flex items-center justify-between p-2.5 rounded-xl text-xs transition-all mt-1 ${
                    activeContextMode === 'trip'
                      ? 'bg-[#E8F0EE] dark:bg-amber-950/60 text-[#1F2522] dark:text-zinc-100 font-bold'
                      : 'hover:bg-[#F0F2EF] dark:hover:bg-zinc-800 text-[#5F6863] dark:text-zinc-400'
                  }`}
                >
                  <div className="flex items-center gap-2.5 text-left min-w-0">
                    <div className="w-7 h-7 rounded-lg bg-amber-100 dark:bg-amber-950/80 text-amber-700 dark:text-amber-300 flex items-center justify-center shrink-0">
                      <Compass className="w-4 h-4" />
                    </div>
                    <div className="min-w-0">
                      <p className="font-bold text-[#1F2522] dark:text-zinc-100 truncate">Trip Mode</p>
                      <p className="text-[10px] text-[#5F6863] dark:text-zinc-400 truncate">{currentTrip.destination.name}</p>
                    </div>
                  </div>
                  {activeContextMode === 'trip' && <Check className="w-4 h-4 text-[#355F58] dark:text-emerald-400 shrink-0" />}
                </button>
              )}

              <div className="pt-1.5 mt-1.5 border-t border-[#D9DEDA] dark:border-zinc-800">
                <button
                  type="button"
                  onClick={() => {
                    setDropdownOpen(false);
                    setIsLocationModalOpen(true);
                  }}
                  className="w-full text-center text-[11px] font-bold text-[#355F58] dark:text-emerald-400 hover:underline py-1"
                >
                  Change GPS Location...
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Right Side: Profile Action */}
        <button
          type="button"
          onClick={() => setIsProfileOpen(true)}
          className="p-0.5 rounded-full border border-[#D9DEDA] dark:border-zinc-700 hover:border-[#355F58] dark:hover:border-emerald-400 transition-colors press-scale shrink-0"
          aria-label="Profile and account settings"
        >
          <div className="w-8 h-8 rounded-full bg-[#F0F2EF] dark:bg-zinc-800 overflow-hidden">
            <img
              src={avatarUrl}
              alt={userProfile?.firstName || 'Profile'}
              className="w-full h-full object-cover"
              loading="lazy"
              decoding="async"
            />
          </div>
        </button>

      </div>
    </header>
  );
};

