/**
 * Client for the session endpoints under /api/v1/auth.
 *
 * These stay RELATIVE, unlike the OAuth login navigation in
 * auth/oauthLoginUrl.ts: they are XHRs carrying a bearer token, so the
 * cookie-scope constraint that forces the login redirect onto the backend's
 * absolute origin does not apply.
 */

import type { AuthUser } from '../auth/types';

const AUTH_BASE = '/api/v1/auth';

/**
 * Carries the HTTP status so callers can tell "the server rejected this
 * token" (401/403) apart from "the request failed for some other reason"
 * (network, 5xx, malformed body). AuthContext signs the user out only for
 * the former.
 */
export class AuthRequestError extends Error {
  constructor(
    message: string,
    public readonly status?: number,
  ) {
    super(message);
    this.name = 'AuthRequestError';
  }
}

export async function fetchCurrentUser(token: string, signal?: AbortSignal): Promise<AuthUser> {
  const res = await fetch(`${AUTH_BASE}/me`, {
    headers: { Authorization: `Bearer ${token}` },
    signal,
  });
  if (!res.ok) {
    throw new AuthRequestError(`GET ${AUTH_BASE}/me responded ${res.status}`, res.status);
  }
  const body = await res.json();
  return body.data as AuthUser;
}

// fetch resolves normally on an HTTP error status, so without the res.ok
// check a failed server-side logout would look identical to a successful one.
export async function requestLogout(): Promise<void> {
  const res = await fetch(`${AUTH_BASE}/logout`, { method: 'POST' });
  if (!res.ok) {
    throw new AuthRequestError(`POST ${AUTH_BASE}/logout responded ${res.status}`, res.status);
  }
}

/**
 * Deliberately raw `fetch`, NOT the `useFetch` hook used elsewhere in this
 * codebase. `useFetch` treats ANY 401 response as an Arshad.AI session
 * expiry and calls `clearToken()` — routing a password login through it
 * would mean a WRONG PASSWORD triggers an app-wide sign-out of whatever
 * session the browser already held. This is a real, non-obvious trap: a
 * future "tidy this up" refactor that swaps this for `useFetch` looks
 * correct and is not. Do not make that change.
 */
export async function loginWithPassword(email: string, password: string): Promise<string> {
  const res = await fetch(`${AUTH_BASE}/password/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    let message = `POST ${AUTH_BASE}/password/login responded ${res.status}`;
    try {
      const body = await res.json();
      if (body?.error?.message) message = body.error.message;
    } catch {
      // Non-JSON error body — fall back to the generic message above.
    }
    throw new AuthRequestError(message, res.status);
  }
  const body = await res.json();
  return body.data.token as string;
}
