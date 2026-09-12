/**
 * KpiCard — four-state rendering contract.
 *
 * The card must never show a stale or zero value in the loading state, must
 * never show hint text when unavailable, and must always surface the
 * "Learn more" link for plan-gated metrics when a docsHref is provided.
 */

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { KpiCard } from './KpiCard';

describe('KpiCard', () => {
  it('shows a skeleton and marks the group busy while loading', () => {
    render(<KpiCard label="Today's Revenue" value={null} state="loading" />);

    const group = screen.getByRole('group', { name: "Today's Revenue" });
    expect(group).toHaveAttribute('aria-busy', 'true');
  });

  it('does not show the value or hint text in the loading state', () => {
    render(
      <KpiCard label="Today's Revenue" value="$500" hint="some hint" state="loading" />,
    );

    expect(screen.queryByText('$500')).toBeNull();
    expect(screen.queryByText('some hint')).toBeNull();
  });

  it('renders the value in the ok state', () => {
    render(<KpiCard label="Orders Today" value="42" state="ok" />);

    expect(screen.getByText('42')).toBeInTheDocument();
  });

  it('renders the hint text in the ok state when provided', () => {
    render(<KpiCard label="Orders Today" value="42" hint="(approximate)" state="ok" />);

    expect(screen.getByText('(approximate)')).toBeInTheDocument();
  });

  it('renders an em dash for a null value in the ok state', () => {
    render(<KpiCard label="Conversion Rate" value={null} state="ok" />);

    expect(screen.getByText('—')).toBeInTheDocument();
  });

  it('renders the value in the empty state', () => {
    render(<KpiCard label="Low Stock SKUs" value="—" state="empty" />);

    expect(screen.getByText('—')).toBeInTheDocument();
  });

  it('shows the plan-gated message and not the value in the unavailable state', () => {
    render(<KpiCard label="Conversion Rate" value="3.2%" state="unavailable" />);

    expect(screen.getByText(/not available on this plan/i)).toBeInTheDocument();
    expect(screen.queryByText('3.2%')).toBeNull();
  });

  it('does not show hint text in the unavailable state', () => {
    render(
      <KpiCard label="Conversion Rate" value={null} hint="some hint" state="unavailable" />,
    );

    expect(screen.queryByText('some hint')).toBeNull();
  });

  it('renders a "Learn more" link in the unavailable state when docsHref is given', () => {
    render(
      <KpiCard
        label="Conversion Rate"
        value={null}
        state="unavailable"
        docsHref="https://help.shopify.com"
      />,
    );

    const link = screen.getByRole('link', { name: /learn more/i });
    expect(link).toHaveAttribute('href', 'https://help.shopify.com');
  });

  it('does not render a "Learn more" link when docsHref is absent', () => {
    render(<KpiCard label="Conversion Rate" value={null} state="unavailable" />);

    expect(screen.queryByRole('link')).toBeNull();
  });

  it('marks the group as not busy in the ok state', () => {
    render(<KpiCard label="Orders Today" value="5" state="ok" />);

    const group = screen.getByRole('group', { name: 'Orders Today' });
    expect(group).toHaveAttribute('aria-busy', 'false');
  });
});
