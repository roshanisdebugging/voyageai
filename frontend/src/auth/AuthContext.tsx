import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import type { AuthUser, UserProfile, UserPreferences, LoginPayload, RegisterPayload, OnboardingUpdatePayload } from './types';
import { authService } from './authService';
import { onSessionExpired, resetSessionExpiredFlag } from './sessionExpiry';
import { purgeClientCaches } from '../store/cache/purge';
import { getCacheOwner, setCacheOwner } from '../store/cache/persist';

/**
 * Bind the client caches to the signed-in user. If the cache belongs to someone else (or to no
 * one), drop it first. Must run BEFORE setAuthUser so no user-scoped fetch can start against
 * another user's data.
 */
const adoptUser = (userId: string) => {
  if (getCacheOwner() !== userId) purgeClientCaches();
  setCacheOwner(userId);
  resetSessionExpiredFlag();
};

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

  const authUserRef = useRef<AuthUser | null>(null);
  authUserRef.current = authUser;

  // Server says the session is gone (401 from any endpoint): purge everything, return to login.
  // The server can report 401 during an infrastructure blip, so confirm with /api/auth/me first.
  const probingRef = useRef(false);
  useEffect(() => {
    return onSessionExpired(async () => {
      if (!authUserRef.current) return; // already logged out; nothing to purge
      if (probingRef.current) return;
      probingRef.current = true;
      try {
        const state = await authService.probeSession();
        if (state !== 'anonymous') {
          // Session is fine (or the server is down): keep the user and caches, re-arm detection.
          resetSessionExpiredFlag();
          return;
        }
        purgeClientCaches();
        authService.clearSessionCache();
        setAuthUser(null);
        setUserProfile(null);
        setUserPreferences(null);
      } finally {
        probingRef.current = false;
      }
    });
  }, []);

  const restoreSession = useCallback(async () => {
    setIsLoading(true);
    try {
      const session = await authService.restoreSession();
      if (session) {
        adoptUser(session.authUser.id);
        setAuthUser(session.authUser);
        setUserProfile(session.userProfile);
        setUserPreferences(session.userPreferences);
      } else {
        // Purge only if the server confirms there is no session; keep the cache across an outage.
        if ((await authService.probeSession()) === 'anonymous') purgeClientCaches();
        setAuthUser(null);
        setUserProfile(null);
        setUserPreferences(null);
      }
    } catch (e) {
      console.warn('Session restoration error', e);
      if ((await authService.probeSession()) === 'anonymous') purgeClientCaches();
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
      adoptUser(session.authUser.id);
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
      adoptUser(session.authUser.id);
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
    } finally {
      // Always purge, even if the server call failed: this device must not keep the user's data.
      purgeClientCaches();
      setAuthUser(null);
      setUserProfile(null);
      setUserPreferences(null);
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
