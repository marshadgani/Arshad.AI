/**
 * The OAuth providers the backend exposes login/callback routes for
 * (`backend/src/auth/routers.py` → `/api/v1/auth/{provider}/login|callback`,
 * registered in `backend/src/auth/providers/registry.py`).
 *
 * Single source of truth: the auth context, the login page, and any future
 * call site import this instead of re-typing the `'google' | 'github'`
 * union, so they cannot drift apart or away from the backend routes.
 *
 * Type-only module by design — it carries no React and no browser API, so
 * importing it can never pull a component tree or `window` into a test.
 */
export const OAUTH_PROVIDERS = ['google', 'github'] as const;

export type OAuthProvider = (typeof OAUTH_PROVIDERS)[number];
