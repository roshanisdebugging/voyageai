import React from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useApp } from '../../context/AppContext';
import { useTrip } from '../../features/trip/TripContext';
import type { NavTab } from '../../types';
import { Home, MapPin, Compass, Sparkles, UtensilsCrossed, Car, Wallet } from 'lucide-react';

export const DesktopSidebar: React.FC = () => {
  const { activeTab, setActiveTab, openAiAssistant } = useApp();
  const { currentTrip } = useTrip();
  const navigate = useNavigate();
  const location = useLocation();

  const navItems: { id: NavTab; label: string; path: string; icon: React.ElementType }[] = [
    { id: 'home', label: 'Home', path: '/', icon: Home },
    { id: 'trips', label: 'Trips', path: '/trips', icon: MapPin },
    { id: 'explore', label: 'Explore', path: '/explore', icon: Compass },
    { id: 'guide', label: 'AI Guide', path: '/tour-guide', icon: Sparkles },
  ];

  const currentPath = location.pathname;
  const isHomeActive = currentPath === '/';
  const isTripsActive = currentPath.startsWith('/trip');
  const isExploreActive = currentPath.startsWith('/explore');
  const isGuideActive = currentPath.startsWith('/tour-guide');

  const getIsActive = (id: NavTab) => {
    if (id === 'home') return isHomeActive;
    if (id === 'trips') return isTripsActive;
    if (id === 'explore') return isExploreActive;
    if (id === 'guide') return isGuideActive;
    return activeTab === id;
  };

  const handleNavClick = (id: NavTab, path: string) => {
    setActiveTab(id);
    navigate(path);
  };

  const destinationName = currentTrip?.destination?.name;
  const tripDates = currentTrip ? `${currentTrip.startDate} to ${currentTrip.endDate}` : '';

  // Determine if the selected trip has actually started (today >= startDate or status === 'ACTIVE')
  const hasTripStarted = React.useMemo(() => {
    if (!currentTrip || !currentTrip.startDate) return false;
    if (currentTrip.status === 'ACTIVE') return true;
    const todayStr = new Date().toISOString().split('T')[0];
    return todayStr >= currentTrip.startDate;
  }, [currentTrip]);

  // Calculate current active day number
  const currentDayNumber = React.useMemo(() => {
    if (!currentTrip?.startDate) return 1;
    const start = new Date(currentTrip.startDate);
    const today = new Date();
    start.setHours(0, 0, 0, 0);
    today.setHours(0, 0, 0, 0);
    const diffDays = Math.floor((today.getTime() - start.getTime()) / (1000 * 60 * 60 * 24)) + 1;
    return Math.max(1, diffDays);
  }, [currentTrip?.startDate]);

  // Context is switched if user is on a /trip route or explicitly active
  const isTripContextActive = isTripsActive || currentPath.startsWith('/trip');

  // Should we show the journey widget?
  // Only show ACTIVE JOURNEY when trip has started AND context is switched or trip is active.
  // Show UPCOMING TRIP when context is explicitly switched to a future trip.
  const showActiveWidget = currentTrip && hasTripStarted && isTripContextActive;
  const showUpcomingWidget = currentTrip && !hasTripStarted && isTripContextActive;

  return (
    <aside className="hidden lg:flex flex-col w-60 sticky top-14 h-[calc(100dvh-56px)] border-r border-[#D9DEDA] dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 justify-between transition-colors">
      <div className="space-y-5">
        <nav className="space-y-1">
          {navItems.map(({ id, label, path, icon: Icon }) => {
            const isActive = getIsActive(id);
            return (
              <button
                key={id}
                type="button"
                onClick={() => handleNavClick(id, path)}
                className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-all ${
                  isActive
                    ? 'bg-[#E8F0EE] dark:bg-emerald-950/60 text-[#355F58] dark:text-emerald-400 font-bold border border-[#D9DEDA] dark:border-zinc-700'
                    : 'text-[#5F6863] dark:text-zinc-400 hover:text-[#1F2522] dark:hover:text-zinc-100 hover:bg-[#F0F2EF] dark:hover:bg-zinc-800'
                }`}
              >
                <Icon className={`w-[18px] h-[18px] ${isActive ? 'text-[#355F58] dark:text-emerald-400' : ''}`} />
                <span>{label}</span>
              </button>
            );
          })}
        </nav>

        {/* Active Journey Widget — Rendered ONLY when trip has started & context is active */}
        {showActiveWidget && (
          <div className="p-3.5 rounded-2xl bg-[#F0F2EF] dark:bg-zinc-800/80 border border-[#D9DEDA] dark:border-zinc-700 space-y-2.5">
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-black uppercase tracking-wider text-[#355F58] dark:text-emerald-400">Active Journey</span>
              <span className="text-[10px] font-mono text-[#5F6863] dark:text-zinc-400 font-bold">Day {currentDayNumber}</span>
            </div>

            <div>
              <div className="text-sm font-extrabold text-[#1F2522] dark:text-zinc-100 truncate">{destinationName} Trip</div>
              <div className="text-[11px] text-[#5F6863] dark:text-zinc-400 truncate">{tripDates}</div>
            </div>

            {/* Sub Navigation Tools */}
            <div className="pt-1 space-y-1">
              <button
                type="button"
                onClick={() => {
                  setActiveTab('trips');
                  navigate('/trip/map');
                }}
                className="w-full flex items-center justify-between px-2.5 py-1.5 rounded-lg bg-white dark:bg-zinc-900 hover:bg-[#E8F0EE] dark:hover:bg-zinc-800 text-xs font-bold text-[#1F2522] dark:text-zinc-100 border border-[#D9DEDA] dark:border-zinc-700 transition-all"
              >
                <span className="flex items-center gap-2">
                  <MapPin className="w-3.5 h-3.5 text-[#355F58] dark:text-emerald-400" />
                  <span>Route Map</span>
                </span>
                <span className="text-[10px] text-[#355F58] dark:text-emerald-400 font-mono font-bold">Live</span>
              </button>

              <button
                type="button"
                onClick={() => {
                  navigate('/trip/food');
                }}
                className="w-full flex items-center justify-between px-2.5 py-1.5 rounded-lg bg-white dark:bg-zinc-900 hover:bg-[#E8F0EE] dark:hover:bg-zinc-800 text-xs font-bold text-[#1F2522] dark:text-zinc-100 border border-[#D9DEDA] dark:border-zinc-700 transition-all"
              >
                <span className="flex items-center gap-2">
                  <UtensilsCrossed className="w-3.5 h-3.5 text-[#355F58] dark:text-emerald-400" />
                  <span>Food Guide</span>
                </span>
                <span className="text-[10px] text-amber-700 dark:text-amber-400 font-mono font-bold">Local</span>
              </button>

              <button
                type="button"
                onClick={() => {
                  navigate('/trip/rides');
                }}
                className="w-full flex items-center justify-between px-2.5 py-1.5 rounded-lg bg-white dark:bg-zinc-900 hover:bg-[#E8F0EE] dark:hover:bg-zinc-800 text-xs font-bold text-[#1F2522] dark:text-zinc-100 border border-[#D9DEDA] dark:border-zinc-700 transition-all"
              >
                <span className="flex items-center gap-2">
                  <Car className="w-3.5 h-3.5 text-[#355F58] dark:text-emerald-400" />
                  <span>Rides & Cabs</span>
                </span>
                <span className="text-[10px] text-[#355F58] dark:text-emerald-400 font-mono font-bold">Instant</span>
              </button>

              <button
                type="button"
                onClick={() => {
                  setActiveTab('trips');
                  navigate('/trip/expenses');
                }}
                className="w-full flex items-center justify-between px-2.5 py-1.5 rounded-lg bg-white dark:bg-zinc-900 hover:bg-[#E8F0EE] dark:hover:bg-zinc-800 text-xs font-bold text-[#1F2522] dark:text-zinc-100 border border-[#D9DEDA] dark:border-zinc-700 transition-all"
              >
                <span className="flex items-center gap-2">
                  <Wallet className="w-3.5 h-3.5 text-[#355F58] dark:text-emerald-400" />
                  <span>Expense Ledger</span>
                </span>
                <span className="text-[10px] text-[#355F58] dark:text-emerald-400 font-mono font-bold">Budget</span>
              </button>
            </div>
          </div>
        )}

        {/* Upcoming Trip Widget — Rendered ONLY when context is switched to a future trip */}
        {showUpcomingWidget && (
          <div className="p-3.5 rounded-2xl bg-[#F0F2EF] dark:bg-zinc-800/80 border border-[#D9DEDA] dark:border-zinc-700 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-black uppercase tracking-wider text-amber-800 dark:text-amber-400">Upcoming Trip</span>
              <span className="text-[10px] font-mono text-[#5F6863] dark:text-zinc-400 font-bold">Starts {currentTrip.startDate}</span>
            </div>

            <div>
              <div className="text-sm font-extrabold text-[#1F2522] dark:text-zinc-100 truncate">{destinationName} Trip</div>
              <div className="text-[11px] text-[#5F6863] dark:text-zinc-400 truncate">{tripDates}</div>
            </div>

            <button
              type="button"
              onClick={() => {
                setActiveTab('trips');
                navigate('/trip');
              }}
              className="w-full mt-1 py-1.5 px-2.5 rounded-lg bg-white dark:bg-zinc-900 hover:bg-[#E8F0EE] dark:hover:bg-zinc-800 text-xs font-bold text-[#355F58] dark:text-emerald-400 border border-[#D9DEDA] dark:border-zinc-700 text-center transition-all"
            >
              View Plan Details
            </button>
          </div>
        )}
      </div>

      <button
        type="button"
        onClick={() => openAiAssistant()}
        className="p-3.5 rounded-2xl bg-[#F0F2EF] dark:bg-zinc-800 border border-[#D9DEDA] dark:border-zinc-700 hover:bg-[#E8F0EE] dark:hover:bg-zinc-700/70 transition-colors group text-left"
      >
        <div className="flex items-center gap-2 mb-1">
          <Sparkles className="w-4 h-4 text-[#355F58] dark:text-emerald-400" />
          <span className="text-xs font-bold text-[#1F2522] dark:text-zinc-100">AI Concierge</span>
        </div>
        <p className="text-[11px] text-[#5F6863] dark:text-zinc-400 leading-snug">Ask for recommendations, plan updates or trip help</p>
      </button>
    </aside>
  );
};
