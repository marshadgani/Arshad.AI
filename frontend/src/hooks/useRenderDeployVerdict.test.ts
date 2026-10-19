import { renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { clearToken } from '../auth/tokenStorage';
import { useRenderDeployVerdict } from './useRenderDeployVerdict';

vi.mock('../auth/tokenStorage', () => ({
  clearToken: vi.fn(),
  getToken: () => 'tok',
}));

const DATA = {
  verdict: 'neutral',
  connected: true,
  needs_reauth: false,
  partial_failures: [],
  log_truncated: false,
  before_error_count: 1,
  after_error_count: 1,
  before_error_rate: 0.1,
  after_error_rate: 0.1,
};

function respond(status: number, body: unknown) {
  return vi.fn().mockResolvedValue({ ok: status < 400, status, json: async () => body });
}

beforeEach(() => vi.mocked(clearToken).mockClear());
afterEach(() => vi.unstubAllGlobals());

describe('useRenderDeployVerdict', () => {
  it('does not fetch without both ids', () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    const { result } = renderHook(() => useRenderDeployVerdict(null, 'dep-1'));
    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.current).toEqual({ data: null, isLoading: false, error: null });
  });

  it('fetches with encoded ids and bearer token and returns data', async () => {
    const fetchMock = respond(200, { data: DATA });
    vi.stubGlobal('fetch', fetchMock);
    const { result } = renderHook(() => useRenderDeployVerdict('srv-a/b', 'dep 1'));
    await waitFor(() => expect(result.current.data).toEqual(DATA));
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/v1/render/services/srv-a%2Fb/deploys/dep%201/verdict');
    expect(init.headers).toEqual({ Authorization: 'Bearer tok' });
  });

  it('clears the session token only on 401', async () => {
    vi.stubGlobal('fetch', respond(401, {}));
    const { result } = renderHook(() => useRenderDeployVerdict('srv-a', 'dep-1'));
    await waitFor(() => expect(result.current.error).not.toBeNull());
    expect(clearToken).toHaveBeenCalledTimes(1);
  });

  it('reports a rate-limit message on 429 without clearing the token', async () => {
    vi.stubGlobal('fetch', respond(429, {}));
    const { result } = renderHook(() => useRenderDeployVerdict('srv-a', 'dep-1'));
    await waitFor(() => expect(result.current.error?.message).toMatch(/too many/i));
    expect(clearToken).not.toHaveBeenCalled();
  });

  it('sets an error on 5xx and on an unrecognised verdict', async () => {
    vi.stubGlobal('fetch', respond(503, {}));
    const first = renderHook(() => useRenderDeployVerdict('srv-a', 'dep-1'));
    await waitFor(() => expect(first.result.current.error).not.toBeNull());

    vi.stubGlobal('fetch', respond(200, { data: { ...DATA, verdict: 'catastrophe' } }));
    const second = renderHook(() => useRenderDeployVerdict('srv-a', 'dep-2'));
    await waitFor(() => expect(second.result.current.error).not.toBeNull());
    expect(second.result.current.data).toBeNull();
  });

  it('aborts the in-flight request on unmount without setting an error', async () => {
    let signal: AbortSignal | undefined;
    vi.stubGlobal(
      'fetch',
      vi.fn((_url: string, init: RequestInit) => {
        signal = init.signal as AbortSignal;
        return new Promise(() => {});
      }),
    );
    const { unmount, result } = renderHook(() => useRenderDeployVerdict('srv-a', 'dep-1'));
    unmount();
    expect(signal?.aborted).toBe(true);
    expect(result.current.error).toBeNull();
  });

  it('clears stale data when the deploy changes', async () => {
    vi.stubGlobal('fetch', respond(200, { data: DATA }));
    const { result, rerender } = renderHook(({ d }) => useRenderDeployVerdict('srv-a', d), {
      initialProps: { d: 'dep-1' as string | null },
    });
    await waitFor(() => expect(result.current.data).not.toBeNull());
    rerender({ d: null });
    expect(result.current.data).toBeNull();
  });
});
