/**
 * Shopify revenue/order trend data for the /shopify page's insights card.
 *
 * No refreshInterval: the backend caches this response for 900s, so
 * polling would just waste the shared 30/min Shopify rate bucket to
 * re-serve identical bytes. Freshness is user-driven — the caller wires
 * `refetch` to a "Refresh" button, and a `days` change fires a fresh
 * request because the URL changes (useFetch treats a new URL as a new
 * request).
 */

import { useFetch } from './useFetch';
import type { ShopifyInsights } from '../types/shopify';

export interface UseShopifyInsightsOptions {
  days?: 7 | 14 | 30;
  /** Suppress the fetch entirely — used when the store is not connected
   * or needs reauth, so this secondary request never fires alongside the
   * dashboard's own empty/reauth state. */
  skip?: boolean;
}

export interface UseShopifyInsightsResult {
  insights: ShopifyInsights | null;
  isLoading: boolean;
  error: Error | null;
  refetch: () => void;
}

export function useShopifyInsights(
  options?: UseShopifyInsightsOptions,
): UseShopifyInsightsResult {
  const { days = 14, skip = false } = options ?? {};

  const { data, isLoading, error, refetch } = useFetch<ShopifyInsights>(
    `/api/v1/shopify/insights?days=${days}`,
    { skip },
  );

  return { insights: data, isLoading, error, refetch };
}
