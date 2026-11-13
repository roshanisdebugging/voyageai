import { useEffect, useRef } from 'react';

export interface UseSyncRevalidationOptions {
  onFocus?: () => void;
  onStorageChange?: (key: string | null, newValue: string | null) => void;
  throttleMs?: number;
}

export function useSyncRevalidation({ onFocus, onStorageChange, throttleMs = 5000 }: UseSyncRevalidationOptions) {
  const onFocusRef = useRef(onFocus);
  const onStorageChangeRef = useRef(onStorageChange);
  const lastRevalidatedRef = useRef<number>(0);

  useEffect(() => {
    onFocusRef.current = onFocus;
    onStorageChangeRef.current = onStorageChange;
  }, [onFocus, onStorageChange]);

  useEffect(() => {
    const triggerFocusThrottled = () => {
      const now = Date.now();
      if (now - lastRevalidatedRef.current > throttleMs) {
        lastRevalidatedRef.current = now;
        if (onFocusRef.current) {
          onFocusRef.current();
        }
      }
    };

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        triggerFocusThrottled();
      }
    };

    const handleWindowFocus = () => {
      triggerFocusThrottled();
    };

    const handleStorage = (event: StorageEvent) => {
      if (onStorageChangeRef.current) {
        onStorageChangeRef.current(event.key, event.newValue);
      }
    };

    window.addEventListener('visibilitychange', handleVisibilityChange);
    window.addEventListener('focus', handleWindowFocus);
    window.addEventListener('storage', handleStorage);

    return () => {
      window.removeEventListener('visibilitychange', handleVisibilityChange);
      window.removeEventListener('focus', handleWindowFocus);
      window.removeEventListener('storage', handleStorage);
    };
  }, [throttleMs]);
}
