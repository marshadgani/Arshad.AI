import { useCallback, useEffect, useState } from 'react';

import { clearToken, getToken } from '../auth/tokenStorage';

/**
 * `data`/`isLoading`/`error` are kept as three independent fields (rather
 * than a discriminated union) because that is the shape every existing
 * caller across the app destructures — changing it would be a breaking
 * API change to a hook used from many call sites. `status` is added
 * alongside them, additively, as the single source of truth for "which
 * state is this": it is derived from the same three fields the same way
 * every time, instead of each caller re-deriving its own `isLoading &&
 * !error` style condition (which is easy to get subtly wrong, e.g.
 * forgetting a still-loading refetch can coexist with stale `data` from
 * the previous successful fetch). Prefer switching on `status` in new
 * code; `data`/`isLoading`/`error` remain for existing callers and for
 * reading the payload/error value once `status` has narrowed which one
 * is meaningful.
 */
export type UseFetchStatus = 'idle' | 'loading' | 'success' | 'error';

export interface UseFetchResult<T> {
  data: T | null;
  isLoading: boolean;
  error: Error | null;
  status: UseFetchStatus;
  /**
   * Re-run the request now, without waiting for refreshInterval. Stable
   * across renders, so it is safe as an effect dependency or an onClick.
   *
   * Exists because a caller sometimes knows the resource changed before
   * the next poll would notice — e.g. the user just finished a connect
   * flow. Without it, hooks that needed this re-implemented the whole
   * fetch (auth header, 401 handling, abort, envelope unwrap) just to own
   * a tick counter, which is exactly how transport policy drifts between
   * copies.
   */
  refetch: () => void;
}

function deriveStatus(isLoading: boolean, error: Error | null, data: unknown): UseFetchStatus {
  if (isLoading) return 'loading';
  if (error) return 'error';
  if (data !== null) return 'success';
  return 'idle';
}

export interface UseFetchOptions {
  /** Poll the endpoint automatically at this interval (ms). */
  refreshInterval?: number;
  /**
   * When true, no fetch is fired and the hook immediately returns
   * { data: null, isLoading: false, error: null } — used when the caller
   * knows in advance the request would fail or is not meaningful (e.g. a
   * secondary endpoint that 404s while its primary resource is
   * disconnected). Toggling skip false->true cancels any in-flight
   * request and resets to that triple; toggling true->false fires a
   * fresh fetch.
   */
  skip?: boolean;
}

// Unwraps the API envelope `{ data: ... }` and returns the inner value.
// Per .claude/rules/frontend.md: data-fetching hooks return
// { data, isLoading, error } consistently.
//
// Phase C: attaches Authorization: Bearer <jwt> from localStorage when
// present. A 401 response wipes the token so the AuthContext effect
// observes the change and bounces the user to /login.
export function useFetch<T>(url: string, options?: UseFetchOptions): UseFetchResult<T> {
  const { refreshInterval, skip = false } = options ?? {};

  const [data, setData] = useState<T | null>(null);
  const [isLoading, setIsLoading] = useState(!skip);
  const [error, setError] = useState<Error | null>(null);
  // Incrementing this triggers a re-fetch without changing the URL.
  const [tick, setTick] = useState(0);
  const refetch = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    if (!refreshInterval || skip) return;
    const id = setInterval(refetch, refreshInterval);
    return () => clearInterval(id);
  }, [refreshInterval, skip, refetch]);

  useEffect(() => {
    if (skip) {
      setData(null);
      setError(null);
      setIsLoading(false);
      return;
    }

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
        if (!controller.signal.aborted) {
          // Surfaced to the UI via `error`, but that string is lost the
          // moment the component unmounts or the message is truncated —
          // log the full error here so it is still traceable (console in
          // dev, captured by the browser's error reporting in prod).
          console.error(`useFetch failed: GET ${url}`, err);
          setError(err);
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setIsLoading(false);
      });

    return () => controller.abort();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, tick, skip]);

  if (skip) {
    return { data: null, isLoading: false, error: null, status: 'idle', refetch };
  }

  return { data, isLoading, error, status: deriveStatus(isLoading, error, data), refetch };
}
