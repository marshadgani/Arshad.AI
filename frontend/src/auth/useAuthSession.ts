import { useCallback, useEffect, useState } from 'react';

import { clearToken, getToken, setToken } from './tokenStorage';

export type AuthUser = {
  id: string;
  email: string;
  name: string | null;
  avatarUrl: string | null;
};

export type AuthSession = {
  token: string | null;
  user: AuthUser | null;
  isLoading: boolean;
  /** Adopt a freshly issued JWT (the OAuth callback's token fragment). */
  adoptToken: (token: string) => void;
  /** Drop the JWT and the resolved user — used by logout and by any 401. */
  endSession: () => void;
};

/**
 * Owns ONE concern: the identity the app currently holds — the persisted
 * JWT, the user it resolves to, and whether that resolution is in flight.
 *
 * Split out of AuthContext so the session lifecycle can be reasoned about
 * (and tested) without a provider tree, and so AuthContext is left doing
 * only what a context should: distributing this state plus the login /
 * logout commands. The hook deliberately knows nothing about OAuth
 * providers or redirect URLs — that is `loginUrl.ts`'s concern.
 */
export function useAuthSession(): AuthSession {
  const [token, setTokenState] = useState<string | null>(() => getToken());
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(Boolean(token));

  const endSession = useCallback(() => {
    clearToken();
    setTokenState(null);
    setUser(null);
  }, []);

  const adoptToken = useCallback((nextToken: string) => {
    setToken(nextToken);
    setTokenState(nextToken);
  }, []);

  useEffect(() => {
    if (!token) {
      setUser(null);
      setIsLoading(false);
      return;
    }
    const controller = new AbortController();
    // `active` guards against a late resolution writing state for a token
    // that is no longer current; abort() alone cannot cover the already-
    // resolved-but-not-yet-run continuation.
    let active = true;
    setIsLoading(true);
    fetch('/api/v1/auth/me', {
      headers: { Authorization: `Bearer ${token}` },
      signal: controller.signal,
    })
      .then(async (res) => {
        if (!active) return;
        if (!res.ok) {
          endSession();
          return;
        }
        const body = await res.json();
        if (active) setUser(body.data as AuthUser);
      })
      .catch((err) => {
        if (err?.name === 'AbortError') return;
        if (!active) return;
        endSession();
      })
      .finally(() => {
        if (active) setIsLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [token, endSession]);

  return { token, user, isLoading, adoptToken, endSession };
}
