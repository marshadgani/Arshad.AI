import { renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useFetch } from './useFetch';

describe('useFetch skip option', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ data: { hello: 'world' } }),
    });
    global.fetch = fetchMock as unknown as typeof fetch;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('skip=true returns the null/false/null triple and fires zero fetches', () => {
    const { result } = renderHook(() => useFetch('/api/v1/whoop/hrv-trend', { skip: true }));

    expect(result.current).toEqual({
      data: null,
      isLoading: false,
      error: null,
      refetch: expect.any(Function),
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('skip=false fetches normally', async () => {
    const { result } = renderHook(() => useFetch('/api/v1/whoop/hrv-trend', { skip: false }));

    expect(fetchMock).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.data).toEqual({ hello: 'world' });
    expect(result.current.error).toBeNull();
  });

  it('toggling skip true->false triggers a fresh fetch', async () => {
    const { result, rerender } = renderHook(
      ({ skip }) => useFetch('/api/v1/whoop/hrv-trend', { skip }),
      { initialProps: { skip: true } },
    );

    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.current).toEqual({
      data: null,
      isLoading: false,
      error: null,
      refetch: expect.any(Function),
    });

    rerender({ skip: false });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.data).toEqual({ hello: 'world' });
  });

  it('toggling skip false->true aborts the in-flight request and resets to the null triple', async () => {
    let resolveFetch: (value: unknown) => void = () => {};
    fetchMock.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveFetch = resolve;
        }),
    );

    const { result, rerender } = renderHook(
      ({ skip }) => useFetch('/api/v1/whoop/hrv-trend', { skip }),
      { initialProps: { skip: false } },
    );

    expect(fetchMock).toHaveBeenCalledTimes(1);

    rerender({ skip: true });

    expect(result.current).toEqual({
      data: null,
      isLoading: false,
      error: null,
      refetch: expect.any(Function),
    });

    // Resolving the now-aborted original fetch must not resurrect stale state.
    resolveFetch({
      ok: true,
      status: 200,
      json: async () => ({ data: { hello: 'stale' } }),
    });
    await Promise.resolve();
    expect(result.current).toEqual({
      data: null,
      isLoading: false,
      error: null,
      refetch: expect.any(Function),
    });
  });
});
