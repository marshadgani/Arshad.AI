/**
 * ShopifyKpiGrid + ShopifyKpiGridSkeleton — KPI mapping and skeleton contract.
 *
 * The grid owns the mapping from wire fields to card props. Tests here verify
 * that each KPI tile gets the right label and that the plan-gated state is
 * applied correctly. The skeleton must match the same four labels so it never
 * drifts from the live content and causes layout shift.
 */

import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { ShopifyDashboard } from '../../../types/shopify';
import { ShopifyKpiGrid, ShopifyKpiGridSkeleton } from './ShopifyKpiGrid';

function dashboard(overrides: Partial<ShopifyDashboard> = {}): ShopifyDashboard {
  return {
    connected: true,
    needs_reauth: false,
    shop_name: 'Test Store',
    currency_code: 'USD',
    timezone: 'UTC',
    cached_at: null,
    revenue_amount: '1234.56',
    order_count: 42,
    order_count_approximate: false,
    truncated: false,
    conversion_rate_status: 'ok',
    average_order_value: '29.37',
    low_stock_sku_count: 3,
    recent_orders: [],
    partial_failures: [],
    ...overrides,
  };
}

describe('ShopifyKpiGrid', () => {
  it('renders all four KPI card labels', () => {
    render(<ShopifyKpiGrid dashboard={dashboard()} />);

    expect(screen.getByRole('group', { name: "Today's Revenue" })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Orders Today' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Conversion Rate' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Low Stock SKUs' })).toBeInTheDocument();
  });

  it('shows the formatted revenue amount', () => {
    render(<ShopifyKpiGrid dashboard={dashboard({ revenue_amount: '1234.56' })} />);

    const revenueCard = screen.getByRole('group', { name: "Today's Revenue" });
    expect(within(revenueCard).getByText(/1[,.]?234/)).toBeInTheDocument();
  });

  it('shows the order count', () => {
    render(<ShopifyKpiGrid dashboard={dashboard({ order_count: 7 })} />);

    const ordersCard = screen.getByRole('group', { name: 'Orders Today' });
    expect(within(ordersCard).getByText('7')).toBeInTheDocument();
  });

  it('shows the "(approximate)" hint when order_count_approximate is true', () => {
    render(<ShopifyKpiGrid dashboard={dashboard({ order_count_approximate: true })} />);

    const ordersCard = screen.getByRole('group', { name: 'Orders Today' });
    expect(within(ordersCard).getByText('(approximate)')).toBeInTheDocument();
  });

  it('marks the conversion rate card as unavailable when conversion_rate_status is "unavailable"', () => {
    render(
      <ShopifyKpiGrid
        dashboard={dashboard({ conversion_rate_status: 'unavailable', average_order_value: null })}
      />,
    );

    const convCard = screen.getByRole('group', { name: 'Conversion Rate' });
    expect(within(convCard).getByText(/not available on this plan/i)).toBeInTheDocument();
  });

  it('shows the low stock SKU count', () => {
    render(<ShopifyKpiGrid dashboard={dashboard({ low_stock_sku_count: 5 })} />);

    const lowStockCard = screen.getByRole('group', { name: 'Low Stock SKUs' });
    expect(within(lowStockCard).getByText('5')).toBeInTheDocument();
  });

  it('marks the revenue card as unavailable when truncated is true', () => {
    // When truncated=true there are >250 orders and revenue cannot be summed.
    // kpiState(true, ...) returns 'unavailable', which renders the plan-gate
    // notice rather than a value or a hint (KpiCard suppresses hints on
    // 'unavailable' state).
    render(
      <ShopifyKpiGrid dashboard={dashboard({ truncated: true, revenue_amount: '99.00' })} />,
    );

    const revenueCard = screen.getByRole('group', { name: "Today's Revenue" });
    expect(within(revenueCard).getByText(/not available on this plan/i)).toBeInTheDocument();
  });

  it('passes the partial_failures error down to the orders card', () => {
    render(
      <ShopifyKpiGrid dashboard={dashboard({ partial_failures: ['orders_failed'] })} />,
    );

    expect(screen.getByRole('alert')).toHaveTextContent(/unable to load recent orders/i);
  });

  it('does not show an orders error when partial_failures is empty', () => {
    render(<ShopifyKpiGrid dashboard={dashboard({ partial_failures: [] })} />);

    expect(screen.queryByRole('alert')).toBeNull();
  });
});

describe('ShopifyKpiGridSkeleton', () => {
  it('is marked as busy for screen readers', () => {
    render(<ShopifyKpiGridSkeleton />);

    const grid = screen.getByLabelText(/loading shopify data/i);
    expect(grid).toHaveAttribute('aria-busy', 'true');
  });

  it('renders all four skeleton KPI cards with their labels', () => {
    render(<ShopifyKpiGridSkeleton />);

    expect(screen.getByRole('group', { name: "Today's Revenue" })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Orders Today' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Conversion Rate' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Low Stock SKUs' })).toBeInTheDocument();
  });

  it('marks every KPI card as loading', () => {
    render(<ShopifyKpiGridSkeleton />);

    const cards = screen.getAllByRole('group');
    cards.forEach((card) => {
      expect(card).toHaveAttribute('aria-busy', 'true');
    });
  });
});
