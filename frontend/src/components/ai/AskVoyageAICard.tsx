import React, { useState } from 'react';
import { useApp } from '../../context/AppContext';
import { ArrowRight, Compass, Utensils, Map, Car } from 'lucide-react';

export const AskVoyageAICard: React.FC = () => {
  const { openAiAssistant } = useApp();
  const [query, setQuery] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (query.trim()) {
      openAiAssistant(query.trim());
      setQuery('');
    }
  };

  const quickChips = [
    { label: 'Nearby places', icon: Compass, prompt: 'What famous places and attractions are near me?' },
    { label: 'Local food', icon: Utensils, prompt: 'What food and restaurants are famous near me?' },
    { label: 'Show map', icon: Map, prompt: 'Show me the interactive map for my current location.' },
    { label: 'Find a ride', icon: Car, prompt: 'Find me a cab or auto ride nearby.' },
  ];

  return (
    <div className="surface-card p-5 space-y-4 border-[#D9DEDA] bg-white shadow-xs rounded-3xl">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-2xl overflow-hidden bg-[#E8F0EE] border border-[#D9DEDA] flex items-center justify-center shrink-0 shadow-xs">
          <img src="/favicon.png" alt="Cruiser" className="w-full h-full object-cover" />
        </div>
        <div>
          <h2 className="text-lg font-extrabold text-[#1F2522]">Ask Cruiser</h2>
          <p className="text-xs text-[#5F6863] font-medium">What would you like to do today?</p>
        </div>
      </div>

      <form onSubmit={handleSubmit} className="flex items-center gap-2 bg-[#F0F2EF] border border-[#D9DEDA] rounded-2xl p-1.5 focus-within:border-[#355F58] transition-all">
        <input
          type="text"
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder="Ask anything... e.g. What is famous here?"
          className="flex-1 bg-transparent px-3 py-2 text-[#1F2522] text-sm font-medium focus:outline-none placeholder:text-[#7C8580] min-w-0"
        />
        <button
          type="submit"
          disabled={!query.trim()}
          className="w-10 h-10 rounded-xl bg-[#355F58] hover:bg-[#2C504A] text-white flex items-center justify-center shrink-0 press-scale disabled:opacity-30 transition-all"
          aria-label="Send query to Cruiser"
        >
          <ArrowRight className="w-5 h-5 font-bold text-white" />
        </button>
      </form>

      {/* 1-Tap Quick Question Chips */}
      <div className="space-y-2 pt-1">
        <span className="text-[11px] font-bold uppercase tracking-wider text-[#5F6863] block">
          Quick Actions
        </span>
        <div className="grid grid-cols-2 gap-2">
          {quickChips.map((chip, idx) => {
            const Icon = chip.icon;
            return (
              <button
                key={idx}
                type="button"
                onClick={() => openAiAssistant(chip.prompt)}
                className="py-3 px-3 rounded-2xl bg-[#F0F2EF] border border-[#D9DEDA] hover:border-[#355F58]/40 text-[#1F2522] text-xs font-bold flex items-center gap-2 press-scale transition-all"
              >
                <Icon className="w-4 h-4 text-[#355F58] shrink-0" />
                <span className="truncate">{chip.label}</span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
};

