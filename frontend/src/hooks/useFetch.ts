import { useEffect, useState } from 'react';

export interface UseFetchResult<T> {
  data: T | null;
  isLoading: boolean;
  error: Error | null;
}

// Unwraps the API envelope `{ data: ... }` and returns the inner value.
// Per .claude/rules/frontend.md: data-fetching hooks return
// { data, isLoading, error } consistently.
export function useFetch<T>(url: string): UseFetchResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    setError(null);

    fetch(url)
      .then(async (res) => {
        if (!res.ok) {
          const body = await res.text();
          throw new Error(`${res.status} ${res.statusText}: ${body.slice(0, 200)}`);
        }
        return res.json() as Promise<{ data: T }>;
      })
      .then((body) => {
        if (!cancelled) setData(body.data);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [url]);

  return { data, isLoading, error };
}
