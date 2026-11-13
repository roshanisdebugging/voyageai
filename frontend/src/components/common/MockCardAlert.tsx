import React from 'react';

interface MockCardAlertProps {
  title?: string;
  location?: string;
  headsUp?: string;
  className?: string;
}

export const MockCardAlert: React.FC<MockCardAlertProps> = ({
  title = 'MOCK ITEM • MOCK MOCK',
  location = 'MOCK LOCATION • MOCK MOCK',
  headsUp = 'MOCK: Live data failed to fetch from backend',
  className = '',
}) => {
  return (
    <div
      className={`relative overflow-hidden rounded-2xl border-2 border-dashed border-amber-500 bg-amber-500/10 p-5 flex flex-col justify-between ${className}`}
    >
      {/* Background Repeating MOCK Watermark Pattern */}
      <div className="absolute inset-0 flex flex-wrap gap-2 p-2 opacity-15 pointer-events-none select-none font-mono font-black text-xs text-amber-700 dark:text-amber-300 uppercase leading-none overflow-hidden">
        {Array(40).fill('MOCK').join(' ')}
      </div>

      <div className="relative z-10 space-y-2">
        <div className="inline-block px-2 py-0.5 rounded bg-amber-500 text-slate-950 font-mono text-[10px] font-black uppercase">
          ⚠️ FAILED_API_FALLBACK
        </div>
        <h4 className="text-base font-black font-mono text-amber-600 dark:text-amber-400 leading-snug">
          {title}
        </h4>
        <p className="text-xs font-mono text-amber-700/80 dark:text-amber-300/80">
          {location}
        </p>
        {headsUp && (
          <p className="text-[10px] font-mono text-amber-600/90 italic">
            {headsUp}
          </p>
        )}
      </div>

      <div className="relative z-10 mt-4 p-2 bg-amber-500/20 border border-amber-500/40 rounded-xl text-[11px] font-mono font-bold text-amber-600 dark:text-amber-400 text-center">
        MOCK DATA • INSPECT BACKEND LOGS
      </div>
    </div>
  );
};
