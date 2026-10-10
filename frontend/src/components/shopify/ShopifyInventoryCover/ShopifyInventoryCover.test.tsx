import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { InventoryCoverResponse } from '../../../types/shopify';
import { ShopifyInventoryCover } from './ShopifyInventoryCover';

function cover(overrides: Partial<InventoryCoverResponse> = {}): InventoryCoverResponse {
  return {
    connected: true,
    needs_reauth: false,
    days_of_cover: [
      {
        variant_id: 'gid://shopify/ProductVariant/1',
        available_qty: 10,
        velocity_30d: '1.0',
        days_of_cover: '10.0',
        no_recent_sales: false,
        is_alert: true,
        projected_stockout_date: '2026-11-08',
      },
      {
        variant_id: 'gid://shopify/ProductVariant/2',
        available_qty: 4,
        velocity_30d: null,
        days_of_cover: null,
        no_recent_sales: true,
        is_alert: false,
        projected_stockout_date: null,
      },
    ],
    alerts: [
      {
        variant_id: 'gid://shopify/ProductVariant/1',
        projected_stockout_date: '2026-11-08',
        travel_event_title: 'Conference Trip',
      },
    ],
    variants_truncated: false,
    orders_truncated: false,
    calendar_connected: true,
    calendar_needs_reauth: false,
    partial_failures: [],
    cached_at: null,
    ...overrides,
  };
}

const noop = () => {};

describe('ShopifyInventoryCover', () => {
  it('shows a loading status on first fetch', () => {
    render(<ShopifyInventoryCover data={null} isLoading error={null} onRetry={noop} />);
    expect(screen.getByRole('status')).toHaveTextContent('Loading inventory cover');
  });

  it('shows the error and lets the user retry', () => {
    const onRetry = vi.fn();
    render(<ShopifyInventoryCover data={null} isLoading={false} error={new Error('x')} onRetry={onRetry} />);
    expect(screen.getByRole('alert')).toHaveTextContent('Failed to load inventory cover.');
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it('shows a not-connected state instead of an empty-state when Shopify is not connected', () => {
    render(<ShopifyInventoryCover data={cover({ connected: false, days_of_cover: [], alerts: [] })} isLoading={false} error={null} onRetry={noop} />);
    expect(screen.getByText('Shopify not connected')).toBeInTheDocument();
    expect(screen.queryByText('No tracked variants')).not.toBeInTheDocument();
  });

  it('shows a reconnect state instead of an empty-state when Shopify needs reauth', () => {
    render(<ShopifyInventoryCover data={cover({ needs_reauth: true, days_of_cover: [], alerts: [] })} isLoading={false} error={null} onRetry={noop} />);
    expect(screen.getByText('Reconnect Shopify')).toBeInTheDocument();
    expect(screen.queryByText('No tracked variants')).not.toBeInTheDocument();
  });

  it('says there are no tracked variants when the list is empty and nothing failed', () => {
    render(<ShopifyInventoryCover data={cover({ days_of_cover: [], alerts: [] })} isLoading={false} error={null} onRetry={noop} />);
    expect(screen.getByText('No tracked variants')).toBeInTheDocument();
  });

  it('does not call an empty list "no tracked variants" when the fetch was throttled', () => {
    render(
      <ShopifyInventoryCover
        data={cover({ days_of_cover: [], alerts: [], partial_failures: ['throttled'] })}
        isLoading={false}
        error={null}
        onRetry={noop}
      />,
    );
    expect(screen.getByText('Inventory unavailable')).toBeInTheDocument();
    expect(screen.queryByText('No tracked variants')).not.toBeInTheDocument();
  });

  it('renders rows with the travel stockout alert and honest dashes', () => {
    render(<ShopifyInventoryCover data={cover()} isLoading={false} error={null} onRetry={noop} />);
    expect(screen.getByText('Stockout 2026-11-08 during Conference Trip')).toBeInTheDocument();
    expect(screen.getByText('No recent sales')).toBeInTheDocument();
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(2);
  });

  it('shows truncation and calendar caveats', () => {
    render(
      <ShopifyInventoryCover
        data={cover({ variants_truncated: true, orders_truncated: true, calendar_connected: false })}
        isLoading={false}
        error={null}
        onRetry={noop}
      />,
    );
    expect(screen.getByText(/Variant data incomplete/)).toBeInTheDocument();
    expect(screen.getByText(/Velocity may be understated/)).toBeInTheDocument();
    expect(screen.getByText(/Calendar not connected/)).toBeInTheDocument();
  });

  it('distinguishes calendar reauth from not connected', () => {
    render(
      <ShopifyInventoryCover
        data={cover({ calendar_needs_reauth: true, partial_failures: ['calendar'] })}
        isLoading={false}
        error={null}
        onRetry={noop}
      />,
    );
    expect(screen.getByText(/reconnect Google/)).toBeInTheDocument();
    expect(screen.queryByText(/Calendar not connected/)).not.toBeInTheDocument();
  });
});
