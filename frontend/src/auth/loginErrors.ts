/**
 * Backend login error codes → copy a human can act on.
 *
 * Codes come from the `oauth_login_state_rejected` / `login_unavailable`
 * family in `backend/src/auth/routers.py`. Kept out of the Login component
 * so the mapping can be extended (or localised) without touching JSX, and
 * so adding a backend error code is a one-line change in one file.
 */

const ERROR_MESSAGES: Record<string, string> = {
  invalid_state:
    'Your sign-in session expired, or this link was opened in a different tab. Please try again.',
  login_unavailable: 'Sign-in is temporarily unavailable. Please try again in a moment.',
  provider_error: 'The sign-in provider returned an error. Please try again.',
};

const DEFAULT_ERROR_MESSAGE = 'Something went wrong signing you in. Please try again.';

export function loginErrorMessage(code: string | null): string | null {
  if (!code) return null;
  return ERROR_MESSAGES[code] ?? DEFAULT_ERROR_MESSAGE;
}

/**
 * Reads the error code from the URL's query string — not router state — so
 * it also works if a future backend change 302s straight to
 * `/login?error=<code>` instead of rendering raw JSON at the callback URL
 * (see FEAT-142; today AuthCallback is the only frontend source of this
 * param, forwarded from its own failure branch).
 */
export function readLoginErrorCode(): string | null {
  if (typeof window === 'undefined') return null;
  return new URLSearchParams(window.location.search).get('error');
}
