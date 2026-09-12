/**
 * Apple Health snapshot for the Health page.
 *
 * This hook used to re-implement useFetch in full — auth header, 401 →
 * clearToken, AbortController, `{ data }` envelope unwrap, loading/error
 * state — solely because it also needed a `refetch` the generic hook did
 * not expose. That is ~50 lines of transport policy maintained in two
 * places: useFetch later grew a `skip` option and a documented 401 →
 * app-wide-logout contract that this copy never received.
 *
 * useFetch now exposes `refetch`, so this is composition over duplication:
 * one transport, one 401 policy, and this module left owning only what is
 * actually Apple-Health-specific — the URL and the poll interval.
 */

import { useFetch } from './useFetch';
import type { AppleHealthSnapshot } from '../types/appleHealth';

export type { AppleHealthSnapshot } from '../types/appleHealth';

export interface UseAppleHealthResult {
  data: AppleHealthSnapshot | null;
  isLoading: boolean;
  error: Error | null;
  refetch: () => void;
}

const URL = '/api/v1/apple-health/dashboard';

// Pushes arrive at whatever cadence the user's Shortcut runs (typically
// hourly), so polling faster buys nothing; 90s is fast enough that a push
// landing mid-session shows up without the user reloading.
const POLL_MS = 90_000;

export function useAppleHealth(): UseAppleHealthResult {
  return useFetch<AppleHealthSnapshot>(URL, { refreshInterval: POLL_MS });
}
