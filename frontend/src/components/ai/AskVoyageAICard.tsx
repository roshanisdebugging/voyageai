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
    <div className="surface-card p-4 sm:p-5 space-y-4 border-[var(--color-border)] bg-[var(--color-surface)] shadow-xs rounded-3xl">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-2xl overflow-hidden bg-[var(--color-surface-elevated)] border border-[var(--color-border)] flex items-center justify-center shrink-0 shadow-xs">
          <img src="/favicon.png" alt="Cruiser" className="w-full h-full object-cover" />
        </div>
        <div>
          <h2 className="text-lg font-extrabold text-[var(--color-text-primary)]">Ask Cruiser</h2>
          <p className="text-xs text-[var(--color-text-secondary)] font-medium">What would you like to do today?</p>
        </div>
      </div>

      <form onSubmit={handleSubmit} className="flex items-center gap-2 bg-[var(--color-surface-elevated)] border border-[var(--color-text-tertiary)] rounded-2xl p-1.5 focus-within:border-[var(--color-primary)] focus-within:outline-2 focus-within:outline-[var(--color-primary)] transition-colors">
        <input
          type="text"
          aria-label="Ask Cruiser"
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder="Ask anything... e.g. What is famous here?"
          className="flex-1 bg-transparent px-3 py-2 text-[var(--color-text-primary)] text-sm font-medium focus:outline-none placeholder:text-[var(--color-text-secondary)] min-w-0"
        />
        <button
          type="submit"
          disabled={!query.trim()}
          className="w-11 h-11 rounded-xl bg-[#355F58] dark:bg-[var(--color-primary)] hover:bg-[#2C504A] dark:hover:bg-[var(--color-primary-light)] text-white dark:text-zinc-950 flex items-center justify-center shrink-0 press-scale disabled:bg-[var(--color-surface)] disabled:text-[var(--color-text-secondary)] disabled:cursor-default focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-primary)] transition-all"
          aria-label="Send query to Cruiser"
        >
          <ArrowRight className="w-5 h-5" />
        </button>
      </form>

      {/* 1-Tap Quick Question Chips */}
      <div className="space-y-2 pt-1">
        <span className="text-[11px] font-bold uppercase tracking-wider text-[var(--color-text-secondary)] block">
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
                className="min-h-11 py-2 px-2.5 text-left rounded-2xl bg-[var(--color-surface-elevated)] border border-[var(--color-border)] hover:border-[var(--color-primary)] text-[var(--color-text-primary)] text-xs font-bold flex items-center gap-2 press-scale focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-primary)] transition-all"
              >
                <Icon className="w-4 h-4 text-[var(--color-primary)] shrink-0" />
                <span className="min-w-0 wrap-anywhere">{chip.label}</span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
};

