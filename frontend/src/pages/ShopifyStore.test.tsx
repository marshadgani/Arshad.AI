/**
 * ShopifyStore page — five-state routing contract.
 *
 * The page is a pure state router. It decides which of five states to render;
 * it does not own any markup beyond the outer wrapper div. Each test verifies
 * that exactly one state is on screen for a given hook result.
 *
 * The documented `error && !dashboard` guard is tested explicitly: an error
 * during a background poll (when dashboard is already populated) must not
 * replace the live data with the error panel.
 *
 * Queries are by role and text, never by CSS class, per
 * .claude/rules/frontend.md.
 */

import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { ShopifyDashboard } from '../types/shopify';
import ShopifyStore from './ShopifyStore';

vi.mock('../hooks/useShopifyDashboard');
vi.mock('../utils/shopifyFormat', async (importOriginal) => {
  const real = await importOriginal<typeof import('../utils/shopifyFormat')>();
  return real;
});

import { useShopifyDashboard } from '../hooks/useShopifyDashboard';

const mockUseShopifyDashboard = vi.mocked(useShopifyDashboard);

afterEach(() => {
  vi.restoreAllMocks();
});

function connectedDashboard(overrides: Partial<ShopifyDashboard> = {}): ShopifyDashboard {
  return {
    connected: true,
    needs_reauth: false,
    shop_name: 'Test Store',
    currency_code: 'USD',
    timezone: 'UTC',
    cached_at: null,
    revenue_amount: '999.00',
    order_count: 10,
    order_count_approximate: false,
    truncated: false,
    conversion_rate_status: 'ok',
    average_order_value: '99.90',
    low_stock_sku_count: 0,
    recent_orders: [],
    partial_failures: [],
    ...overrides,
  };
}

describe('ShopifyStore', () => {
  it('shows the loading skeleton on first fetch with no data yet', () => {
    mockUseShopifyDashboard.mockReturnValue({
      dashboard: null,
      isLoading: true,
      error: null,
    });

    render(<ShopifyStore />);

    expect(screen.getByRole('status')).toHaveTextContent(/loading shopify dashboard/i);
    expect(screen.getByLabelText(/loading shopify data/i)).toBeInTheDocument();
  });

  it('shows the Shopify Store heading even in the loading state', () => {
    mockUseShopifyDashboard.mockReturnValue({
      dashboard: null,
      isLoading: true,
      error: null,
    });

    render(<ShopifyStore />);

    expect(screen.getByRole('heading', { name: 'Shopify Store' })).toBeInTheDocument();
  });

  it('shows the error panel when the first fetch fails and there is no data', () => {
    mockUseShopifyDashboard.mockReturnValue({
      dashboard: null,
      isLoading: false,
      error: new Error('network error'),
    });

    render(<ShopifyStore />);

    expect(screen.getByRole('alert')).toHaveTextContent(/failed to load shopify data/i);
    expect(screen.queryByLabelText(/loading shopify data/i)).toBeNull();
  });

  it('keeps showing live data when a background poll errors — the error && !dashboard guard', () => {
    // An error occurs during a 120s background poll but dashboard is already populated.
    // The page must NOT replace live data with the error panel.
    mockUseShopifyDashboard.mockReturnValue({
      dashboard: connectedDashboard(),
      isLoading: false,
      error: new Error('refresh failed'),
    });

    render(<ShopifyStore />);

    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.getByRole('group', { name: "Today's Revenue" })).toBeInTheDocument();
  });

  it('shows the connect notice when the store is not connected', () => {
    mockUseShopifyDashboard.mockReturnValue({
      dashboard: { connected: false, needs_reauth: false, recent_orders: [], partial_failures: [] },
      isLoading: false,
      error: null,
    });

    render(<ShopifyStore />);

    expect(screen.getByRole('heading', { name: 'Connect Shopify' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Connect Shopify' })).toHaveAttribute(
      'href',
      '/integrations',
    );
  });

  it('shows the reconnect notice when needs_reauth is true', () => {
    mockUseShopifyDashboard.mockReturnValue({
      dashboard: connectedDashboard({ needs_reauth: true }),
      isLoading: false,
      error: null,
    });

    render(<ShopifyStore />);

    expect(screen.getByRole('heading', { name: 'Reconnect Shopify' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Reconnect Shopify' })).toHaveAttribute(
      'href',
      '/integrations',
    );
  });

  it('renders the KPI grid and the Live badge when connected with data', () => {
    mockUseShopifyDashboard.mockReturnValue({
      dashboard: connectedDashboard(),
      isLoading: false,
      error: null,
    });

    render(<ShopifyStore />);

    expect(screen.getByRole('group', { name: "Today's Revenue" })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Orders Today' })).toBeInTheDocument();
    expect(screen.getByText('Live')).toBeInTheDocument();
  });

  it('does not show the loading skeleton once data is on screen', () => {
    mockUseShopifyDashboard.mockReturnValue({
      dashboard: connectedDashboard(),
      isLoading: false,
      error: null,
    });

    render(<ShopifyStore />);

    expect(screen.queryByLabelText(/loading shopify data/i)).toBeNull();
  });

  it('does not show a stale label when cached_at is null', () => {
    mockUseShopifyDashboard.mockReturnValue({
      dashboard: connectedDashboard({ cached_at: null }),
      isLoading: false,
      error: null,
    });

    render(<ShopifyStore />);

    expect(screen.queryByRole('status')).toBeNull();
  });

  it('shows a stale label when cached_at is provided', () => {
    const now = new Date('2026-09-11T12:00:00.000Z').getTime();
    vi.spyOn(Date, 'now').mockReturnValue(now);

    mockUseShopifyDashboard.mockReturnValue({
      dashboard: connectedDashboard({
        cached_at: new Date(now - 5 * 60_000).toISOString(),
      }),
      isLoading: false,
      error: null,
    });

    render(<ShopifyStore />);

    expect(screen.getByRole('status')).toHaveTextContent(/updated 5m ago/i);
  });

  it('shows the shop subtitle in the page header when connected', () => {
    mockUseShopifyDashboard.mockReturnValue({
      dashboard: connectedDashboard({ shop_name: 'My Shop', timezone: 'Europe/London' }),
      isLoading: false,
      error: null,
    });

    render(<ShopifyStore />);

    expect(screen.getByText(/My Shop/)).toBeInTheDocument();
    expect(screen.getByText(/Europe\/London/)).toBeInTheDocument();
  });
});
