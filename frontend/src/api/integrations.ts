/**
 * Client for the /api/v1/integrations/{slug}/* calls.
 *
 * These were hand-rolled at each call site — the Integrations page and
 * AppleHealthCard — each repeating the auth header, the JSON body, and the
 * `{ error: { message } }` unwrap. Two copies of one contract is how the
 * Apple Health one-time token gets delivered correctly on one screen and
 * dropped on the other.
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

/** Shape of this API's envelope — success (`data`) or failure (`error`),
 * per .claude/rules/api.md. Both are optional because a non-JSON body
 * (see parseJsonBody below) parses to `{}`, matching neither. */
interface ApiEnvelope {
  data?: Record<string, unknown>;
  error?: { message?: string; code?: string };
}

/**
 * Carries the envelope's machine-readable `error.code` alongside the human
 * message, so a caller that needs to special-case one failure (e.g.
 * Shopify's `invalid_hmac`) can do it without re-reading the response body
 * itself — which is what forced callers to keep their own copy of this
 * whole module.
 */
export class IntegrationApiError extends Error {
  readonly code: string | null;

  constructor(message: string, code: string | null) {
    super(message);
    this.name = 'IntegrationApiError';
    this.code = code;
  }
}

/**
 * Parse a response body as JSON, tolerating a body that isn't JSON at all —
 * an infra-layer 502/503/504 (Render, a proxy, a load balancer) returns an
 * HTML or plain-text error page, not the `{error: {...}}` envelope this API
 * always sends. Calling `res.json()` unconditionally on that response
 * throws a `SyntaxError` ("Unexpected token '<'…") that replaces the real,
 * useful signal — the HTTP status — with a parser error the user cannot
 * act on. Falling back to `{}` here lets the thrown error still carry an
 * actionable `HTTP ${res.status}` message.
 */
async function parseJsonBody(res: Response): Promise<ApiEnvelope> {
  try {
    return (await res.json()) as ApiEnvelope;
  } catch {
    return {};
  }
}

/** POST to an integrations endpoint and return its `data` envelope,
 * throwing IntegrationApiError on any non-ok response. */
async function post(path: string, payload?: Record<string, unknown>) {
  const res = await fetch(`/api/v1/integrations/${path}`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${getToken()}`,
      ...(payload ? { 'Content-Type': 'application/json' } : {}),
    },
    body: payload ? JSON.stringify(payload) : undefined,
  });
  const body = await parseJsonBody(res);
  if (!res.ok) {
    throw new IntegrationApiError(
      body?.error?.message ?? `HTTP ${res.status}`,
      body?.error?.code ?? null,
    );
  }
  return body?.data ?? {};
}

export interface ConnectResponse {
  integration_id: string | null;
  /** Present for OAuth providers — navigate the browser here. */
  redirect_url: string | null;
  /** Present for push providers — show once, never store. */
  ingest_token: string | null;
}

export async function connectIntegration(
  slug: string,
  payload: Record<string, unknown> = {},
): Promise<ConnectResponse> {
  const data = await post(`${slug}/connect`, payload);
  return {
    integration_id: (data.integration_id as string | null) ?? null,
    redirect_url: (data.redirect_url as string | null) ?? null,
    ingest_token: (data.ingest_token as string | null) ?? null,
  };
}

export type DisconnectStatus = 'disconnected' | 'already_disconnected';

/**
 * Client for POST /api/v1/integrations/{slug}/disconnect
 * (backend/src/integrations/routers.py). A failed local-credential-deletion
 * transaction (base.py's disconnect() rolls back and re-raises rather than
 * leaving the integration half-disconnected) surfaces here as a thrown
 * IntegrationApiError, so the UI can show the real reason instead of a bare
 * "HTTP 500".
 */
export async function disconnectIntegration(slug: string): Promise<DisconnectStatus> {
  const data = await post(`${slug}/disconnect`);
  return (data.status as DisconnectStatus | undefined) ?? 'disconnected';
}
