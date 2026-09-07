/**
 * Whoop data for the Health page.
 *
 * The page previously made three separate useFetch calls inline, mixing
 * data acquisition into a component that also did layout and formatting.
 * Collecting them here gives the page a single dependency with one shape,
 * matches the existing useAppleHealth pattern, and means the polling
 * intervals are declared next to each other instead of scattered through
 * JSX.
 *
 * Only the dashboard's loading/error state is surfaced. The HRV trend and
 * workouts are secondary: their cards render their own empty state, and a
 * failure in either must not blank the page — same behaviour as before.
 */

import { useFetch } from './useFetch';
import type { WhoopDashboard, WhoopHRVPoint, WhoopWorkout } from '../types/whoop';

export interface UseWhoopDashboardResult {
  dashboard: WhoopDashboard | null;
  hrvPoints: WhoopHRVPoint[];
  workouts: WhoopWorkout[];
  isLoading: boolean;
  error: Error | null;
}

// Recovery/sleep/strain change at most a few times a day, but the tile is
// always on screen; 120s keeps it fresh without hammering Whoop's rate limit.
const DASHBOARD_POLL_MS = 120_000;

export function useWhoopDashboard(): UseWhoopDashboardResult {
  const { data, isLoading, error } = useFetch<WhoopDashboard>(
    '/api/v1/whoop/dashboard',
    DASHBOARD_POLL_MS,
  );
  const { data: hrvPoints } = useFetch<WhoopHRVPoint[]>('/api/v1/whoop/hrv-trend');
  const { data: workouts } = useFetch<WhoopWorkout[]>('/api/v1/whoop/workouts');

  return {
    dashboard: data,
    hrvPoints: hrvPoints ?? [],
    workouts: workouts ?? [],
    isLoading,
    error,
  };
}
