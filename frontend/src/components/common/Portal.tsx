import type React from 'react';
import { createPortal } from 'react-dom';

/**
 * Renders children directly under <body>, outside any parent stacking context, so a dialog
 * with z-[var(--z-modal)] always sits above the header and bottom nav.
 */
export const Portal: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  if (typeof document === 'undefined') return null;
  return createPortal(children, document.body);
};
