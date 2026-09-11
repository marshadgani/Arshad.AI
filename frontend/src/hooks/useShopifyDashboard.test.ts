/**
 * useShopifyDashboard — useFetch delegation contract.
 *
 * The hook is a thin wrapper over useFetch. Its only responsibilities are
 * calling the right endpoint, passing the correct poll interval, and
 * re-exposing data as `dashboard` (not `data`). Any deviation from those
 * three facts is a bug.
 */

import { renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { useShopifyDashboard } from './useShopifyDashboard';

// Mock useFetch at the module boundary so the hook can be tested in
// isolation without a real network or a running backend.
vi.mock('./useFetch');

import { useFetch } from './useFetch';

const mockUseFetch = vi.mocked(useFetch);

afterEach(() => {
  vi.restoreAllMocks();
});

describe('useShopifyDashboard', () => {
  it('calls the shopify dashboard endpoint', () => {
    mockUseFetch.mockReturnValue({ data: null, isLoading: true, error: null, refetch: vi.fn() });

    renderHook(() => useShopifyDashboard());

    expect(mockUseFetch).toHaveBeenCalledWith(
      '/api/v1/shopify/dashboard',
      expect.anything(),
    );
  });

  it('passes a 120-second poll interval matching the backend cache TTL', () => {
    mockUseFetch.mockReturnValue({ data: null, isLoading: true, error: null, refetch: vi.fn() });

    renderHook(() => useShopifyDashboard());

    expect(mockUseFetch).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({ refreshInterval: 120_000 }),
    );
  });

  it('exposes useFetch data as dashboard', () => {
    const fakeDashboard = {
      connected: true,
      needs_reauth: false,
      recent_orders: [],
      partial_failures: [],
    };
    mockUseFetch.mockReturnValue({ data: fakeDashboard, isLoading: false, error: null, refetch: vi.fn() });

    const { result } = renderHook(() => useShopifyDashboard());

    expect(result.current.dashboard).toBe(fakeDashboard);
  });

  it('reports null for dashboard before the first fetch resolves', () => {
    mockUseFetch.mockReturnValue({ data: null, isLoading: true, error: null, refetch: vi.fn() });

    const { result } = renderHook(() => useShopifyDashboard());

    expect(result.current.dashboard).toBeNull();
    expect(result.current.isLoading).toBe(true);
  });

  it('propagates a fetch error', () => {
    const err = new Error('network failure');
    mockUseFetch.mockReturnValue({ data: null, isLoading: false, error: err, refetch: vi.fn() });

    const { result } = renderHook(() => useShopifyDashboard());

    expect(result.current.error).toBe(err);
    expect(result.current.dashboard).toBeNull();
  });
});
