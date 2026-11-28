import React from 'react';
import { nextVoiceLanguage, VOICE_LANGUAGES, voiceLanguageOption } from './voiceLanguage';
import { useVoiceLanguage } from './useVoiceLanguage';

/** Settings: Auto / हिन्दी / English as one row of buttons (each at least 44 px). */
export const VoiceLanguageSegmented: React.FC<{ id?: string }> = ({ id = 'voice-language' }) => {
  const [value, setValue] = useVoiceLanguage();
  return (
    <div role="radiogroup" aria-labelledby={`${id}-label`} className="flex gap-1.5">
      {VOICE_LANGUAGES.map(opt => (
        <button
          key={opt.id}
          type="button"
          role="radio"
          aria-checked={value === opt.id}
          aria-label={opt.spoken}
          onClick={() => setValue(opt.id)}
          className={`min-h-11 min-w-11 rounded-[14px] border px-3 text-xs font-bold transition-colors ${
            value === opt.id
              ? 'border-(--itinerary-accent) bg-(--itinerary-accent-surface) text-(--itinerary-accent)'
              : 'border-(--itinerary-control-border) bg-(--color-surface-elevated) text-(--itinerary-muted) hover:border-(--itinerary-accent)'
          }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
};

/** By the mic: a small 44 px button showing the current choice; a tap moves to the next one. */
export const VoiceLanguageChip: React.FC<{ style?: React.CSSProperties; className?: string }> = ({ style, className = '' }) => {
  const [value, setValue] = useVoiceLanguage();
  const current = voiceLanguageOption(value);
  const next = voiceLanguageOption(nextVoiceLanguage(value));
  return (
    <button
      type="button"
      data-voice-language
      onClick={() => setValue(next.id)}
      aria-label={`Voice language: ${current.spoken}. Tap for ${next.spoken}.`}
      title={`Voice language: ${current.spoken}`}
      className={`min-h-11 min-w-11 rounded-full border border-(--itinerary-control-border) bg-(--color-surface) px-2.5 text-xs font-bold text-(--itinerary-accent) shadow-sm press-scale ${className}`}
      style={style}
    >
      {current.short}
    </button>
  );
};
