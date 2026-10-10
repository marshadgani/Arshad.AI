import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { ServiceDebtResponse } from '../../../types/shopify';
import { ShopifyServiceDebt } from './ShopifyServiceDebt';

function debt(overrides: Partial<ServiceDebtResponse> = {}): ServiceDebtResponse {
  return {
    gmail_connected: true,
    shopify_connected: true,
    needs_reauth: false,
    threads: [
      {
        id: 'a',
        snippet: 'Where is order #1042?',
        matched_order_id: 'gid://shopify/Order/1',
        matched_order_name: '#1042',
        match_confidence: 'high',
      },
      { id: 'b', snippet: 'Hello?', matched_order_id: null, matched_order_name: null, match_confidence: null },
    ],
    threads_truncated: false,
    orders_truncated: false,
    partial_failures: [],
    cached_at: null,
    ...overrides,
  };
}

const noop = () => {};
const renderDebt = (data: ServiceDebtResponse | null, extra: { isLoading?: boolean; error?: Error | null; onRetry?: () => void } = {}) =>
  render(
    <ShopifyServiceDebt
      data={data}
      isLoading={extra.isLoading ?? false}
      error={extra.error ?? null}
      onRetry={extra.onRetry ?? noop}
    />,
  );

describe('ShopifyServiceDebt', () => {
  it('shows a loading status', () => {
    renderDebt(null, { isLoading: true });
    expect(screen.getByRole('status')).toHaveTextContent('Loading customer service debt');
  });

  it('shows the error with a working retry', () => {
    const onRetry = vi.fn();
    renderDebt(null, { error: new Error('x'), onRetry });
    expect(screen.getByRole('alert')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it('shows Gmail not connected instead of an empty list', () => {
    renderDebt(debt({ gmail_connected: false, threads: [] }));
    expect(screen.getByText('Gmail not connected')).toBeInTheDocument();
  });

  it('asks for reconnect when Gmail needs reauth', () => {
    renderDebt(debt({ needs_reauth: true, partial_failures: ['gmail'], threads: [] }));
    expect(screen.getByText('Reconnect Google')).toBeInTheDocument();
  });

  it('shows the empty state when nothing is waiting', () => {
    renderDebt(debt({ threads: [] }));
    expect(screen.getByText('No old unanswered threads')).toBeInTheDocument();
  });

  it('renders matches with confidence and the approximation footer', () => {
    renderDebt(debt());
    expect(screen.getByText('#1042')).toBeInTheDocument();
    expect(screen.getByText('High confidence')).toBeInTheDocument();
    expect(screen.getByText('No match')).toBeInTheDocument();
    expect(screen.getByText(/Order matching is approximate/)).toBeInTheDocument();
  });

  it('shows truncation and Shopify-not-connected caveats', () => {
    renderDebt(debt({ threads_truncated: true, shopify_connected: false }));
    expect(screen.getByText(/100 most recent matching threads/)).toBeInTheDocument();
    expect(screen.getByText(/Shopify not connected/)).toBeInTheDocument();
  });

  it('warns when order lookups failed', () => {
    renderDebt(debt({ partial_failures: ['orders'] }));
    expect(screen.getByText(/Order context could not be loaded/)).toBeInTheDocument();
  });
});
