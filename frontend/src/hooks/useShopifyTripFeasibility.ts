/**
 * Mutation-style hook for POST /api/v1/trip-feasibility.
 *
 * Nothing is requested on mount. A 401 clears the token as useFetch does (a
 * real session expiry: the endpoint never uses 401 for Shopify or Calendar
 * state). A 422 is split into per-field messages. `result` is only ever set
 * from a 200 body, so a failed request can never leave a stale verdict.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { clearToken, getToken } from '../auth/tokenStorage';
import type { TripFeasibilityResult } from '../types/shopify';

export type TripField = 'start_date' | 'end_date';
export type TripFieldErrors = Partial<Record<TripField, string>>;

export interface UseShopifyTripFeasibilityResult {
  result: TripFeasibilityResult | null;
  isLoading: boolean;
  error: Error | null;
  fieldErrors: TripFieldErrors;
  check: (startDate: string, endDate: string) => Promise<void>;
}

const VERDICTS: readonly string[] = ['go', 'no-go', 'unknown'];

interface ValidationEntry {
  loc?: unknown[];
  msg?: string;
}

function validationEntries(body: unknown): ValidationEntry[] {
  const entries = (body as { error?: { details?: { errors?: ValidationEntry[] } } })?.error
    ?.details?.errors;
  return Array.isArray(entries) ? entries : [];
}

export function useShopifyTripFeasibility(): UseShopifyTripFeasibilityResult {
  const [result, setResult] = useState<TripFeasibilityResult | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [fieldErrors, setFieldErrors] = useState<TripFieldErrors>({});
  const controllerRef = useRef<AbortController | null>(null);

  useEffect(() => () => controllerRef.current?.abort(), []);

  const check = useCallback(async (startDate: string, endDate: string) => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setIsLoading(true);
    setError(null);
    setFieldErrors({});
    setResult(null);

    try {
      const token = getToken();
      const res = await fetch('/api/v1/trip-feasibility', {
        method: 'POST',
        signal: controller.signal,
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ start_date: startDate, end_date: endDate }),
      });
      if (res.status === 401) {
        clearToken();
        throw new Error('401 Unauthorized');
      }
      if (res.status === 422) {
        const entries = validationEntries(await res.json().catch(() => null));
        const fields: TripFieldErrors = {};
        for (const entry of entries) {
          const field = entry.loc?.[entry.loc.length - 1];
          if ((field === 'start_date' || field === 'end_date') && entry.msg) {
            fields[field] = entry.msg;
          }
        }
        if (!controller.signal.aborted) {
          setFieldErrors(fields);
          if (Object.keys(fields).length === 0) {
            setError(new Error(entries[0]?.msg ?? 'Invalid request.'));
          }
        }
        return;
      }
      if (res.status === 429) {
        throw new Error('Too many checks. Wait a minute and try again.');
      }
      if (!res.ok) {
        // The raw body may carry proxy or server internals, so only the status is shown.
        throw new Error(`The check failed (status ${res.status}). Try again shortly.`);
      }
      const body = (await res.json()) as { data?: TripFeasibilityResult } | null;
      const data = body?.data;
      if (!data || !VERDICTS.includes(data.verdict)) {
        throw new Error('The server returned an unexpected response.');
      }
      if (!controller.signal.aborted) setResult(data);
    } catch (err) {
      if ((err as Error).name === 'AbortError') return;
      if (!controller.signal.aborted) setError(err as Error);
    } finally {
      if (!controller.signal.aborted) setIsLoading(false);
    }
  }, []);

  return { result, isLoading, error, fieldErrors, check };
}
