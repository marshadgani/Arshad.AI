/**
 * WorkoutsCard — error / empty / data rendering matrix.
 *
 * Same contract as HRVTrendCard: "no workouts recorded" and "the workouts
 * endpoint failed" are different facts and must not share a rendering.
 *
 * Queries are by role and text, never by CSS class, per
 * .claude/rules/frontend.md.
 */

import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import WorkoutsCard from './WorkoutsCard';
import type { WhoopWorkout } from '../../types/whoop';

function workout(overrides: Partial<WhoopWorkout> = {}): WhoopWorkout {
  return {
    id: 1,
    sport_id: null,
    sport_name: 'Running',
    start: '2024-06-01T07:00:00Z',
    end: '2024-06-01T07:45:00Z',
    strain: 12.3,
    average_heart_rate: null,
    max_heart_rate: null,
    kilojoule: null,
    ...overrides,
  };
}

const WORKOUTS: WhoopWorkout[] = [
  workout(),
  workout({ id: 2, sport_name: 'Cycling', strain: 14.1 }),
];

describe('WorkoutsCard', () => {
  it('shows the empty state when there is no data and no error', () => {
    render(<WorkoutsCard workouts={[]} error={null} />);

    expect(screen.getByText(/no recent workouts/i)).toBeInTheDocument();
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.queryByRole('list')).toBeNull();
  });

  it('shows an announced error banner instead of the empty state when the fetch failed', () => {
    render(<WorkoutsCard workouts={[]} error={new Error('boom')} />);

    expect(screen.getByRole('alert')).toHaveTextContent(/could not load workouts/i);
    expect(screen.queryByText(/no recent workouts/i)).toBeNull();
  });

  it('keeps showing previously loaded workouts alongside the error banner', () => {
    render(<WorkoutsCard workouts={WORKOUTS} error={new Error('refresh failed')} />);

    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.getAllByRole('listitem')).toHaveLength(WORKOUTS.length);
    expect(screen.queryByText(/no recent workouts/i)).toBeNull();
  });

  it('renders one list item per workout with no error banner on the happy path', () => {
    render(<WorkoutsCard workouts={WORKOUTS} error={null} />);

    expect(screen.queryByRole('alert')).toBeNull();
    const items = screen.getAllByRole('listitem');
    expect(items).toHaveLength(2);
    expect(within(items[0]).getByText('Running')).toBeInTheDocument();
    expect(within(items[1]).getByText('Cycling')).toBeInTheDocument();
  });

  it('shows strain to one decimal place', () => {
    render(<WorkoutsCard workouts={WORKOUTS} error={null} />);

    expect(screen.getByText('12.3')).toBeInTheDocument();
    expect(screen.getByText('14.1')).toBeInTheDocument();
  });

  it('falls back to a generic label when the sport is unknown', () => {
    render(<WorkoutsCard workouts={[workout({ sport_name: null })]} error={null} />);

    expect(screen.getByText('Activity')).toBeInTheDocument();
  });

  it('renders an em dash rather than 0.0 for a workout with no strain yet', () => {
    render(<WorkoutsCard workouts={[workout({ strain: null })]} error={null} />);

    // Zero is a real reading; missing data is not, and the two must not
    // look the same on a health dashboard.
    expect(screen.getByText('—')).toBeInTheDocument();
    expect(screen.queryByText('0.0')).toBeNull();
  });

  it('defaults error to null so the prop stays optional', () => {
    render(<WorkoutsCard workouts={[]} />);

    expect(screen.getByText(/no recent workouts/i)).toBeInTheDocument();
    expect(screen.queryByRole('alert')).toBeNull();
  });
});
