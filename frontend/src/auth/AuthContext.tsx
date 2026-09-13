import { createContext, useCallback, useContext, useMemo, type ReactNode } from 'react';

import { navigateToLogin } from './loginUrl';
import { OAUTH_PROVIDERS, type OAuthProvider } from './providers';
import { useAuthSession, type AuthUser } from './useAuthSession';

/**
 * Distributes the auth session and the two commands that change it.
 *
 * Everything substantive lives one level down and is independently
 * testable — `useAuthSession` (token + /me lifecycle) and `loginUrl`
 * (the absolute-backend-origin rule that FEAT-142 turned on). This file
 * is deliberately thin: it exists to put that state on the React tree,
 * not to implement it.
 */

// Re-exported so existing call sites (TopBar, Login, AuthCallback) keep a
// single import point while the underlying modules stay decoupled.
export { OAUTH_PROVIDERS };
export type { AuthUser, OAuthProvider };

type AuthState = {
  token: string | null;
  user: AuthUser | null;
  isLoading: boolean;
  loginWith: (provider: OAuthProvider) => void;
  logout: () => Promise<void>;
  setTokenFromCallback: (token: string) => void;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const { token, user, isLoading, adoptToken, endSession } = useAuthSession();

  const loginWith = useCallback((provider: OAuthProvider) => {
    navigateToLogin(provider);
  }, []);

  const logout = useCallback(async () => {
    try {
      await fetch('/api/v1/auth/logout', { method: 'POST' });
    } catch {
      // server-side noop — ignore network errors
    }
    endSession();
  }, [endSession]);

  const value = useMemo<AuthState>(
    () => ({
      token,
      user,
      isLoading,
      loginWith,
      logout,
      setTokenFromCallback: adoptToken,
    }),
    [token, user, isLoading, loginWith, logout, adoptToken],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within an AuthProvider');
  return ctx;
}
