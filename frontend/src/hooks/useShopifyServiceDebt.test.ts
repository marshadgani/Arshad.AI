/**
 * useShopifyServiceDebt — useFetch delegation contract.
 *
 * The hook is a thin wrapper over useFetch. Its only responsibilities are:
 * 1. Calling the /service-debt endpoint.
 * 2. Passing a 120-second poll interval (matching backend cache TTL).
 * 3. Re-exposing data as `serviceDebt` (not `data`) and refetch as `refresh`.
 */

import { renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { useShopifyServiceDebt } from './useShopifyServiceDebt';

vi.mock('./useFetch');

import { useFetch } from './useFetch';

const mockUseFetch = vi.mocked(useFetch);

afterEach(() => {
  vi.restoreAllMocks();
});

describe('useShopifyServiceDebt', () => {
  it('calls the service-debt endpoint', () => {
    mockUseFetch.mockReturnValue({ data: null, isLoading: true, error: null, refetch: vi.fn() });

    renderHook(() => useShopifyServiceDebt());

    expect(mockUseFetch).toHaveBeenCalledWith(
      '/api/v1/shopify/service-debt',
      expect.anything(),
    );
  });

  it('passes a 120-second poll interval matching the backend cache TTL', () => {
    mockUseFetch.mockReturnValue({ data: null, isLoading: true, error: null, refetch: vi.fn() });

    renderHook(() => useShopifyServiceDebt());

    expect(mockUseFetch).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({ refreshInterval: 120_000 }),
    );
  });

  it('exposes useFetch data as serviceDebt', () => {
    const fakeDebt = {
      gmail_connected: true,
      shopify_connected: true,
      needs_reauth: false,
      threads: [],
      threads_truncated: false,
      orders_truncated: false,
      partial_failures: [],
    };
    mockUseFetch.mockReturnValue({ data: fakeDebt, isLoading: false, error: null, refetch: vi.fn() });

    const { result } = renderHook(() => useShopifyServiceDebt());

    expect(result.current.serviceDebt).toBe(fakeDebt);
  });

  it('reports null for serviceDebt before the first fetch resolves', () => {
    mockUseFetch.mockReturnValue({ data: null, isLoading: true, error: null, refetch: vi.fn() });

    const { result } = renderHook(() => useShopifyServiceDebt());

    expect(result.current.serviceDebt).toBeNull();
    expect(result.current.isLoading).toBe(true);
  });

  it('propagates a fetch error', () => {
    const err = new Error('upstream failure');
    mockUseFetch.mockReturnValue({ data: null, isLoading: false, error: err, refetch: vi.fn() });

    const { result } = renderHook(() => useShopifyServiceDebt());

    expect(result.current.error).toBe(err);
    expect(result.current.serviceDebt).toBeNull();
  });

  it('exposes refetch as refresh', () => {
    const refetch = vi.fn();
    mockUseFetch.mockReturnValue({ data: null, isLoading: false, error: null, refetch });

    const { result } = renderHook(() => useShopifyServiceDebt());

    result.current.refresh();
    expect(refetch).toHaveBeenCalledOnce();
  });
});
