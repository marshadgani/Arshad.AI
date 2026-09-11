/**
 * HRVTrendCard — error / empty / data rendering matrix.
 *
 * The card has to keep two facts apart that a naive implementation folds
 * together: "Whoop recorded no HRV in this window" (a fact about the user)
 * and "we could not reach the HRV endpoint" (a fact about the system).
 * Rendering the empty state for a failed fetch would quietly tell the user
 * their data does not exist.
 *
 * Queries are by role and text, never by CSS class, per
 * .claude/rules/frontend.md.
 */

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import HRVTrendCard from './HRVTrendCard';
import type { WhoopHRVPoint } from '../../types/whoop';

const POINTS: WhoopHRVPoint[] = [
  { date: '2024-06-01', hrv_rmssd_milli: 48.5 },
  { date: '2024-06-02', hrv_rmssd_milli: 52 },
  { date: '2024-06-03', hrv_rmssd_milli: 44.3 },
];

describe('HRVTrendCard', () => {
  it('shows the empty state when there is no data and no error', () => {
    render(<HRVTrendCard points={[]} days={14} error={null} />);

    expect(screen.getByText(/no hrv data/i)).toBeInTheDocument();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('shows an announced error banner instead of the empty state when the fetch failed', () => {
    render(<HRVTrendCard points={[]} days={14} error={new Error('boom')} />);

    // role=alert so assistive tech announces the failure; without it the
    // card silently swaps one paragraph for another.
    expect(screen.getByRole('alert')).toHaveTextContent(/could not load hrv data/i);
    // The two facts must not be shown at once.
    expect(screen.queryByText(/no hrv data/i)).toBeNull();
  });

  it('keeps showing previously loaded data alongside the error banner', () => {
    const { container } = render(
      <HRVTrendCard points={POINTS} days={14} error={new Error('refresh failed')} />,
    );

    expect(screen.getByRole('alert')).toBeInTheDocument();
    // Stale-but-real readings are more useful than a blank card.
    expect(container.querySelectorAll('[title]')).toHaveLength(POINTS.length);
    expect(screen.queryByText(/no hrv data/i)).toBeNull();
  });

  it('renders the sparkline with no error banner on the happy path', () => {
    const { container } = render(<HRVTrendCard points={POINTS} days={14} error={null} />);

    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.queryByText(/no hrv data/i)).toBeNull();
    expect(container.querySelectorAll('[title]')).toHaveLength(POINTS.length);
  });

  it('titles each bar with its own date and reading', () => {
    render(<HRVTrendCard points={POINTS} days={14} error={null} />);

    expect(screen.getByTitle('2024-06-01: 48.5 ms')).toBeInTheDocument();
    expect(screen.getByTitle('2024-06-03: 44.3 ms')).toBeInTheDocument();
  });

  it('names the window length in the title', () => {
    render(<HRVTrendCard points={POINTS} days={14} error={null} />);

    expect(screen.getByText(/hrv trend \(14 days\)/i)).toBeInTheDocument();
  });

  it('treats a null reading as zero height rather than crashing', () => {
    const withNull: WhoopHRVPoint[] = [
      { date: '2024-06-01', hrv_rmssd_milli: null },
      { date: '2024-06-02', hrv_rmssd_milli: 50 },
    ];

    render(<HRVTrendCard points={withNull} days={2} error={null} />);

    // A record still being computed arrives with its score absent; it must
    // render, not blank the card.
    expect(screen.getByTitle('2024-06-01: 0.0 ms')).toBeInTheDocument();
  });

  it('defaults error to null so the prop stays optional', () => {
    render(<HRVTrendCard points={[]} days={14} />);

    expect(screen.getByText(/no hrv data/i)).toBeInTheDocument();
    expect(screen.queryByRole('alert')).toBeNull();
  });
});
