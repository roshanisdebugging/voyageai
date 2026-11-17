import React, { useContext, useMemo, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { MicButton } from './MicButton';
import { DEFAULT_MIC_LAYOUT, MicLayoutContext, type MicLayout } from './micLayoutContext';

/**
 * The mic button is mounted once, above the routes, so it survives page changes (for example the jump to the trip
 * wizard's review page). Unmounting it would close the voice socket and end the session, which deletes the trip draft.
 * The main shell tells it where to sit (raised above the AI button, or inside an inline slot) with useMicLayout.
 */
export const MicLayoutProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [layout, setLayout] = useState<MicLayout>(DEFAULT_MIC_LAYOUT);
  const value = useMemo(() => ({ layout, setLayout }), [layout]);
  return <MicLayoutContext.Provider value={value}>{children}</MicLayoutContext.Provider>;
};

const NO_MIC_PATHS = new Set(['/login', '/onboarding']);

/** The one mic button of the app (logged-in pages only, not login or onboarding). */
export const GlobalMicButton: React.FC = () => {
  const { layout } = useContext(MicLayoutContext);
  const location = useLocation();
  if (NO_MIC_PATHS.has(location.pathname)) return null;
  const place = location.pathname === '/trips/new' ? 'wizard' : 'shell';
  return <MicButton raised={layout.raised} inlineTarget={place === 'wizard' ? null : layout.inlineTarget} place={place} />;
};
