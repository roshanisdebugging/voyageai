import React from 'react';
import { useAuth } from './AuthContext';
import { Navigate, useLocation } from 'react-router-dom';
import { RefreshCw } from 'lucide-react';

export const AuthGuard: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { isAuthenticated, userProfile, isLoading } = useAuth();
  const location = useLocation();

  if (isLoading) {
    return (
      <div className="min-h-dvh bg-[#080B10] text-slate-100 flex flex-col items-center justify-center p-6 space-y-4">
        <RefreshCw className="w-8 h-8 text-teal-400 animate-spin" />
        <p className="text-sm font-bold text-white">Restoring your Cruiser session...</p>
      </div>
    );
  }

  // Case 1: Unauthenticated -> Redirect to Login
  if (!isAuthenticated) {
    if (location.pathname !== '/login') {
      return <Navigate to="/login" replace />;
    }
    return <>{children}</>;
  }

  // Case 2: Authenticated but Onboarding Incomplete -> Redirect to Onboarding
  const onboardingStatus = userProfile?.onboardingStatus || 'NOT_STARTED';
  const isCompleteOrSkipped = onboardingStatus === 'COMPLETED' || onboardingStatus === 'SKIPPED';

  if (!isCompleteOrSkipped) {
    if (location.pathname !== '/onboarding') {
      return <Navigate to="/onboarding" replace />;
    }
    return <>{children}</>;
  }

  // Case 3: Authenticated & Onboarded -> Don't allow visiting /login or /onboarding unnecessarily
  if (location.pathname === '/login' || location.pathname === '/onboarding') {
    return <Navigate to="/" replace />;
  }

  return <>{children}</>;
};
