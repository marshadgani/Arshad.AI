import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

import { clearToken, getToken, setToken } from './tokenStorage';

export type AuthUser = {
  id: string;
  email: string;
  name: string | null;
  avatarUrl: string | null;
};

type AuthState = {
  token: string | null;
  user: AuthUser | null;
  isLoading: boolean;
  loginWith: (provider: 'google' | 'github') => void;
  logout: () => Promise<void>;
  setTokenFromCallback: (token: string) => void;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setTokenState] = useState<string | null>(() => getToken());
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(Boolean(token));

  useEffect(() => {
    if (!token) {
      setUser(null);
      setIsLoading(false);
      return;
    }
    const controller = new AbortController();
    let active = true;
    setIsLoading(true);
    fetch('/api/v1/auth/me', {
      headers: { Authorization: `Bearer ${token}` },
      signal: controller.signal,
    })
      .then(async (res) => {
        if (!active) return;
        if (!res.ok) {
          clearToken();
          setTokenState(null);
          setUser(null);
          return;
        }
        const body = await res.json();
        if (active) setUser(body.data as AuthUser);
      })
      .catch((err) => {
        if (err?.name === 'AbortError') return;
        if (!active) return;
        clearToken();
        setTokenState(null);
        setUser(null);
      })
      .finally(() => {
        if (active) setIsLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [token]);

  const loginWith = useCallback((provider: 'google' | 'github') => {
    window.location.href = `/api/v1/auth/${provider}/login`;
  }, []);

  const logout = useCallback(async () => {
    try {
      await fetch('/api/v1/auth/logout', { method: 'POST' });
    } catch {
      // server-side noop — ignore network errors
    }
    clearToken();
    setTokenState(null);
    setUser(null);
  }, []);

  const setTokenFromCallback = useCallback((nextToken: string) => {
    setToken(nextToken);
    setTokenState(nextToken);
  }, []);

  const value = useMemo<AuthState>(
    () => ({ token, user, isLoading, loginWith, logout, setTokenFromCallback }),
    [token, user, isLoading, loginWith, logout, setTokenFromCallback],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within an AuthProvider');
  return ctx;
}
