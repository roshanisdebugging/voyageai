import React from 'react';
import { useApp } from '../../context/AppContext';
import { Home, Calendar, MapPin, Sparkles, Menu } from 'lucide-react';
import { useNavigate, useLocation } from 'react-router-dom';
import type { NavTab } from '../../types';

interface TabItem {
  id: NavTab | 'more' | 'map' | 'guide';
  path: string;
  label: string;
  icon: React.ElementType;
}

const tabs: TabItem[] = [
  { id: 'home', path: '/', label: 'Home', icon: Home },
  { id: 'trips', path: '/trips', label: 'Trips', icon: Calendar },
  { id: 'guide' as any, path: '/guide', label: 'Guide', icon: Sparkles },
  { id: 'map', path: '/map', label: 'Map', icon: MapPin },
  { id: 'more' as any, path: '/more', label: 'More', icon: Menu },
];

export const MobileBottomNav: React.FC = () => {
  const { setActiveTab, setTripView, setNavigationTarget } = useApp();
  const navigate = useNavigate();
  const location = useLocation();

  const handleTabClick = (tab: TabItem) => {
    if (tab.id === 'map') {
      setActiveTab('trips');
      setTripView('map');
    } else {
      setTripView('home');
      setNavigationTarget(null);
      if (tab.id === 'home' || tab.id === 'trips' || tab.id === 'explore') {
        setActiveTab(tab.id as NavTab);
      }
    }
    navigate(tab.path);
  };

  return (
    <nav
      className="fixed bottom-0 left-0 right-0 z-[100] bg-white/95 dark:bg-zinc-900/95 backdrop-blur-lg border-t border-[#D9DEDA] dark:border-zinc-800 shadow-md lg:hidden transition-colors"
      style={{ paddingBottom: 'max(6px, env(safe-area-inset-bottom, 0px))' }}
    >
      <div className="flex items-center justify-around h-16 max-w-lg mx-auto px-2">
        {tabs.map((tab) => {
          const isActive = tab.path === '/'
            ? location.pathname === '/'
            : location.pathname.startsWith(tab.path) || (tab.path === '/guide' && location.pathname === '/tour-guide');
          const Icon = tab.icon;

          return (
            <button
              key={tab.label}
              type="button"
              onClick={() => handleTabClick(tab)}
              className={`flex-1 flex flex-col items-center justify-center py-2 px-1 rounded-2xl transition-all ${
                isActive
                  ? 'text-[#355F58] dark:text-emerald-400 bg-[#E8F0EE] dark:bg-emerald-950/60 font-bold'
                  : 'text-[#5F6863] dark:text-zinc-400 hover:text-[#1F2522] dark:hover:text-zinc-100'
              }`}
              aria-label={tab.label}
              aria-current={isActive ? 'page' : undefined}
            >
              <Icon className={`w-6 h-6 ${isActive ? 'text-[#355F58] dark:text-emerald-400 stroke-[2.5]' : 'text-[#5F6863] dark:text-zinc-400 stroke-[1.8]'}`} />
              <span className={`text-[12px] leading-tight mt-1 ${isActive ? 'font-extrabold text-[#1F2522] dark:text-zinc-100' : 'font-semibold text-[#5F6863] dark:text-zinc-400'}`}>
                {tab.label}
              </span>
            </button>
          );
        })}
      </div>
    </nav>
  );
};
