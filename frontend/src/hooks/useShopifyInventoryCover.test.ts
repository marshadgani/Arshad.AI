/**
 * useShopifyInventoryCover — useFetch delegation contract.
 *
 * The hook is a thin wrapper over useFetch. Its only responsibilities are:
 * 1. Calling the /inventory-cover endpoint.
 * 2. Passing a 120-second poll interval (matching backend cache TTL).
 * 3. Re-exposing data as `inventory` (not `data`) and refetch as `refresh`.
 */

import { renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { useShopifyInventoryCover } from './useShopifyInventoryCover';

vi.mock('./useFetch');

import { useFetch } from './useFetch';

const mockUseFetch = vi.mocked(useFetch);

afterEach(() => {
  vi.restoreAllMocks();
});

describe('useShopifyInventoryCover', () => {
  it('calls the inventory-cover endpoint', () => {
    mockUseFetch.mockReturnValue({ data: null, isLoading: true, error: null, refetch: vi.fn() });

    renderHook(() => useShopifyInventoryCover());

    expect(mockUseFetch).toHaveBeenCalledWith(
      '/api/v1/shopify/inventory-cover',
      expect.anything(),
    );
  });

  it('passes a 120-second poll interval matching the backend cache TTL', () => {
    mockUseFetch.mockReturnValue({ data: null, isLoading: true, error: null, refetch: vi.fn() });

    renderHook(() => useShopifyInventoryCover());

    expect(mockUseFetch).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({ refreshInterval: 120_000 }),
    );
  });

  it('exposes useFetch data as inventory', () => {
    const fakeInventory = {
      connected: true,
      needs_reauth: false,
      days_of_cover: [],
      alerts: [],
      variants_truncated: false,
      orders_truncated: false,
      calendar_connected: true,
      calendar_needs_reauth: false,
      partial_failures: [],
    };
    mockUseFetch.mockReturnValue({ data: fakeInventory, isLoading: false, error: null, refetch: vi.fn() });

    const { result } = renderHook(() => useShopifyInventoryCover());

    expect(result.current.inventory).toBe(fakeInventory);
  });

  it('reports null for inventory before the first fetch resolves', () => {
    mockUseFetch.mockReturnValue({ data: null, isLoading: true, error: null, refetch: vi.fn() });

    const { result } = renderHook(() => useShopifyInventoryCover());

    expect(result.current.inventory).toBeNull();
    expect(result.current.isLoading).toBe(true);
  });

  it('propagates a fetch error', () => {
    const err = new Error('network failure');
    mockUseFetch.mockReturnValue({ data: null, isLoading: false, error: err, refetch: vi.fn() });

    const { result } = renderHook(() => useShopifyInventoryCover());

    expect(result.current.error).toBe(err);
    expect(result.current.inventory).toBeNull();
  });

  it('exposes refetch as refresh', () => {
    const refetch = vi.fn();
    mockUseFetch.mockReturnValue({ data: null, isLoading: false, error: null, refetch });

    const { result } = renderHook(() => useShopifyInventoryCover());

    result.current.refresh();
    expect(refetch).toHaveBeenCalledOnce();
  });
});
