import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { Check, RotateCcw } from 'lucide-react';

/**
 * One toast at a time, shown at the bottom of the screen.
 * Small actions (save/unsave place, mark done, change a filter) pass an `undo`
 * function; tapping Undo runs it. Undo is tap-only by design.
 */

interface ToastOptions {
  message: string;
  undo?: () => void | Promise<void>;
  tone?: 'info' | 'error';
  durationMs?: number;
}

interface ToastState extends ToastOptions {
  id: number;
}

interface ToastContextValue {
  showToast: (options: ToastOptions) => void;
}

const ToastContext = createContext<ToastContextValue>({ showToast: () => {} });

export const useToast = () => useContext(ToastContext);

export const ToastProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [toast, setToast] = useState<ToastState | null>(null);
  const [isUndoing, setIsUndoing] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const idRef = useRef(0);

  const clearTimer = () => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = null;
  };

  const showToast = useCallback((options: ToastOptions) => {
    clearTimer();
    idRef.current += 1;
    setIsUndoing(false);
    setToast({ ...options, id: idRef.current });
  }, []);

  useEffect(() => {
    if (!toast) return;
    const duration = toast.durationMs ?? (toast.undo ? 5000 : 3000);
    timerRef.current = setTimeout(() => setToast(null), duration);
    return clearTimer;
  }, [toast]);

  const handleUndo = async () => {
    if (!toast?.undo || isUndoing) return;
    clearTimer();
    setIsUndoing(true);
    try {
      await toast.undo();
      setToast({ id: ++idRef.current, message: 'Undone', durationMs: 2000 });
    } catch (err: any) {
      setToast({ id: ++idRef.current, message: err?.message || "Couldn't undo. Please try again.", tone: 'error' });
    } finally {
      setIsUndoing(false);
    }
  };

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}
      {toast && (
        <div
          key={toast.id}
          role="status"
          aria-live="polite"
          className={`fixed bottom-24 left-1/2 -translate-x-1/2 z-[70] w-[calc(100%-32px)] max-w-sm px-4 py-3 rounded-2xl shadow-2xl flex items-center justify-between gap-3 animate-fadeIn text-xs font-bold ${
            toast.tone === 'error' ? 'bg-rose-600 text-white' : 'bg-[#1F2522] text-white'
          }`}
        >
          <span className="flex items-center gap-2 min-w-0">
            {toast.tone !== 'error' && <Check className="w-4 h-4 text-emerald-400 shrink-0" />}
            <span className="truncate">{toast.message}</span>
          </span>
          {toast.undo && (
            <button
              type="button"
              onClick={handleUndo}
              disabled={isUndoing}
              className="shrink-0 flex items-center gap-1 px-3 py-1.5 rounded-xl bg-white/15 hover:bg-white/25 text-white font-extrabold disabled:opacity-60"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              {isUndoing ? 'Undoing…' : 'Undo'}
            </button>
          )}
        </div>
      )}
    </ToastContext.Provider>
  );
};
