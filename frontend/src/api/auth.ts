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
