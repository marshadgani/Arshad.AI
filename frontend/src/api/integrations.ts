/**
 * Client for POST /api/v1/integrations/{slug}/connect.
 *
 * The connect call was hand-rolled in two places — the Integrations page
 * and AppleHealthCard — each repeating the auth header, the JSON body, the
 * `{ error: { message } }` unwrap, and the reading of `data.ingest_token`.
 * Two copies of one contract is how the Apple Health one-time token gets
 * delivered correctly on one screen and dropped on the other.
 *
 * ConnectResponse mirrors ConnectResult in backend/src/integrations/base.py,
 * including its invariant: a provider hands back a redirect_url (OAuth) or
 * an ingest_token (push-style, e.g. Apple Health), never both. The backend
 * makes the illegal combination unconstructible; this type documents it on
 * the client so callers branch on one or the other rather than inventing a
 * third possibility.
 *
 * The ingest token is a one-time-display secret: it is returned to the
 * caller for immediate display and must never be logged, stored, or put in
 * a URL. Nothing here persists it.
 */

import { getToken } from '../auth/tokenStorage';

export interface ConnectResponse {
  integration_id: string | null;
  /** Present for OAuth providers — navigate the browser here. */
  redirect_url: string | null;
  /** Present for push providers — show once, never store. */
  ingest_token: string | null;
}

/**
 * Carries the API envelope's machine-readable `error.code` alongside the
 * human message, so a caller that needs to special-case one failure (e.g.
 * Shopify's `invalid_hmac`) can do it without re-reading the response body
 * itself — which is what forced that caller to keep its own copy of this
 * whole function.
 */
export class ConnectError extends Error {
  readonly code: string | null;

  constructor(message: string, code: string | null) {
    super(message);
    this.name = 'ConnectError';
    this.code = code;
  }
}

/**
 * POST /api/v1/integrations/{slug}/sync — ask the backend to re-run a
 * provider's sync() now. Resolves on success, rejects on any non-2xx.
 *
 * Extracted from useFinanceHoldings so that hook holds sync *state* only
 * and no longer carries a second, divergent copy of the auth-header and
 * response-check rules this module already owns.
 *
 * Two deliberate differences from connectIntegration above, both
 * preserving the behaviour this call already had:
 *  - the Authorization header is omitted entirely when no token is
 *    stored, rather than sent as a literal `Bearer null`;
 *  - the response body is never read. Sync failures surface as a status
 *    code; a rejection here must not depend on the error envelope being
 *    parseable, and must never clear the session token — only useFetch's
 *    401 handling owns that path.
 */
export async function syncIntegration(slug: string): Promise<void> {
  const token = getToken();
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (token) headers.Authorization = `Bearer ${token}`;

  // Encoded, not interpolated raw: `slug` is server-supplied today, but a
  // path segment built by concatenation is one upstream change away from
  // traversing to a different endpoint ('../disconnect').
  const res = await fetch(`/api/v1/integrations/${encodeURIComponent(slug)}/sync`, {
    method: 'POST',
    headers,
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
}

export async function connectIntegration(
  slug: string,
  payload: Record<string, unknown> = {},
): Promise<ConnectResponse> {
  const res = await fetch(`/api/v1/integrations/${slug}/connect`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${getToken()}`,
    },
    body: JSON.stringify(payload),
  });
  const body = await res.json();
  if (!res.ok) {
    throw new ConnectError(
      body?.error?.message ?? `HTTP ${res.status}`,
      (body?.error?.code as string | undefined) ?? null,
    );
  }
  return {
    integration_id: (body?.data?.integration_id as string | null) ?? null,
    redirect_url: (body?.data?.redirect_url as string | null) ?? null,
    ingest_token: (body?.data?.ingest_token as string | null) ?? null,
  };
}
