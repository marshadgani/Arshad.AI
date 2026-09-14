import { useCallback, useEffect, useState } from 'react';

import { clearToken, getToken } from '../auth/tokenStorage';

export interface UsePaginatedFetchResult<T> {
  data: T[];
  total: number;
  isLoading: boolean;
  error: Error | null;
  /** Re-run the request now (e.g. from an error state's Retry button). */
  refetch: () => void;
}

/**
 * Fetches a paginated list endpoint that returns the API envelope
 * `{ data: T[], total: number }`. Distinct from useFetch because callers
 * that page through a large collection (e.g. the AI Ecosystem Skills tab,
 * ~1.3k rows) need `total` to render "Showing X-Y of N" and to disable
 * next/prev — useFetch intentionally discards everything but the inner
 * `data` array to keep its contract simple for the (far more common)
 * non-paginated callers.
 */
export function usePaginatedFetch<T>(url: string): UsePaginatedFetchResult<T> {
  const [data, setData] = useState<T[]>([]);
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [tick, setTick] = useState(0);
  const refetch = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    setIsLoading(true);
    setError(null);

    const token = getToken();
    const headers: Record<string, string> = {};
    if (token) headers.Authorization = `Bearer ${token}`;

    fetch(url, { signal: controller.signal, headers })
      .then(async (res) => {
        if (res.status === 401) {
          clearToken();
          throw new Error('401 Unauthorized');
        }
        if (!res.ok) {
          const body = await res.text();
          throw new Error(`${res.status} ${res.statusText}: ${body.slice(0, 200)}`);
        }
        return res.json() as Promise<{ data: T[]; total: number }>;
      })
      .then((body) => {
        if (controller.signal.aborted) return;
        setData(body.data);
        setTotal(body.total);
      })
      .catch((err: Error) => {
        if (err.name === 'AbortError') return;
        if (!controller.signal.aborted) setError(err);
      })
      .finally(() => {
        if (!controller.signal.aborted) setIsLoading(false);
      });

    return () => controller.abort();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, tick]);

  return { data, total, isLoading, error, refetch };
}
