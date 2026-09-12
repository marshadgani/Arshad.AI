/**
 * HealthFitness — error-vs-dashboard gate.
 *
 * Regression guard for a gate finding: the page used to gate its full-page
 * error state on `error` alone, so a single flaky 120s background poll
 * would blank an already-rendered dashboard (recovery/sleep/strain/HRV/
 * workouts) and replace it with a bare error message. Fixed to mirror
 * ShopifyStore.tsx's `error && !dashboard` guard — only a failed *first*
 * load shows the full-page error; a later poll failure leaves the last
 * good render on screen.
 */

import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('../hooks/useWhoopDashboard');
vi.mock('../components/AppleHealthCard', () => ({
  default: () => <div data-testid="apple-health-card" />,
}));

import HealthFitness from './HealthFitness';
import { useWhoopDashboard } from '../hooks/useWhoopDashboard';
import type { UseWhoopDashboardResult } from '../hooks/useWhoopDashboard';

const mockUseWhoopDashboard = vi.mocked(useWhoopDashboard);

afterEach(() => {
  vi.restoreAllMocks();
});

const BASE: UseWhoopDashboardResult = {
  dashboard: null,
  hrvPoints: [],
  workouts: [],
  isLoading: false,
  error: null,
  hrvError: null,
  workoutsError: null,
};

const CONNECTED_DASHBOARD = {
  connected: true,
  needs_reauth: false,
  degraded: false,
  recovery: null,
  sleep: null,
  strain: null,
  user_first_name: 'Arshad',
} as UseWhoopDashboardResult['dashboard'];

describe('HealthFitness', () => {
  it('shows the full-page error on a failed first load (no dashboard yet)', () => {
    mockUseWhoopDashboard.mockReturnValue({
      ...BASE,
      error: new Error('network down'),
      dashboard: null,
    });

    render(<HealthFitness />);

    expect(
      screen.getByText('Failed to load health data. Check backend logs.'),
    ).toBeInTheDocument();
  });

  it('does not blank an already-rendered dashboard on a background poll error', () => {
    mockUseWhoopDashboard.mockReturnValue({
      ...BASE,
      error: new Error('transient poll failure'),
      dashboard: CONNECTED_DASHBOARD,
    });

    render(<HealthFitness />);

    expect(
      screen.queryByText('Failed to load health data. Check backend logs.'),
    ).not.toBeInTheDocument();
    // The last-good dashboard is still rendered — Apple Health tile present.
    expect(screen.getByTestId('apple-health-card')).toBeInTheDocument();
  });

  it('renders the loading state before any data has arrived', () => {
    mockUseWhoopDashboard.mockReturnValue({ ...BASE, isLoading: true });

    render(<HealthFitness />);

    expect(screen.getByText('Loading health data…')).toBeInTheDocument();
  });
});
