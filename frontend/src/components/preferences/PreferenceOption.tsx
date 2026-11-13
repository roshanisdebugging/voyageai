import React from 'react';
import { Check } from 'lucide-react';

interface PreferenceOptionProps {
  id: string;
  label: string;
  subtitle?: string;
  icon?: string | React.ReactNode;
  selected: boolean;
  onSelect: (id: string) => void;
  mode?: 'single' | 'multiple';
}

export const PreferenceOption: React.FC<PreferenceOptionProps> = ({
  id,
  label,
  subtitle,
  icon,
  selected,
  onSelect,
  mode = 'multiple',
}) => {
  return (
    <button
      type="button"
      onClick={() => onSelect(id)}
      aria-pressed={selected}
      aria-label={`${label} (${mode} selection)`}
      className={`
        relative w-full text-left p-4 rounded-2xl border transition-all duration-200 flex items-center justify-between gap-3
        min-h-[56px] select-none touch-manipulation active:scale-[0.98]
        ${selected
          ? 'bg-[#E8F0EE] border-[#355F58] text-[#1F2522] shadow-xs ring-1 ring-[#355F58]/30 font-bold'
          : 'bg-white border-[#D9DEDA] text-[#1F2522] hover:border-[#355F58]/40 hover:bg-[#F0F2EF]'
        }
      `}
    >
      <div className="flex items-center gap-3.5 min-w-0 flex-1">
        {icon && (
          <span className="text-2xl flex-shrink-0 leading-none">
            {typeof icon === 'string' ? icon : icon}
          </span>
        )}
        <div className="flex-1 min-w-0">
          <div className={`font-bold text-sm leading-tight ${selected ? 'text-[#355F58]' : 'text-[#1F2522]'}`}>
            {label}
          </div>
          {subtitle && (
            <p className="text-xs text-[#5F6863] mt-0.5 leading-snug line-clamp-1 font-medium">
              {subtitle}
            </p>
          )}
        </div>
      </div>

      <div className={`
        w-6 h-6 rounded-full border flex items-center justify-center transition-all flex-shrink-0
        ${selected
          ? 'bg-[#355F58] border-[#355F58] text-white scale-100'
          : 'border-[#D9DEDA] bg-[#F0F2EF] text-transparent scale-90'
        }
      `}>
        <Check className="w-3.5 h-3.5 stroke-[3]" />
      </div>
    </button>
  );
};
