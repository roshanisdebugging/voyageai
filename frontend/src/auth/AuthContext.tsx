import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import type { AuthUser, UserProfile, UserPreferences, LoginPayload, RegisterPayload, OnboardingUpdatePayload } from './types';
import { authService } from './authService';

interface AuthContextType {
  authUser: AuthUser | null;
  userProfile: UserProfile | null;
  userPreferences: UserPreferences | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  signIn: (payload: LoginPayload) => Promise<void>;
  signUp: (payload: RegisterPayload) => Promise<void>;
  signOut: () => Promise<void>;
  updateOnboarding: (payload: OnboardingUpdatePayload) => Promise<void>;
  restoreSession: () => Promise<void>;
}

const defaultAuthContext: AuthContextType = {
  authUser: null,
  userProfile: null,
  userPreferences: null,
  isAuthenticated: false,
  isLoading: false,
  signIn: async () => {},
  signUp: async () => {},
  signOut: async () => {},
  updateOnboarding: async () => {},
  restoreSession: async () => {},
};

const AuthContext = createContext<AuthContextType>(defaultAuthContext);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [authUser, setAuthUser] = useState<AuthUser | null>(null);
  const [userProfile, setUserProfile] = useState<UserProfile | null>(null);
  const [userPreferences, setUserPreferences] = useState<UserPreferences | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);

  const restoreSession = useCallback(async () => {
    setIsLoading(true);
    try {
      const session = await authService.restoreSession();
      if (session) {
        setAuthUser(session.authUser);
        setUserProfile(session.userProfile);
        setUserPreferences(session.userPreferences);
      } else {
        setAuthUser(null);
        setUserProfile(null);
        setUserPreferences(null);
      }
    } catch (e) {
      console.warn('Session restoration error', e);
      setAuthUser(null);
      setUserProfile(null);
      setUserPreferences(null);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    restoreSession();
  }, [restoreSession]);

  const signIn = useCallback(async (payload: LoginPayload) => {
    setIsLoading(true);
    try {
      const session = await authService.login(payload);
      setAuthUser(session.authUser);
      setUserProfile(session.userProfile);
      setUserPreferences(session.userPreferences);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const signUp = useCallback(async (payload: RegisterPayload) => {
    setIsLoading(true);
    try {
      const session = await authService.register(payload);
      setAuthUser(session.authUser);
      setUserProfile(session.userProfile);
      setUserPreferences(session.userPreferences);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const signOut = useCallback(async () => {
    setIsLoading(true);
    try {
      await authService.logout();
      setAuthUser(null);
      setUserProfile(null);
      setUserPreferences(null);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const updateOnboarding = useCallback(async (payload: OnboardingUpdatePayload) => {
    const res = await authService.updateOnboarding(payload);
    setUserProfile(res.userProfile);
    setUserPreferences(res.userPreferences);
  }, []);

  return (
    <AuthContext.Provider value={{
      authUser,
      userProfile,
      userPreferences,
      isAuthenticated: !!authUser && !!userProfile,
      isLoading,
      signIn,
      signUp,
      signOut,
      updateOnboarding,
      restoreSession,
    }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  return context || defaultAuthContext;
};
