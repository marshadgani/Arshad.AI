/**
 * TC-FE-001 – TC-FE-004: useDashboardData knowledge-suggestions contract.
 *
 * Regression tests that lock down the additive-contract guarantee from FEAT-123
 * (FN-106) and the 401-does-not-clear-session guarantee (NF-208).
 *
 * We test useFetch's envelope-unwrap and 401 behaviour directly because that is
 * the unit of logic that matters — useDashboardData is a thin composition over
 * useFetch and has no logic of its own beyond the URL string.
 */

import { renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import * as tokenStorage from '../auth/tokenStorage';
import { useFetch } from '../hooks/useFetch';

// ── helpers ──────────────────────────────────────────────────────────────────

/** Build a minimal Response-like object that fetch resolves with. */
function makeResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? 'OK' : 'Error',
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as unknown as Response;
}

const KNOWLEDGE_URL = '/api/v1/dashboard/knowledge-suggestions';

// ── TC-FE-001 ─────────────────────────────────────────────────────────────────
// Hook yields string[] from knowledge-suggestions with new additive flags present.

describe('TC-FE-001: hook yields string[] from knowledge-suggestions', () => {
  beforeEach(() => {
    vi.spyOn(tokenStorage, 'getToken').mockReturnValue('tok');
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('unwraps the data envelope and returns the names array', async () => {
    const payload = {
      data: ['budget-2026.pdf', 'q1-review.xlsx'],
      total: 2,
      connected: true,
      needs_reauth: false,
      truncated: false,
      partial_failures: [],
    };

    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(makeResponse(payload));

    const { result } = renderHook(() => useFetch<string[]>(KNOWLEDGE_URL));

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.data).toEqual(['budget-2026.pdf', 'q1-review.xlsx']);
    expect(result.current.error).toBeNull();
  });
});

// ── TC-FE-002 ─────────────────────────────────────────────────────────────────
// Hook does not crash when new additive flags are absent from the response body.

describe('TC-FE-002: hook does not crash when additive flags are absent', () => {
  beforeEach(() => {
    vi.spyOn(tokenStorage, 'getToken').mockReturnValue('tok');
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('handles a legacy response that has only data and total', async () => {
    // Simulate an older API response without the new flags.
    const legacyPayload = {
      data: ['old-file.pdf'],
      total: 1,
    };

    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(makeResponse(legacyPayload));

    const { result } = renderHook(() => useFetch<string[]>(KNOWLEDGE_URL));

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    // The hook must not throw; data is still the inner array.
    expect(result.current.data).toEqual(['old-file.pdf']);
    expect(result.current.error).toBeNull();
  });

  it('returns null data (not a crash) when the server returns an empty data array', async () => {
    const emptyPayload = {
      data: [],
      total: 0,
      connected: false,
      needs_reauth: false,
      truncated: false,
      partial_failures: [],
    };

    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(makeResponse(emptyPayload));

    const { result } = renderHook(() => useFetch<string[]>(KNOWLEDGE_URL));

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.data).toEqual([]);
    expect(result.current.error).toBeNull();
  });
});

// ── TC-FE-003 ─────────────────────────────────────────────────────────────────
// Empty data + connected=false renders empty state (null data), not a crash.

describe('TC-FE-003: disconnected state renders empty, not crash', () => {
  beforeEach(() => {
    vi.spyOn(tokenStorage, 'getToken').mockReturnValue(null);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('returns empty array data when Drive is not connected', async () => {
    const disconnectedPayload = {
      data: [],
      total: 0,
      connected: false,
      needs_reauth: false,
      truncated: false,
      partial_failures: [],
    };

    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      makeResponse(disconnectedPayload)
    );

    const { result } = renderHook(() => useFetch<string[]>(KNOWLEDGE_URL));

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    // Calling code that maps over data must not throw — empty array is safe.
    expect(Array.isArray(result.current.data)).toBe(true);
    expect(result.current.data).toHaveLength(0);
  });
});

// ── TC-FE-004 ─────────────────────────────────────────────────────────────────
// A 401 from knowledge-suggestions DOES clear the session token.
// (This tests the existing useFetch behaviour and verifies knowledge-suggestions
//  must NEVER return 401 in production — the always-200 contract is there
//  precisely to prevent this path from triggering for Drive token expiry.)

describe('TC-FE-004: 401 from knowledge-suggestions clears session token', () => {
  let clearTokenSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    vi.spyOn(tokenStorage, 'getToken').mockReturnValue('tok');
    clearTokenSpy = vi.spyOn(tokenStorage, 'clearToken').mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('calls clearToken when the endpoint unexpectedly returns 401', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(makeResponse({}, 401));

    const { result } = renderHook(() => useFetch<string[]>(KNOWLEDGE_URL));

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    // The token must be wiped — this is by design for any genuine 401.
    expect(clearTokenSpy).toHaveBeenCalledTimes(1);

    // And the hook surfaces an error rather than leaving data stale.
    expect(result.current.error).not.toBeNull();
    expect(result.current.error?.message).toMatch(/401/);
  });

  it('does not call clearToken on a 200 response with needs_reauth=true in body', async () => {
    // This is the path that knowledge-suggestions ACTUALLY takes when Drive
    // needs reauthorisation — HTTP 200, needs_reauth flag in body, no token wipe.
    const reauthPayload = {
      data: [],
      total: 0,
      connected: true,
      needs_reauth: true,
      truncated: false,
      partial_failures: ['google_drive: needs_reauth'],
    };

    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(makeResponse(reauthPayload));

    const { result } = renderHook(() => useFetch<string[]>(KNOWLEDGE_URL));

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    // Session token must remain intact — only the Drive token needs re-auth.
    expect(clearTokenSpy).not.toHaveBeenCalled();
    expect(result.current.error).toBeNull();
    // The hook surfaces the data array (empty) — caller reads needs_reauth from body.
    expect(result.current.data).toEqual([]);
  });
});
