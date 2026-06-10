import { useEffect, useState } from 'react';

import { clearToken, getToken } from '../auth/tokenStorage';

export interface UseFetchResult<T> {
  data: T | null;
  isLoading: boolean;
  error: Error | null;
}

// Unwraps the API envelope `{ data: ... }` and returns the inner value.
// Per .claude/rules/frontend.md: data-fetching hooks return
// { data, isLoading, error } consistently.
//
// Phase C: attaches Authorization: Bearer <jwt> from localStorage when
// present. A 401 response wipes the token so the AuthContext effect
// observes the change and bounces the user to /login.
//
// Pass refreshInterval (ms) to poll the endpoint automatically — useful for
// live data like the agent registry that changes outside the React session.
export function useFetch<T>(url: string, refreshInterval?: number): UseFetchResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  // Incrementing this triggers a re-fetch without changing the URL.
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!refreshInterval) return;
    const id = setInterval(() => setTick((t) => t + 1), refreshInterval);
    return () => clearInterval(id);
  }, [refreshInterval]);

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
        return res.json() as Promise<{ data: T }>;
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
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, tick]);

  return { data, isLoading, error };
}
