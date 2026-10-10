/** Days-of-cover and travel-window stockout alerts for /shopify. */

import { useFetch } from './useFetch';
import type { InventoryCoverResponse } from '../types/shopify';

export interface UseShopifyInventoryCoverResult {
  inventory: InventoryCoverResponse | null;
  isLoading: boolean;
  error: Error | null;
  refresh: () => void;
}

// Matches the backend's 120s cache TTL.
const POLL_MS = 120_000;

export function useShopifyInventoryCover(): UseShopifyInventoryCoverResult {
  const { data, isLoading, error, refetch } = useFetch<InventoryCoverResponse>(
    '/api/v1/shopify/inventory-cover',
    { refreshInterval: POLL_MS },
  );
  return { inventory: data, isLoading, error, refresh: refetch };
}
