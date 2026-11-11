import type { SessionData, LoginPayload, RegisterPayload, OnboardingUpdatePayload } from './types';
import { wsClient } from '../services/wsClient';
import { getApiBaseUrl, getAuthHeaders, setAuthToken, getAuthToken } from '../config/apiConfig';

let inMemorySession: SessionData | null = null;

export const authService = {
  clearSessionCache() {
    inMemorySession = null;
    setAuthToken(null);
    try {
      if (typeof window !== 'undefined' && window.localStorage) {
        localStorage.clear();
      }
      if (typeof window !== 'undefined' && window.sessionStorage) {
        sessionStorage.clear();
      }
    } catch {
      /* ignore */
    }
  },

  saveCachedSession(session: SessionData) {
    inMemorySession = session;
    if (session?.token) {
      setAuthToken(session.token);
    }
  },

  getCachedSession(): SessionData | null {
    return inMemorySession;
  },

  getAuthHeaders(): Record<string, string> {
    return getAuthHeaders();
  },

  async register(data: RegisterPayload): Promise<SessionData> {
    const url = `${getApiBaseUrl()}/api/auth/register`;
    const response = await fetch(url, {
      method: 'POST',
      credentials: 'include',
      headers: this.getAuthHeaders(),
      body: JSON.stringify(data),
    });

    if (!response.ok) {
      const errData = await response.json().catch(() => ({}));
      throw new Error(errData.detail || 'Registration failed');
    }

    const resJson = await response.json();
    if (resJson && resJson.token && resJson.authUser) {
      const sessionData: SessionData = {
        token: resJson.token,
        authUser: resJson.authUser,
        userProfile: resJson.userProfile,
        userPreferences: resJson.userPreferences,
      };
      this.saveCachedSession(sessionData);
      return sessionData;
    }

    const session = await this.getCurrentUser();
    if (session) return session;

    throw new Error('Registration succeeded but the session could not be loaded. Please sign in.');
  },

  async login(payload: LoginPayload): Promise<SessionData> {
    const url = `${getApiBaseUrl()}/api/auth/login`;
    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: this.getAuthHeaders(),
        body: JSON.stringify(payload),
        credentials: 'include',
      });

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || 'Authentication failed. Please check your credentials.');
      }

      const data: SessionData = await response.json();
      this.saveCachedSession(data);
      return data;
    } catch (err: any) {
      console.warn('REST Auth login failed, attempting WS fallback...', err);
      try {
        const wsData: SessionData = await wsClient.sendRequest('auth:login', payload);
        if (wsData && wsData.authUser) {
          this.saveCachedSession(wsData);
          return wsData;
        }
      } catch (wsErr) {
        console.warn('WebSocket auth login fallback error:', wsErr);
      }
      throw err;
    }
  },

  async getCurrentUser(): Promise<SessionData | null> {
    const url = `${getApiBaseUrl()}/api/auth/me`;
    try {
      const response = await fetch(url, {
        method: 'GET',
        headers: this.getAuthHeaders(),
        credentials: 'include',
      });
      if (response.ok) {
        const data = await response.json();
        if (data && data.authenticated && data.authUser) {
          const directToken = getAuthToken() || undefined;
          const sessionData: SessionData = {
            token: data.token || directToken,
            authUser: data.authUser,
            userProfile: data.userProfile,
            userPreferences: data.userPreferences,
          };
          this.saveCachedSession(sessionData);
          return sessionData;
        }
      }
    } catch (e) {
      console.warn('getCurrentUser /api/auth/me error:', e);
    }
    return null;
  },

  async restoreSession(): Promise<SessionData | null> {
    const url = `${getApiBaseUrl()}/api/auth/me`;
    const cached = this.getCachedSession();

    try {
      const response = await fetch(url, {
        method: 'GET',
        headers: this.getAuthHeaders(),
        credentials: 'include',
      });

      if (response.ok) {
        const data = await response.json();
        if (data && data.authenticated && data.authUser) {
          const sessionData: SessionData = {
            token: data.token || cached?.token || getAuthToken() || undefined,
            authUser: data.authUser,
            userProfile: data.userProfile,
            userPreferences: data.userPreferences,
          };
          this.saveCachedSession(sessionData);
          return sessionData;
        }
      }
    } catch (err) {
      console.warn('REST session restore error, trying WS fallback', err);
    }

    // Try WS fallback if cached token exists
    const token = cached?.token || getAuthToken();
    if (token) {
      try {
        const wsData: SessionData = await wsClient.sendRequest('auth:session', { token });
        if (wsData && wsData.authUser) {
          if (!wsData.token) wsData.token = token;
          this.saveCachedSession(wsData);
          return wsData;
        }
      } catch (wsErr) {
        console.warn('WebSocket session restore failed', wsErr);
      }
    }

    // Preserve cached session for offline/graceful degraded operation if valid user profile exists
    if (cached && cached.authUser) {
      return cached;
    }

    this.clearSessionCache();
    return null;
  },

  async logout(): Promise<void> {
    const url = `${getApiBaseUrl()}/api/auth/logout`;
    try {
      await fetch(url, {
        method: 'POST',
        headers: this.getAuthHeaders(),
        credentials: 'include',
      });
    } catch (e) {
      console.warn('REST Logout error, trying WS logout', e);
      try {
        await wsClient.sendRequest('auth:logout', {});
      } catch {
        /* best effort */
      }
    } finally {
      this.clearSessionCache();
    }
  },

  async updateOnboarding(payload: OnboardingUpdatePayload): Promise<{ userProfile: SessionData['userProfile']; userPreferences: SessionData['userPreferences'] }> {
    const cached = this.getCachedSession();
    const token = cached?.token || getAuthToken() || undefined;
    const url = `${getApiBaseUrl()}/api/user/onboarding`;
    const requestPayload = { ...payload, token };

    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: this.getAuthHeaders(),
        body: JSON.stringify(requestPayload),
        credentials: 'include',
      });

      if (response.ok) {
        const res = await response.json();
        if (res && res.userProfile) {
          if (cached) {
            cached.userProfile = res.userProfile;
            cached.userPreferences = res.userPreferences;
            this.saveCachedSession(cached);
          }
          return res;
        }
      } else {
        console.warn(`REST Onboarding update returned ${response.status}, attempting WS fallback`);
      }
    } catch (e) {
      console.warn('REST Onboarding update network error, trying WS fallback', e);
    }

    // WebSocket fallback
    try {
      const res = await wsClient.sendRequest('auth:onboarding', requestPayload);
      if (res && res.userProfile) {
        if (cached) {
          cached.userProfile = res.userProfile;
          cached.userPreferences = res.userPreferences;
          this.saveCachedSession(cached);
        }
        return res;
      }
    } catch (wsErr) {
      console.warn('WS Onboarding fallback error', wsErr);
    }

    throw new Error('Could not save your preferences. Please check your connection and try again.');
  },
};

export const registerUser = async (data: RegisterPayload) => {
  return authService.register(data);
};
