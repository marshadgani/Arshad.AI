/**
 * RecentOrdersCard — loading / error / empty / data rendering matrix.
 *
 * "No orders yet today" (a fact about the store) and "we could not reach the
 * orders endpoint" (a fact about the system) are different states that must
 * never share a rendering.
 *
 * Queries are by role and text, never by CSS class, per
 * .claude/rules/frontend.md.
 */

import { render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { ShopifyOrder } from '../../../types/shopify';
import { RecentOrdersCard } from './RecentOrdersCard';

function order(overrides: Partial<ShopifyOrder> = {}): ShopifyOrder {
  return {
    id: '1001',
    order_number: '#1001',
    customer_name: 'Alice Smith',
    item_count: 2,
    total_amount: '49.99',
    currency_code: 'USD',
    created_at: new Date().toISOString(),
    ...overrides,
  };
}

const ORDERS: ShopifyOrder[] = [
  order({ id: '1001', order_number: '#1001' }),
  order({ id: '1002', order_number: '#1002', customer_name: null }),
];

describe('RecentOrdersCard', () => {
  it('renders a loading skeleton that is hidden from assistive technology', () => {
    render(<RecentOrdersCard orders={[]} isLoading />);

    const hiddenList = document.querySelector('[aria-hidden="true"]');
    expect(hiddenList).toBeInTheDocument();
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.queryByText(/no orders yet/i)).toBeNull();
  });

  it('shows an error alert when the fetch failed and is not loading', () => {
    render(<RecentOrdersCard orders={[]} isLoading={false} error="Partial data" />);

    expect(screen.getByRole('alert')).toHaveTextContent(/unable to load recent orders/i);
  });

  it('does not show the error alert while still loading', () => {
    render(<RecentOrdersCard orders={[]} isLoading error="Partial data" />);

    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('shows the empty state when there are no orders and no error', () => {
    render(<RecentOrdersCard orders={[]} isLoading={false} />);

    expect(screen.getByText(/no orders yet today/i)).toBeInTheDocument();
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.queryByRole('list')).toBeNull();
  });

  it('renders one list item per order on the happy path', () => {
    render(<RecentOrdersCard orders={ORDERS} isLoading={false} />);

    const items = screen.getAllByRole('listitem');
    expect(items).toHaveLength(2);
  });

  it('shows the order number for each order', () => {
    render(<RecentOrdersCard orders={ORDERS} isLoading={false} />);

    expect(screen.getByText('#1001')).toBeInTheDocument();
    expect(screen.getByText('#1002')).toBeInTheDocument();
  });

  it('falls back to "Guest" when the customer name is null', () => {
    render(<RecentOrdersCard orders={[order({ customer_name: null })]} isLoading={false} />);

    expect(screen.getByText('Guest')).toBeInTheDocument();
  });

  it('pluralises item count correctly for a single item', () => {
    render(
      <RecentOrdersCard orders={[order({ item_count: 1 })]} isLoading={false} />,
    );

    expect(screen.getByText('1 item')).toBeInTheDocument();
  });

  it('pluralises item count correctly for multiple items', () => {
    render(
      <RecentOrdersCard orders={[order({ item_count: 3 })]} isLoading={false} />,
    );

    expect(screen.getByText('3 items')).toBeInTheDocument();
  });

  it('shows the formatted amount for an order', () => {
    const now = new Date('2026-09-11T12:00:00.000Z').getTime();
    vi.spyOn(Date, 'now').mockReturnValue(now);

    render(
      <RecentOrdersCard
        orders={[order({ total_amount: '49.99', currency_code: 'USD' })]}
        isLoading={false}
      />,
    );

    const listItem = screen.getAllByRole('listitem')[0];
    expect(within(listItem).getByText(/49\.99/)).toBeInTheDocument();

    vi.restoreAllMocks();
  });

  it('shows the Live badge when there are orders and no error', () => {
    render(<RecentOrdersCard orders={ORDERS} isLoading={false} />);

    expect(screen.getByText('Live')).toBeInTheDocument();
  });

  it('does not show the Live badge when there are no orders', () => {
    render(<RecentOrdersCard orders={[]} isLoading={false} />);

    expect(screen.queryByText('Live')).toBeNull();
  });

  it('does not show the Live badge when there is an error', () => {
    render(<RecentOrdersCard orders={ORDERS} isLoading={false} error="Partial data" />);

    expect(screen.queryByText('Live')).toBeNull();
  });
});
