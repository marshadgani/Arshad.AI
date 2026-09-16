/**
 * ShopifyInsightsCard — loading/error/empty/content states, truncation
 * gap-bar contract, and the day selector.
 *
 * Queries are by role/label/text only — no class or test-id selectors,
 * per .claude/rules/frontend.md.
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import ShopifyInsightsCard from './ShopifyInsightsCard';
import type { ShopifyInsights } from '../../../types/shopify';

function makeInsights(overrides: Partial<ShopifyInsights> = {}): ShopifyInsights {
  return {
    days: 7,
    currency_code: 'USD',
    timezone: 'UTC',
    start_date: '2026-09-08',
    end_date: '2026-09-14',
    points: [
      { date: '2026-09-08', revenue_amount: '100.00', order_count: 5, is_partial_day: false },
      { date: '2026-09-09', revenue_amount: '150.00', order_count: 6, is_partial_day: false },
      { date: '2026-09-10', revenue_amount: '50.00', order_count: 2, is_partial_day: false },
      { date: '2026-09-14', revenue_amount: '20.00', order_count: 1, is_partial_day: true },
    ],
    summary: {
      window_revenue: '300.00',
      window_order_count: 13,
      average_order_value: '23.08',
      best_day: '2026-09-09',
      worst_day: '2026-09-10',
      completed_day_count: 3,
      prior_period_change_pct: 8.4,
      direction: 'up',
    },
    truncated: false,
    covered_through: null,
    cached_at: '2026-09-14T09:00:00Z',
    partial_failures: [],
    ...overrides,
  };
}

describe('ShopifyInsightsCard', () => {
  it('shows a loading skeleton with role=status when isLoading and no data yet', () => {
    render(
      <ShopifyInsightsCard
        insights={null}
        days={7}
        onDaysChange={vi.fn()}
        isLoading
      />,
    );

    expect(screen.getByRole('status')).toBeInTheDocument();
  });

  it('shows an announced error banner instead of bars when the fetch failed', () => {
    render(
      <ShopifyInsightsCard
        insights={null}
        days={7}
        onDaysChange={vi.fn()}
        isLoading={false}
        error={new Error('boom')}
      />,
    );

    expect(screen.getByRole('alert')).toHaveTextContent(/could not load trend/i);
  });

  it('still announces the error when stale data from a previous window is present', () => {
    // A `days` switch leaves useFetch holding the PREVIOUS window's data
    // while the new request runs. If that failure were swallowed, the old
    // window's bars would stay on screen under the new window's label.
    render(
      <ShopifyInsightsCard
        insights={makeInsights({})}
        days={30}
        onDaysChange={vi.fn()}
        isLoading={false}
        error={new Error('boom')}
      />,
    );

    expect(screen.getByRole('alert')).toHaveTextContent(/could not load trend/i);
  });

  it('shows the empty state when points is empty', () => {
    render(
      <ShopifyInsightsCard
        insights={makeInsights({ points: [] })}
        days={7}
        onDaysChange={vi.fn()}
        isLoading={false}
      />,
    );

    expect(screen.getByText(/no revenue data/i)).toBeInTheDocument();
  });

  it('renders a no-data gap bar (not a zero bar) for a truncated point', () => {
    const insights = makeInsights({
      truncated: true,
      covered_through: '2026-09-10T00:00:00Z',
      summary: null,
      points: [
        { date: '2026-09-08', revenue_amount: '100.00', order_count: 5, is_partial_day: false },
        { date: '2026-09-09', revenue_amount: null, order_count: null, is_partial_day: false },
      ],
    });

    render(<ShopifyInsightsCard insights={insights} days={7} onDaysChange={vi.fn()} isLoading={false} />);

    expect(screen.getByTitle(/no data — window truncated/i)).toBeInTheDocument();
  });

  it('titles the partial-day bar as "today, so far"', () => {
    render(
      <ShopifyInsightsCard insights={makeInsights()} days={7} onDaysChange={vi.fn()} isLoading={false} />,
    );

    expect(screen.getByTitle(/today, so far/i)).toBeInTheDocument();
  });

  it('shows a truncation notice naming covered_through when truncated', () => {
    const insights = makeInsights({
      truncated: true,
      covered_through: '2026-09-10T00:00:00Z',
      summary: null,
    });

    render(<ShopifyInsightsCard insights={insights} days={7} onDaysChange={vi.fn()} isLoading={false} />);

    expect(screen.getByText(/incomplete/i)).toHaveTextContent('2026-09-10T00:00:00Z');
  });

  it('labels the summary row with completed_day_count, not the requested window', () => {
    render(
      <ShopifyInsightsCard insights={makeInsights()} days={7} onDaysChange={vi.fn()} isLoading={false} />,
    );

    expect(screen.getByText(/3 complete days/i)).toBeInTheDocument();
  });

  it('calls onDaysChange when a day-selector button is clicked', async () => {
    const user = userEvent.setup();
    const onDaysChange = vi.fn();
    render(
      <ShopifyInsightsCard insights={makeInsights()} days={7} onDaysChange={onDaysChange} isLoading={false} />,
    );

    await user.click(screen.getByRole('button', { name: '30d' }));

    expect(onDaysChange).toHaveBeenCalledWith(30);
  });

  it('marks the active day option with aria-pressed', () => {
    render(
      <ShopifyInsightsCard insights={makeInsights()} days={14} onDaysChange={vi.fn()} isLoading={false} />,
    );

    expect(screen.getByRole('button', { name: '14d' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: '7d' })).toHaveAttribute('aria-pressed', 'false');
  });

  it('calls onRefresh when the Refresh button is clicked', async () => {
    const user = userEvent.setup();
    const onRefresh = vi.fn();
    render(
      <ShopifyInsightsCard
        insights={makeInsights()}
        days={7}
        onDaysChange={vi.fn()}
        isLoading={false}
        onRefresh={onRefresh}
      />,
    );

    await user.click(screen.getByRole('button', { name: /refresh/i }));

    expect(onRefresh).toHaveBeenCalledTimes(1);
  });

  it('does not render a Refresh button when onRefresh is omitted', () => {
    render(
      <ShopifyInsightsCard insights={makeInsights()} days={7} onDaysChange={vi.fn()} isLoading={false} />,
    );

    expect(screen.queryByRole('button', { name: /refresh/i })).toBeNull();
  });

  it('carries an aria-label naming the window', () => {
    render(
      <ShopifyInsightsCard insights={makeInsights()} days={7} onDaysChange={vi.fn()} isLoading={false} />,
    );

    expect(screen.getByLabelText('Shopify revenue trend, 7 days')).toBeInTheDocument();
  });
});
