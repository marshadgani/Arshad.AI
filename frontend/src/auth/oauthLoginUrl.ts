/**
 * Where the OAuth login navigation points.
 *
 * The whole module exists to guarantee one thing: the login URL is always an
 * ABSOLUTE backend origin, never a relative path. A relative path is proxied
 * by Vercel, which scopes the backend's oauth_login_nonce cookie to the
 * frontend domain — while the provider's callback goes straight to the
 * backend domain, so the nonce never comes back and login fails with
 * invalid_state.
 */

import type { OAuthProvider } from './types';

// Absolute in dev too, rather than leaning on vite.config.ts's /api dev proxy
// for a top-level navigation.
export const DEV_BACKEND_ORIGIN = 'http://localhost:8000';

const MISSING_ORIGIN_MESSAGE =
  'VITE_API_BASE_URL must be set to the backend origin (e.g. https://arshad-ai.onrender.com) ' +
  'for OAuth login to work; the login nonce cookie must be scoped to the backend domain the ' +
  'provider callback targets.';

const INSECURE_ORIGIN_MESSAGE =
  'VITE_API_BASE_URL must use https in production; an http backend origin would send the ' +
  'login nonce cookie and the returned JWT over an unencrypted connection.';

/**
 * Read at call time (not module load) so it stays stubbable in tests and the
 * prod guard stays reachable. In production an unset value throws
 * diagnosably rather than silently reproducing the cookie-scope bug.
 */
export function resolveBackendOrigin(): string {
  const base = (import.meta.env.VITE_API_BASE_URL ?? '').trim();
  if (base) {
    // Plaintext http in prod would strip Secure from the backend's
    // oauth_login_nonce cookie and carry the returned JWT over the wire in
    // clear, so a misconfigured scheme must fail loudly, not downgrade.
    if (import.meta.env.PROD && !/^https:\/\//i.test(base)) {
      throw new Error(INSECURE_ORIGIN_MESSAGE);
    }
    return base;
  }
  if (import.meta.env.PROD) {
    throw new Error(MISSING_ORIGIN_MESSAGE);
  }
  return DEV_BACKEND_ORIGIN;
}

/**
 * Pure builder: normalises a trailing slash off baseUrl, rejects an empty one,
 * and rejects anything that is not an absolute http(s) URL.
 *
 * The result is assigned straight to window.location.href, so a non-http(s)
 * value would be navigated as a pseudo-scheme (javascript:, data:) rather than
 * as the backend origin — and a scheme-less value is the relative path this
 * module exists to prevent.
 */
export function buildOAuthLoginUrl(provider: OAuthProvider, baseUrl: string): string {
  const normalized = baseUrl.trim().replace(/\/+$/, '');
  if (!normalized) {
    throw new Error('buildOAuthLoginUrl requires a non-empty baseUrl');
  }
  let parsed: URL;
  try {
    parsed = new URL(normalized);
  } catch {
    throw new Error(
      `buildOAuthLoginUrl requires an absolute http(s) backend origin, got '${normalized}'`,
    );
  }
  if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') {
    throw new Error(
      `buildOAuthLoginUrl requires an absolute http(s) backend origin, got '${normalized}'`,
    );
  }
  return `${normalized}/api/v1/auth/${provider}/login`;
}

export function oauthLoginUrl(provider: OAuthProvider): string {
  return buildOAuthLoginUrl(provider, resolveBackendOrigin());
}
