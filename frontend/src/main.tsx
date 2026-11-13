import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { ReduxProvider } from './store';
import './styles/index.css';
import App from './App.tsx';

// Strictly enforce zero localStorage / sessionStorage policy: wipe legacy browser storage while preserving theme
if (typeof window !== 'undefined') {
  try {
    const savedTheme = window.localStorage?.getItem('cruiser_theme');
    window.localStorage?.clear();
    if (savedTheme) {
      window.localStorage?.setItem('cruiser_theme', savedTheme);
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
