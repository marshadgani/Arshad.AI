import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { usePaginatedFetch } from './usePaginatedFetch';

describe('usePaginatedFetch', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ data: [{ id: 1 }], total: 42 }),
    });
    global.fetch = fetchMock as unknown as typeof fetch;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('unwraps the { data, total } envelope', async () => {
    const { result } = renderHook(() => usePaginatedFetch('/api/v1/ai-ecosystem/skills'));

    expect(result.current.isLoading).toBe(true);
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.data).toEqual([{ id: 1 }]);
    expect(result.current.total).toBe(42);
    expect(result.current.error).toBeNull();
  });

  it('surfaces a non-2xx response as an error', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 500,
      statusText: 'Internal Server Error',
      text: async () => 'boom',
    });

    const { result } = renderHook(() => usePaginatedFetch('/api/v1/ai-ecosystem/skills'));

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.error).toBeInstanceOf(Error);
    expect(result.current.error?.message).toContain('500');
    expect(result.current.data).toEqual([]);
  });

  it('refetch() re-runs the request without changing the url', async () => {
    const { result } = renderHook(() => usePaginatedFetch('/api/v1/ai-ecosystem/skills'));

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(fetchMock).toHaveBeenCalledTimes(1);

    act(() => result.current.refetch());

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  });

  it('a failed request can recover via refetch() once the endpoint succeeds', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 503,
      statusText: 'Service Unavailable',
      text: async () => 'down',
    });

    const { result } = renderHook(() => usePaginatedFetch('/api/v1/ai-ecosystem/skills'));

    await waitFor(() => expect(result.current.error).not.toBeNull());

    act(() => result.current.refetch());

    await waitFor(() => expect(result.current.error).toBeNull());
    expect(result.current.data).toEqual([{ id: 1 }]);
    expect(result.current.total).toBe(42);
  });
});
