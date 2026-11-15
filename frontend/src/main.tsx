import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { ReduxProvider } from './store';
import { CACHE_STORAGE_KEY } from './store/cache/persist';
import './styles/index.css';
import App from './App.tsx';

// Wipe legacy browser storage on load, preserving only the theme and the versioned Redux cache.
// (The store module has already hydrated from CACHE_STORAGE_KEY by the time this runs, since ES
// imports are hoisted, so that key must survive or reloads would lose the cache.)
if (typeof window !== 'undefined') {
  try {
    const keep: Record<string, string> = {};
    for (const key of ['cruiser_theme', CACHE_STORAGE_KEY]) {
      const value = window.localStorage?.getItem(key);
      if (value !== null && value !== undefined) keep[key] = value;
    }
    window.localStorage?.clear();
    for (const [key, value] of Object.entries(keep)) {
      window.localStorage?.setItem(key, value);
    }
    window.sessionStorage?.clear();
  } catch {
    /* ignore */
  }
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ReduxProvider>
      <App />
    </ReduxProvider>
  </StrictMode>,
);
