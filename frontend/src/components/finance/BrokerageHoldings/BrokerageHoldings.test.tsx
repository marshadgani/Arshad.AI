/**
 * BrokerageHoldings — state routing + a wire-level envelope regression.
 *
 * Most cases mock useFinanceHoldings directly (fast, focused on markup).
 * One case ("wire test") deliberately does NOT mock the hook — it mocks
 * global fetch and renders through the real useFinanceHoldings/useFetch
 * stack, so an envelope mismatch between the backend's {"data": {...}}
 * response and useFetch's `body.data` unwrap would actually fail here,
 * not just in a hook-level mock that assumes the shape is already right.
 *
 * Queries are by role/text only, never by CSS class or test id, per
 * .claude/rules/frontend.md.
 */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { FinanceHoldingsResponse } from '../../../types/finance';
import { BrokerageHoldings } from './BrokerageHoldings';

vi.mock('../../../hooks/useFinanceHoldings');

import { useFinanceHoldings } from '../../../hooks/useFinanceHoldings';

const mockUseFinanceHoldings = vi.mocked(useFinanceHoldings);

function baseHookResult(overrides: Partial<ReturnType<typeof useFinanceHoldings>> = {}) {
  return {
    data: null,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
    syncAll: vi.fn(),
    isSyncing: false,
    syncError: null,
    ...overrides,
  };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe('BrokerageHoldings (mocked hook)', () => {
  it('shows the disconnected notice with a link to /integrations', () => {
    mockUseFinanceHoldings.mockReturnValue(
      baseHookResult({ data: { connected: false, brokers: [] } }),
    );

    render(<BrokerageHoldings />);

    expect(screen.getByText('No brokerage account connected')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Connect a broker' })).toHaveAttribute(
      'href',
      '/integrations',
    );
  });

  it('renders one broker with its display name and a holding symbol', () => {
    mockUseFinanceHoldings.mockReturnValue(
      baseHookResult({
        data: {
          connected: true,
          brokers: [
            {
              broker: 'upstox',
              display_name: 'Upstox (India)',
              status: 'connected',
              needs_reauth: false,
              currency: 'INR',
              holding_count: 1,
              truncated: false,
              holdings: [{ symbol: 'TCS', qty: 10, ltp: 3500, pnl: null, value: 35000 }],
              last_synced_at: null,
              error: null,
            },
          ],
        },
      }),
    );

    render(<BrokerageHoldings />);

    expect(screen.getByText('Upstox (India)')).toBeInTheDocument();
    expect(screen.getByText('TCS')).toBeInTheDocument();
  });

  it('renders two cards when both brokers are connected', () => {
    mockUseFinanceHoldings.mockReturnValue(
      baseHookResult({
        data: {
          connected: true,
          brokers: [
            {
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
            },
            {
              broker: 'zerodha_kite',
              display_name: 'Zerodha Kite (India)',
              status: 'connected',
              needs_reauth: false,
              currency: 'INR',
              holding_count: 0,
              truncated: false,
              holdings: [],
              last_synced_at: null,
              error: null,
            },
          ],
        },
      }),
    );

    render(<BrokerageHoldings />);

    expect(screen.getByRole('heading', { name: 'Upstox (India)' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Zerodha Kite (India)' })).toBeInTheDocument();
  });

  it('shows a reconnect notice for a broker that needs reauth while another still renders its table', () => {
    mockUseFinanceHoldings.mockReturnValue(
      baseHookResult({
        data: {
          connected: true,
          brokers: [
            {
              broker: 'upstox',
              display_name: 'Upstox (India)',
              status: 'expired',
              needs_reauth: true,
              currency: 'INR',
              holding_count: 0,
              truncated: false,
              holdings: [],
              last_synced_at: null,
              error: null,
            },
            {
              broker: 'zerodha_kite',
              display_name: 'Zerodha Kite (India)',
              status: 'connected',
              needs_reauth: false,
              currency: 'INR',
              holding_count: 1,
              truncated: false,
              holdings: [{ symbol: 'RELIANCE', qty: 1, ltp: 2400, pnl: 10, value: 2400 }],
              last_synced_at: null,
              error: null,
            },
          ],
        },
      }),
    );

    render(<BrokerageHoldings />);

    expect(screen.getByText('Reconnect Upstox (India)')).toBeInTheDocument();
    expect(screen.getByText('RELIANCE')).toBeInTheDocument();
  });

  it('renders a dash, never the string NaN, for a null ltp', () => {
    mockUseFinanceHoldings.mockReturnValue(
      baseHookResult({
        data: {
          connected: true,
          brokers: [
            {
              broker: 'upstox',
              display_name: 'Upstox (India)',
              status: 'connected',
              needs_reauth: false,
              currency: 'INR',
              holding_count: 1,
              truncated: false,
              holdings: [{ symbol: 'TCS', qty: 10, ltp: null, pnl: null, value: null }],
              last_synced_at: null,
              error: null,
            },
          ],
        },
      }),
    );

    render(<BrokerageHoldings />);

    expect(screen.queryByText(/NaN/)).not.toBeInTheDocument();
    expect(screen.getAllByLabelText('no data').length).toBeGreaterThan(0);
  });

  it('shows the truncated caption when holding_count exceeds the returned rows', () => {
    mockUseFinanceHoldings.mockReturnValue(
      baseHookResult({
        data: {
          connected: true,
          brokers: [
            {
              broker: 'upstox',
              display_name: 'Upstox (India)',
              status: 'connected',
              needs_reauth: false,
              currency: 'INR',
              holding_count: 42,
              truncated: true,
              holdings: Array.from({ length: 10 }, (_, i) => ({
                symbol: `S${i}`,
                qty: 1,
                ltp: 1,
                pnl: null,
                value: 1,
              })),
              last_synced_at: null,
              error: null,
            },
          ],
        },
      }),
    );

    render(<BrokerageHoldings />);

    expect(screen.getByText('Showing top 10 of 42 holdings')).toBeInTheDocument();
  });

  it('keeps the last good holdings on screen when the broker last sync failed', () => {
    mockUseFinanceHoldings.mockReturnValue(
      baseHookResult({
        data: {
          connected: true,
          brokers: [
            {
              broker: 'zerodha_kite',
              display_name: 'Zerodha Kite (India)',
              status: 'error',
              needs_reauth: false,
              currency: 'INR',
              holding_count: 1,
              truncated: false,
              holdings: [{ symbol: 'RELIANCE', qty: 1, ltp: 2400, pnl: 10, value: 2400 }],
              last_synced_at: null,
              // Raw upstream exception text as stored in last_error.
              error: "HTTPStatusError: Server error '502 Bad Gateway' for url 'https://api.kite.trade/portfolio/holdings'",
            },
          ],
        },
      }),
    );

    render(<BrokerageHoldings />);

    expect(screen.getByText('RELIANCE')).toBeInTheDocument();
    expect(
      screen.getByText('Last sync failed — showing the most recent data we have.'),
    ).toBeInTheDocument();
    // The raw upstream URL/exception class must never reach the UI.
    expect(screen.queryByText(/api\.kite\.trade/)).not.toBeInTheDocument();
    expect(screen.queryByText(/HTTPStatusError/)).not.toBeInTheDocument();
  });
});

describe('BrokerageHoldings interactions', () => {
  const connectedBroker = {
    broker: 'upstox',
    display_name: 'Upstox (India)',
    status: 'connected' as const,
    needs_reauth: false,
    currency: 'INR',
    holding_count: 0,
    truncated: false,
    holdings: [],
    last_synced_at: null,
    error: null,
  };

  it('calls syncAll when Sync now is pressed', async () => {
    const syncAll = vi.fn();
    mockUseFinanceHoldings.mockReturnValue(
      baseHookResult({ data: { connected: true, brokers: [connectedBroker] }, syncAll }),
    );

    render(<BrokerageHoldings />);
    await userEvent.click(screen.getByRole('button', { name: 'Sync now' }));

    expect(syncAll).toHaveBeenCalledTimes(1);
  });

  it('disables the sync button and shows progress while syncing', () => {
    mockUseFinanceHoldings.mockReturnValue(
      baseHookResult({
        data: { connected: true, brokers: [connectedBroker] },
        isSyncing: true,
      }),
    );

    render(<BrokerageHoldings />);

    expect(screen.getByRole('button', { name: 'Syncing…' })).toBeDisabled();
  });

  it('surfaces a sync error message', () => {
    mockUseFinanceHoldings.mockReturnValue(
      baseHookResult({
        data: { connected: true, brokers: [connectedBroker] },
        syncError: new Error('One or more brokers failed to sync.'),
      }),
    );

    render(<BrokerageHoldings />);

    expect(screen.getByText('One or more brokers failed to sync.')).toBeInTheDocument();
  });

  it('calls refetch when Retry is pressed on the error state', async () => {
    const refetch = vi.fn();
    mockUseFinanceHoldings.mockReturnValue(
      baseHookResult({ error: new Error('boom'), refetch }),
    );

    render(<BrokerageHoldings />);
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));

    expect(refetch).toHaveBeenCalledTimes(1);
  });
});

describe('BrokerageHoldings (wire-level, real useFetch)', () => {
  it('unwraps the {"data": {...}} envelope through the real fetch stack', async () => {
    vi.doUnmock('../../../hooks/useFinanceHoldings');
    vi.resetModules();

    const body: { data: FinanceHoldingsResponse } = {
      data: {
        connected: true,
        brokers: [
          {
            broker: 'upstox',
            display_name: 'Upstox (India)',
            status: 'connected',
            needs_reauth: false,
            currency: 'INR',
            holding_count: 1,
            truncated: false,
            holdings: [{ symbol: 'TCS', qty: 10, ltp: 3500, pnl: null, value: 35000 }],
            last_synced_at: null,
            error: null,
          },
        ],
      },
    };

    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        status: 200,
        ok: true,
        json: () => Promise.resolve(body),
      }),
    );

    const { BrokerageHoldings: RealBrokerageHoldings } = await import('./BrokerageHoldings');

    render(<RealBrokerageHoldings />);

    await waitFor(() => expect(screen.getByText('TCS')).toBeInTheDocument());

    vi.unstubAllGlobals();
  });
});
