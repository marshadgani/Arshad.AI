/** Unanswered Gmail threads matched to Shopify orders for /shopify. */

import { useFetch } from './useFetch';
import type { ServiceDebtResponse } from '../types/shopify';

export interface UseShopifyServiceDebtResult {
  serviceDebt: ServiceDebtResponse | null;
  isLoading: boolean;
  error: Error | null;
  refresh: () => void;
}

// Matches the backend's 120s cache TTL.
const POLL_MS = 120_000;

export function useShopifyServiceDebt(): UseShopifyServiceDebtResult {
  const { data, isLoading, error, refetch } = useFetch<ServiceDebtResponse>(
    '/api/v1/shopify/service-debt',
    { refreshInterval: POLL_MS },
  );
  return { serviceDebt: data, isLoading, error, refresh: refetch };
}
