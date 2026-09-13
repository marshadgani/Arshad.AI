/**
 * Unit tests for api/auth.ts — fetchCurrentUser and requestLogout.
 *
 * These are new in this changeset alongside the OAuth-login fix and were
 * previously untested: AuthContext.test.tsx stubs global.fetch to return 401,
 * but with no token in localStorage the mount-time effect never calls
 * fetchCurrentUser, so that mock never actually executes. These tests
 * exercise the module directly instead.
 *
 * Coverage: happy path, the 401/403 branch AuthContext relies on to decide
 * whether to sign a user out, and the res.ok check that stops a failed
 * logout from looking identical to a successful one.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';

import { AuthRequestError, fetchCurrentUser, requestLogout } from './auth';

afterEach(() => {
  vi.restoreAllMocks();
});

describe('fetchCurrentUser', () => {
  it('resolves with the user on a 200 response, unwrapping { data }', async () => {
    const user = { id: 'u1', email: 'a@b.com', name: 'A', avatarUrl: null };
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ data: user }), { status: 200 }),
    );

    await expect(fetchCurrentUser('tok')).resolves.toEqual(user);
  });

  it('sends the bearer token in the Authorization header', async () => {
    const fetchSpy = vi
      .spyOn(global, 'fetch')
      .mockResolvedValue(new Response(JSON.stringify({ data: {} }), { status: 200 }));

    await fetchCurrentUser('my-token');

    expect(fetchSpy).toHaveBeenCalledWith(
      '/api/v1/auth/me',
      expect.objectContaining({ headers: { Authorization: 'Bearer my-token' } }),
    );
  });

  it('rejects with AuthRequestError carrying status 401 on an unauthorized response', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ error: { code: 'invalid_token' } }), { status: 401 }),
    );

    const err = await fetchCurrentUser('bad-token').catch((e) => e);
    expect(err).toBeInstanceOf(AuthRequestError);
    expect((err as AuthRequestError).status).toBe(401);
  });

  it('rejects with AuthRequestError carrying status 500 on a server error (distinct from 401/403)', async () => {
    // AuthContext only signs the user out for 401/403; this pins the status
    // it must be able to tell apart from that case.
    vi.spyOn(global, 'fetch').mockResolvedValue(new Response('', { status: 500 }));

    const err = await fetchCurrentUser('tok').catch((e) => e);
    expect(err).toBeInstanceOf(AuthRequestError);
    expect((err as AuthRequestError).status).toBe(500);
  });

  it('propagates the AbortSignal so the request can be cancelled', async () => {
    const fetchSpy = vi
      .spyOn(global, 'fetch')
      .mockResolvedValue(new Response(JSON.stringify({ data: {} }), { status: 200 }));
    const controller = new AbortController();

    await fetchCurrentUser('tok', controller.signal);

    expect(fetchSpy).toHaveBeenCalledWith(
      '/api/v1/auth/me',
      expect.objectContaining({ signal: controller.signal }),
    );
  });
});

describe('requestLogout', () => {
  it('resolves without throwing on a 200 response', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(new Response(null, { status: 200 }));

    await expect(requestLogout()).resolves.toBeUndefined();
  });

  it('POSTs to /api/v1/auth/logout', async () => {
    const fetchSpy = vi
      .spyOn(global, 'fetch')
      .mockResolvedValue(new Response(null, { status: 200 }));

    await requestLogout();

    expect(fetchSpy).toHaveBeenCalledWith('/api/v1/auth/logout', { method: 'POST' });
  });

  it('throws AuthRequestError on a non-ok response instead of resolving silently', async () => {
    // Without the res.ok check, fetch resolving normally on an HTTP error
    // status would make a failed server-side logout indistinguishable from
    // a successful one.
    vi.spyOn(global, 'fetch').mockResolvedValue(new Response(null, { status: 500 }));

    const err = await requestLogout().catch((e) => e);
    expect(err).toBeInstanceOf(AuthRequestError);
    expect((err as AuthRequestError).status).toBe(500);
  });
});
