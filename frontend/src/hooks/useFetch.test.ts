import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { useFetch } from './useFetch';

const mockFetch = vi.fn();

beforeEach(() => {
  vi.stubGlobal('fetch', mockFetch);
  localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('useFetch', () => {
  it('returns data on successful fetch', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ data: { id: '1', name: 'test' } }),
    });

    const { result } = renderHook(() => useFetch('/api/v1/test'));

    expect(result.current.isLoading).toBe(true);
    expect(result.current.data).toBeNull();

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.data).toEqual({ id: '1', name: 'test' });
    expect(result.current.error).toBeNull();
  });

  it('sets error on non-ok response', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
      statusText: 'Internal Server Error',
      text: async () => 'Something went wrong',
    });

    const { result } = renderHook(() => useFetch('/api/v1/test'));

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.data).toBeNull();
    expect(result.current.error).toBeInstanceOf(Error);
    expect(result.current.error?.message).toContain('500');
  });

  it('clears token and sets error on 401 response', async () => {
    localStorage.setItem('arshad.ai:jwt', 'some-token');
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 401,
      statusText: 'Unauthorized',
    });

    const { result } = renderHook(() => useFetch('/api/v1/secure'));

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(localStorage.getItem('arshad.ai:jwt')).toBeNull();
    expect(result.current.error?.message).toContain('401');
  });

  it('prepends API_BASE to relative URLs', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ data: [] }),
    });

    renderHook(() => useFetch('/api/v1/items'));

    await waitFor(() => expect(mockFetch).toHaveBeenCalledOnce());
    const [calledUrl] = mockFetch.mock.calls[0];
    // In test env VITE_API_BASE_URL is not set → API_BASE is '' → URL is unchanged
    expect(calledUrl).toBe('/api/v1/items');
  });

  it('uses absolute URL as-is', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ data: 'ok' }),
    });

    renderHook(() => useFetch('https://external.example.com/data'));

    await waitFor(() => expect(mockFetch).toHaveBeenCalledOnce());
    const [calledUrl] = mockFetch.mock.calls[0];
    expect(calledUrl).toBe('https://external.example.com/data');
  });
});
