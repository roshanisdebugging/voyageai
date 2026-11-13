import React, { createContext, useContext, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import type { MapFocusTarget } from '../types';

export type AppMode = 'explore' | 'map' | 'trips' | 'guide';

export interface ExploreFocusTarget {
  placeId: string;
  category?: string;
}

interface NavigationContextType {
  activeMode: AppMode;
  setActiveMode: (mode: AppMode) => void;
  mapFocusTarget: MapFocusTarget | null;
  setMapFocusTarget: (target: MapFocusTarget | null) => void;
  exploreFocusTarget: ExploreFocusTarget | null;
  setExploreFocusTarget: (target: ExploreFocusTarget | null) => void;
  navigateToMap: (target?: MapFocusTarget) => void;
  navigateToExplore: (placeId?: string, category?: string) => void;
}

const NavigationContext = createContext<NavigationContextType | undefined>(undefined);

export const NavigationProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [activeMode, setActiveMode] = useState<AppMode>('explore');
  const [mapFocusTarget, setMapFocusTarget] = useState<MapFocusTarget | null>(null);
  const [exploreFocusTarget, setExploreFocusTarget] = useState<ExploreFocusTarget | null>(null);
  const navigate = useNavigate();

  const navigateToMap = useCallback((target?: MapFocusTarget) => {
    if (target) {
      setMapFocusTarget(target);
    }
    setActiveMode('map');
    navigate('/map');
  }, [navigate]);

  const navigateToExplore = useCallback((placeId?: string, category?: string) => {
    if (placeId) {
      setExploreFocusTarget({ placeId, category });
    }
    setActiveMode('explore');
    navigate('/explore');
  }, [navigate]);

  return (
    <NavigationContext.Provider
      value={{
        activeMode,
        setActiveMode,
        mapFocusTarget,
        setMapFocusTarget,
        exploreFocusTarget,
        setExploreFocusTarget,
        navigateToMap,
        navigateToExplore,
      }}
    >
      {children}
    </NavigationContext.Provider>
  );
};

export const useNavigation = (): NavigationContextType => {
  const context = useContext(NavigationContext);
  if (!context) {
    throw new Error('useNavigation must be used within a NavigationProvider');
  }
  return context;
};
