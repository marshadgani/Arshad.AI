/**
 * ShopifyAnomalyRadar — loading/error/empty("insufficient"/"all clear")/
 * content states. Queries are by role/label/text only — no class or
 * test-id selectors, per .claude/rules/frontend.md.
 */

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import ShopifyAnomalyRadar from './ShopifyAnomalyRadar';
import type { ShopifyInsights } from '../../../types/shopify';

function makeInsights(pointsRevenue: (number | null)[], partialLast = true): ShopifyInsights {
  const points = pointsRevenue.map((rev, i) => ({
    date: `2026-09-${String(8 + i).padStart(2, '0')}`,
    revenue_amount: rev == null ? null : rev.toFixed(2),
    order_count: rev == null ? null : Math.max(1, Math.round(rev / 20)),
    is_partial_day: partialLast && i === pointsRevenue.length - 1,
  }));

  return {
    days: points.length,
    currency_code: 'USD',
    timezone: 'UTC',
    start_date: points[0].date,
    end_date: points[points.length - 1].date,
    points,
    summary: null,
    truncated: false,
    covered_through: null,
    cached_at: null,
    partial_failures: [],
  };
}

describe('ShopifyAnomalyRadar', () => {
  it('shows a loading skeleton with role=status when isLoading and no data yet', () => {
    render(<ShopifyAnomalyRadar insights={null} isLoading />);

    expect(screen.getByRole('status')).toBeInTheDocument();
  });

  it('shows an announced error banner when the shared insights fetch failed', () => {
    render(<ShopifyAnomalyRadar insights={null} isLoading={false} error={new Error('boom')} />);

    expect(screen.getByRole('alert')).toHaveTextContent(/could not scan/i);
  });

  it('shows an insufficient-data message with too few completed days', () => {
    const insights = makeInsights([100, 105, 98], false);

    render(<ShopifyAnomalyRadar insights={insights} isLoading={false} />);

    expect(screen.getByText(/not enough completed days/i)).toBeInTheDocument();
  });

  it('shows a distinct "all clear" state for a flat window', () => {
    const insights = makeInsights([100, 101, 99, 100, 101, 99], false);

    render(<ShopifyAnomalyRadar insights={insights} isLoading={false} />);

    expect(screen.getByText(/all clear/i)).toBeInTheDocument();
  });

  it('lists a detected spike with its date and amount', () => {
    const insights = makeInsights([100, 105, 98, 102, 500, 101], false);

    render(<ShopifyAnomalyRadar insights={insights} isLoading={false} />);

    expect(screen.getByRole('list', { name: /detected anomalies/i })).toBeInTheDocument();
    expect(screen.getByText('Spike')).toBeInTheDocument();
    expect(screen.getByText('$500.00')).toBeInTheDocument();
  });

  it('shows a badge count matching the number of anomalies found', () => {
    const insights = makeInsights([200, 210, 195, 205, 15, 198], false);

    render(<ShopifyAnomalyRadar insights={insights} isLoading={false} />);

    expect(screen.getByText('1')).toBeInTheDocument();
  });

  it('labels a zero-revenue day against an active baseline as a silent day', () => {
    const insights = makeInsights([200, 210, 195, 205, 0, 198], false);

    render(<ShopifyAnomalyRadar insights={insights} isLoading={false} />);

    expect(screen.getByText('Silent day')).toBeInTheDocument();
  });

  it('carries an aria-label identifying the card', () => {
    render(<ShopifyAnomalyRadar insights={null} isLoading />);

    expect(screen.getByLabelText('Shopify anomaly radar')).toBeInTheDocument();
  });
});
