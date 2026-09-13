/**
 * useFinanceHoldings — syncAll behaviour.
 *
 * useFetch is mocked so these tests own only the sync half of the hook:
 * which brokers are POSTed to, what happens on a partial failure, and that
 * a refetch always follows. The GET/envelope half is covered by
 * useFetch.test.ts and by BrokerageHoldings' wire-level test.
 */

import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { BrokerHoldings, FinanceHoldingsResponse } from '../types/finance';

vi.mock('./useFetch');

import { useFetch } from './useFetch';
import { useFinanceHoldings } from './useFinanceHoldings';

const mockUseFetch = vi.mocked(useFetch);

function broker(overrides: Partial<BrokerHoldings> = {}): BrokerHoldings {
  return {
    broker: 'upstox',
    display_name: 'Upstox (India)',
    status: 'connected',
    needs_reauth: false,
    currency: 'INR',
    holding_count: 0,
    truncated: false,
    holdings: [],
    last_synced_at: null,
    error: null,
    ...overrides,
  };
}

function mockData(data: FinanceHoldingsResponse | null, refetch = vi.fn()) {
  mockUseFetch.mockReturnValue({ data, isLoading: false, error: null, refetch });
  return refetch;
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 200 }));
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe('useFinanceHoldings.syncAll', () => {
  it('POSTs to the sync endpoint for every connected broker and refetches', async () => {
    const refetch = mockData(
      {
        connected: true,
        brokers: [broker(), broker({ broker: 'zerodha_kite' })],
      },
      vi.fn(),
    );

    const { result } = renderHook(() => useFinanceHoldings());
    act(() => result.current.syncAll());

    await waitFor(() => expect(refetch).toHaveBeenCalledTimes(1));

    const calls = vi.mocked(fetch).mock.calls.map((c) => c[0]);
    expect(calls).toEqual([
      '/api/v1/integrations/upstox/sync',
      '/api/v1/integrations/zerodha_kite/sync',
    ]);
    expect(result.current.syncError).toBeNull();
    expect(result.current.isSyncing).toBe(false);
  });

  it('skips a broker that needs reauth rather than sending a doomed request', async () => {
    const refetch = mockData({
      connected: true,
      brokers: [
        broker({ needs_reauth: true, status: 'expired' }),
        broker({ broker: 'zerodha_kite' }),
      ],
    });

    const { result } = renderHook(() => useFinanceHoldings());
    act(() => result.current.syncAll());

    await waitFor(() => expect(refetch).toHaveBeenCalled());
    expect(vi.mocked(fetch).mock.calls.map((c) => c[0])).toEqual([
      '/api/v1/integrations/zerodha_kite/sync',
    ]);
  });

  it('explains itself instead of no-opping when every broker needs reauth', () => {
    mockData({
      connected: true,
      brokers: [broker({ needs_reauth: true, status: 'expired' })],
    });

    const { result } = renderHook(() => useFinanceHoldings());
    act(() => result.current.syncAll());

    expect(fetch).not.toHaveBeenCalled();
    expect(result.current.syncError?.message).toBe('Reconnect your broker before syncing.');
  });

  it('reports a partial failure but still refetches', async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce({ ok: true, status: 200 } as Response)
      .mockResolvedValueOnce({ ok: false, status: 502, statusText: 'Bad Gateway' } as Response);

    const refetch = mockData({
      connected: true,
      brokers: [broker(), broker({ broker: 'zerodha_kite' })],
    });

    const { result } = renderHook(() => useFinanceHoldings());
    act(() => result.current.syncAll());

    await waitFor(() =>
      expect(result.current.syncError?.message).toBe('One or more brokers failed to sync.'),
    );
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it('does nothing when no broker is connected', () => {
    mockData({ connected: false, brokers: [] });

    const { result } = renderHook(() => useFinanceHoldings());
    act(() => result.current.syncAll());

    expect(fetch).not.toHaveBeenCalled();
  });
});
