import { backendOrigin } from '../env';
import type { OAuthProvider } from './providers';

/**
 * Where the browser must navigate to begin an OAuth login.
 *
 * Must be an ABSOLUTE backend URL, not a relative path. A relative path
 * resolves against the frontend's own origin, and on Vercel that origin
 * proxies /api/* server-side (see frontend/vercel.json) — the browser
 * never navigates to the backend for this leg, so the SEC-002 CSRF cookie
 * backend/src/auth/routers.py sets during this call lands on the
 * frontend's origin instead of the backend's. The OAuth provider then
 * redirects straight to the backend for the callback, which never sees
 * that cookie and rejects with "OAuth state does not match this browser
 * session." (FEAT-142).
 *
 * Falls back to a relative path when VITE_BACKEND_URL is unset (local dev
 * / docker-compose share one origin via the dev proxy, so a relative path
 * is already correct there).
 *
 * Kept as a pure string function, separate from the navigation itself, so
 * the origin rule above is testable without stubbing `window.location`.
 */
export function loginUrl(provider: OAuthProvider): string {
  return `${backendOrigin()}/api/v1/auth/${provider}/login`;
}

/**
 * Performs the login handoff as a top-level navigation (NOT fetch) — fetch
 * cannot follow the cross-origin redirect to the provider's consent page;
 * the browser must own the URL bar.
 */
export function navigateToLogin(provider: OAuthProvider): void {
  window.location.href = loginUrl(provider);
}
