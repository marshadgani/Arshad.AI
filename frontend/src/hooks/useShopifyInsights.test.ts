/**
 * useShopifyInsights — useFetch delegation contract.
 *
 * Mirrors useShopifyDashboard.test.ts: the hook is a thin wrapper over
 * useFetch, mocked at the module boundary so no real network/backend is
 * needed.
 */

import { renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { useShopifyInsights } from './useShopifyInsights';

vi.mock('./useFetch');

import { useFetch } from './useFetch';

const mockUseFetch = vi.mocked(useFetch);

afterEach(() => {
  vi.restoreAllMocks();
});

describe('useShopifyInsights', () => {
  it('calls /api/v1/shopify/insights with days=14 by default', () => {
    mockUseFetch.mockReturnValue({ data: null, isLoading: true, error: null, refetch: vi.fn() });

    renderHook(() => useShopifyInsights());

    expect(mockUseFetch).toHaveBeenCalledWith(
      '/api/v1/shopify/insights?days=14',
      expect.objectContaining({ skip: false }),
    );
  });

  it('passes no refreshInterval', () => {
    mockUseFetch.mockReturnValue({ data: null, isLoading: true, error: null, refetch: vi.fn() });

    renderHook(() => useShopifyInsights());

    const [, options] = mockUseFetch.mock.calls[0];
    expect(options).not.toHaveProperty('refreshInterval');
  });

  it('changes the URL when days changes', () => {
    mockUseFetch.mockReturnValue({ data: null, isLoading: true, error: null, refetch: vi.fn() });

    renderHook(() => useShopifyInsights({ days: 30 }));

    expect(mockUseFetch).toHaveBeenCalledWith('/api/v1/shopify/insights?days=30', expect.anything());
  });

  it('forwards skip:true to useFetch', () => {
    mockUseFetch.mockReturnValue({ data: null, isLoading: false, error: null, refetch: vi.fn() });

    renderHook(() => useShopifyInsights({ skip: true }));

    expect(mockUseFetch).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({ skip: true }),
    );
  });

  it('exposes useFetch data as insights and re-exports refetch', () => {
    const refetch = vi.fn();
    const fakeInsights = { days: 14 } as any;
    mockUseFetch.mockReturnValue({ data: fakeInsights, isLoading: false, error: null, refetch });

    const { result } = renderHook(() => useShopifyInsights());

    expect(result.current.insights).toBe(fakeInsights);
    expect(result.current.refetch).toBe(refetch);
  });

  it('propagates a fetch error', () => {
    const err = new Error('boom');
    mockUseFetch.mockReturnValue({ data: null, isLoading: false, error: err, refetch: vi.fn() });

    const { result } = renderHook(() => useShopifyInsights());

    expect(result.current.error).toBe(err);
    expect(result.current.insights).toBeNull();
  });
});
