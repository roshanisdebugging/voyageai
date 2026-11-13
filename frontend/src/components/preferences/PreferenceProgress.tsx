import React from 'react';

interface PreferenceProgressProps {
  currentStep: number;
  totalSteps: number;
}

export const PreferenceProgress: React.FC<PreferenceProgressProps> = ({
  currentStep,
  totalSteps,
}) => {
  return (
    <div className="flex items-center justify-between gap-4 py-2">
      <span className="text-xs font-bold uppercase tracking-wider text-[#355F58]">
        Step {currentStep} of {totalSteps}
      </span>
      <div className="flex items-center gap-1.5" aria-label={`Progress: step ${currentStep} of ${totalSteps}`}>
        {Array.from({ length: totalSteps }).map((_, idx) => {
          const stepNum = idx + 1;
          const isActive = stepNum === currentStep;
          const isDone = stepNum < currentStep;
          return (
            <span
              key={idx}
              className={`
                h-1.5 rounded-full transition-all duration-300
                ${isActive
                  ? 'w-6 bg-[#355F58]'
                  : isDone
                  ? 'w-2 bg-[#487C74]'
                  : 'w-2 bg-[#D9DEDA]'
                }
              `}
            />
          );
        })}
      </div>
    </div>
  );
};
