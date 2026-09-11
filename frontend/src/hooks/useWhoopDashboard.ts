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
 * The two secondary fetches (HRV trend, workouts) are skipped entirely
 * while Whoop is disconnected or needs re-authentication — both are
 * guaranteed to 404/409 in that state, so firing them serves no purpose.
 * A skipped useFetch reports error: null, so a skipped card renders its
 * empty state rather than a failure it never attempted.
 *
 * Their errors are surfaced separately (hrvError/workoutsError) so each
 * card can render its own failure state; a secondary failure must never
 * blank the whole page.
 */

import { useFetch } from './useFetch';
import type { WhoopDashboard, WhoopHRVPoint, WhoopWorkout } from '../types/whoop';

export interface UseWhoopDashboardResult {
  dashboard: WhoopDashboard | null;
  hrvPoints: WhoopHRVPoint[];
  workouts: WhoopWorkout[];
  isLoading: boolean;
  error: Error | null;
  hrvError: Error | null;
  workoutsError: Error | null;
}

// Recovery/sleep/strain change at most a few times a day, but the tile is
// always on screen; 120s keeps it fresh without hammering Whoop's rate limit.
const DASHBOARD_POLL_MS = 120_000;

export function useWhoopDashboard(): UseWhoopDashboardResult {
  const { data, isLoading, error } = useFetch<WhoopDashboard>(
    '/api/v1/whoop/dashboard',
    { refreshInterval: DASHBOARD_POLL_MS },
  );

  const skipSecondaries = !data?.connected || !!data?.needs_reauth;

  const { data: hrvPoints, error: hrvError } = useFetch<WhoopHRVPoint[]>(
    '/api/v1/whoop/hrv-trend',
    { skip: skipSecondaries },
  );
  const { data: workouts, error: workoutsError } = useFetch<WhoopWorkout[]>(
    '/api/v1/whoop/workouts',
    { skip: skipSecondaries },
  );

  return {
    dashboard: data,
    hrvPoints: hrvPoints ?? [],
    workouts: workouts ?? [],
    isLoading,
    error,
    hrvError,
    workoutsError,
  };
}
