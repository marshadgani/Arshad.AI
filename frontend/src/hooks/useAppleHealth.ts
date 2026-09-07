import { useCallback, useEffect, useState } from 'react';

import { clearToken, getToken } from '../auth/tokenStorage';

export interface AppleHealthSnapshot {
  connected: boolean;
  stale: boolean;
  resting_heart_rate: number | null;
  heart_rate_variability_ms: number | null;
  sleep_hours: number | null;
  active_energy_kcal: number | null;
  steps: number | null;
  vo2_max: number | null;
  recorded_at: string | null;
  received_at: string | null;
}

export interface UseAppleHealthResult {
  data: AppleHealthSnapshot | null;
  isLoading: boolean;
  error: Error | null;
  refetch: () => void;
}

const URL = '/api/v1/apple-health/dashboard';
const POLL_MS = 90_000;

// Same envelope-unwrapping contract as useFetch, but exposes `refetch` —
// the generic hook has no way to trigger a fetch from outside its own
// interval, and this page needs to re-poll immediately after the user
// finishes the Apple Health connect flow instead of waiting up to 90s.
export function useAppleHealth(): UseAppleHealthResult {
  const [data, setData] = useState<AppleHealthSnapshot | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [tick, setTick] = useState(0);

  const refetch = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    const id = setInterval(refetch, POLL_MS);
    return () => clearInterval(id);
  }, [refetch]);

  useEffect(() => {
    const controller = new AbortController();
    setIsLoading(true);
    setError(null);

    const token = getToken();
    const headers: Record<string, string> = {};
    if (token) headers.Authorization = `Bearer ${token}`;

    fetch(URL, { signal: controller.signal, headers })
      .then(async (res) => {
        if (res.status === 401) {
          clearToken();
          throw new Error('401 Unauthorized');
        }
        if (!res.ok) {
          const body = await res.text();
          throw new Error(`${res.status} ${res.statusText}: ${body.slice(0, 200)}`);
        }
        return res.json() as Promise<{ data: AppleHealthSnapshot }>;
      })
      .then((body) => {
        if (!controller.signal.aborted) setData(body.data);
      })
      .catch((err: Error) => {
        if (err.name === 'AbortError') return;
        if (!controller.signal.aborted) setError(err);
      })
      .finally(() => {
        if (!controller.signal.aborted) setIsLoading(false);
      });

    return () => controller.abort();
  }, [tick]);

  return { data, isLoading, error, refetch };
}
