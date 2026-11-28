import React from 'react';
import { ArrowRight } from 'lucide-react';

interface PreferenceFooterProps {
  onContinue: () => void;
  onSkip?: () => void;
  continueText?: string;
  skipText?: string;
  disabled?: boolean;
  isLoading?: boolean;
}

export const PreferenceFooter: React.FC<PreferenceFooterProps> = ({
  onContinue,
  onSkip,
  continueText = 'Continue',
  skipText = 'Skip for now',
  disabled = false,
  isLoading = false,
}) => {
  return (
    <div data-preference-footer className="space-y-3 pt-4">
      <button
        type="button"
        onClick={onContinue}
        disabled={disabled || isLoading}
        aria-label={continueText}
        className="w-full h-14 bg-[var(--preference-action,#355F58)] hover:bg-[var(--preference-action-hover,#2A4D47)] active:bg-[var(--preference-action-active,#1F3B36)] disabled:opacity-[var(--preference-disabled-opacity,0.4)] disabled:bg-[var(--preference-action-disabled,#355F58)] disabled:text-[var(--preference-disabled-text,#fff)] text-[var(--preference-on-accent,#fff)] font-extrabold text-base rounded-2xl flex items-center justify-center gap-2 shadow-[var(--preference-action-shadow,var(--shadow-md))] transition-all select-none touch-manipulation"
      >
        {isLoading ? (
          <div className="w-5 h-5 border-2 border-current border-t-transparent rounded-full animate-spin" />
        ) : (
          <>
            <span>{continueText}</span>
            <ArrowRight className="w-5 h-5" />
          </>
        )}
      </button>

      {onSkip && (
        <button
          type="button"
          onClick={onSkip}
          className="w-full py-2 text-center text-xs font-semibold text-[#5F6863] hover:text-[#1F2522] transition-colors select-none"
        >
          {skipText}
        </button>
      )}
    </div>
  );
};
