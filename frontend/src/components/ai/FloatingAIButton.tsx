import React from 'react';
import { useApp } from '../../context/AppContext';
import { Sparkles } from 'lucide-react';

import { useLocation } from 'react-router-dom';

export const FloatingAIButton: React.FC = () => {
  const { openAiAssistant, aiContextLabel, isAiOpen, selectedHotel, isCabModalOpen } = useApp();
  const location = useLocation();

  const isGuidePage = location.pathname === '/guide' || location.pathname === '/tour-guide';

  // Hide when on Guide page or when other overlays/modals are open
  if (isGuidePage || isAiOpen || selectedHotel || isCabModalOpen) return null;

  return (
    <button
      onClick={() => openAiAssistant()}
      className="fixed z-30 right-4 press-scale animate-scaleIn"
      style={{ bottom: 'calc(var(--bottom-nav-h) + env(safe-area-inset-bottom, 0px) + 12px)' }}
      aria-label={`Ask Cruiser: ${aiContextLabel}`}
    >
      <div className="flex items-center gap-2 px-4 py-3 rounded-full bg-[#355F58] hover:bg-[#2C504A] text-white font-extrabold text-xs shadow-lg border border-[#D9DEDA] transition-all">
        <Sparkles className="w-4 h-4 text-white" />
        <span className="font-extrabold">{aiContextLabel}</span>
      </div>
    </button>
  );
};
