/**
 * Mutation-style hook for POST /api/v1/shopify/discount-simulator.
 *
 * Deliberately not useFetch: nothing is requested on mount, only when the
 * user submits. A 401 clears the token exactly as useFetch does (that is a
 * real Arshad.AI session expiry — the endpoint never uses 401 for Shopify
 * state). A 422 is split into per-field messages for the form.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { clearToken, getToken } from '../auth/tokenStorage';
import type { DiscountSimulatorResult } from '../types/shopify';

export type DiscountField = 'variant_id' | 'discount_percent';
export type DiscountFieldErrors = Partial<Record<DiscountField, string>>;

export interface UseShopifyDiscountSimulatorResult {
  result: DiscountSimulatorResult | null;
  isLoading: boolean;
  error: Error | null;
  fieldErrors: DiscountFieldErrors;
  checkDiscount: (variantId: string, discountPercent: number) => Promise<void>;
}

interface ValidationEntry {
  loc?: unknown[];
  msg?: string;
}

function fieldErrorsFrom(body: unknown): DiscountFieldErrors {
  const entries = (body as { error?: { details?: { errors?: ValidationEntry[] } } })
    ?.error?.details?.errors;
  const out: DiscountFieldErrors = {};
  for (const entry of entries ?? []) {
    const field = entry.loc?.[entry.loc.length - 1];
    if ((field === 'variant_id' || field === 'discount_percent') && entry.msg) {
      out[field] = entry.msg;
    }
  }
  return out;
}

export function useShopifyDiscountSimulator(): UseShopifyDiscountSimulatorResult {
  const [result, setResult] = useState<DiscountSimulatorResult | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [fieldErrors, setFieldErrors] = useState<DiscountFieldErrors>({});
  const controllerRef = useRef<AbortController | null>(null);

  useEffect(() => () => controllerRef.current?.abort(), []);

  const checkDiscount = useCallback(async (variantId: string, discountPercent: number) => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setIsLoading(true);
    setError(null);
    setFieldErrors({});
    setResult(null);

    try {
      const token = getToken();
      const res = await fetch('/api/v1/shopify/discount-simulator', {
        method: 'POST',
        signal: controller.signal,
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ variant_id: variantId, discount_percent: discountPercent }),
      });
      if (res.status === 401) {
        clearToken();
        throw new Error('401 Unauthorized');
      }
      if (res.status === 422) {
        const fields = fieldErrorsFrom(await res.json().catch(() => null));
        if (!controller.signal.aborted) {
          setFieldErrors(fields);
          if (Object.keys(fields).length === 0) setError(new Error('Invalid request.'));
        }
        return;
      }
      if (!res.ok) {
        const text = await res.text();
        throw new Error(`${res.status} ${res.statusText}: ${text.slice(0, 200)}`);
      }
      const body = (await res.json()) as { data: DiscountSimulatorResult };
      if (!controller.signal.aborted) setResult(body.data);
    } catch (err) {
      if ((err as Error).name === 'AbortError') return;
      if (!controller.signal.aborted) setError(err as Error);
    } finally {
      if (!controller.signal.aborted) setIsLoading(false);
    }
  }, []);

  return { result, isLoading, error, fieldErrors, checkDiscount };
}
