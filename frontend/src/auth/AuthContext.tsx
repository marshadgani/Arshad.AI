import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

import {
  AuthRequestError,
  fetchCurrentUser,
  loginWithPassword as apiLoginWithPassword,
  requestLogout,
} from '../api/auth';
import { oauthLoginUrl } from './oauthLoginUrl';
import { clearToken, getToken, setToken } from './tokenStorage';
import type { AuthState, AuthUser, OAuthProvider } from './types';

export type { AuthUser, AuthState } from './types';

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setTokenState] = useState<string | null>(() => getToken());
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(Boolean(token));

  const forgetSession = useCallback(() => {
    clearToken();
    setTokenState(null);
    setUser(null);
  }, []);

  useEffect(() => {
    if (!token) {
      setUser(null);
      setIsLoading(false);
      return;
    }
    const controller = new AbortController();
    let active = true;
    setIsLoading(true);
    fetchCurrentUser(token, controller.signal)
      .then((nextUser) => {
        if (active) setUser(nextUser);
      })
      .catch((err) => {
        if (err?.name === 'AbortError') return;
        if (!active) return;
        // Only a server-confirmed 401/403 proves the token is invalid. Any
        // other failure (network, 5xx, malformed body) leaves validity
        // unknown, so the session is kept rather than logging the user out
        // over a transient blip.
        const status = err instanceof AuthRequestError ? err.status : undefined;
        if (status === 401 || status === 403) {
          console.error('Auth session rejected by server, signing out', err);
          forgetSession();
          return;
        }
        console.error('Failed to load the authenticated user', err);
      })
      .finally(() => {
        if (active) setIsLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [token, forgetSession]);

  const loginWith = useCallback((provider: OAuthProvider) => {
    // Top-level navigation to the backend's ABSOLUTE origin: a relative URL is
    // proxied by Vercel, scoping the oauth_login_nonce cookie to the frontend
    // domain while the provider's callback goes straight to the backend domain,
    // so the nonce is never sent back and every login fails with invalid_state.
    window.location.href = oauthLoginUrl(provider);
  }, []);

  const logout = useCallback(async () => {
    try {
      await requestLogout();
    } catch (err) {
      // The local session is cleared regardless (a broken logout button must
      // not strand the user signed in), but a server-side token left
      // un-revoked is a real gap and must not vanish unlogged.
      console.error('Server-side logout request failed; clearing local session anyway', err);
    }
    forgetSession();
  }, [forgetSession]);

  const setTokenFromCallback = useCallback((nextToken: string) => {
    setToken(nextToken);
    setTokenState(nextToken);
  }, []);

  const loginWithPassword = useCallback(
    async (email: string, password: string) => {
      const nextToken = await apiLoginWithPassword(email, password);
      setTokenFromCallback(nextToken);
    },
    [setTokenFromCallback],
  );

  const value = useMemo<AuthState>(
    () => ({
      token,
      user,
      isLoading,
      loginWith,
      loginWithPassword,
      logout,
      setTokenFromCallback,
    }),
    [token, user, isLoading, loginWith, loginWithPassword, logout, setTokenFromCallback],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within an AuthProvider');
  return ctx;
}
