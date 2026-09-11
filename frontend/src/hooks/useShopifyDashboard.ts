/**
 * Shopify dashboard data for the /shopify page.
 *
 * Single endpoint, so this is a thin wrapper over useFetch — the interval
 * and AbortController are owned by useFetch itself, not duplicated here.
 */

import { useFetch } from './useFetch';
import type { ShopifyDashboard } from '../types/shopify';

export interface UseShopifyDashboardResult {
  dashboard: ShopifyDashboard | null;
  isLoading: boolean;
  error: Error | null;
}

// Matches the backend's 120s dashboard cache TTL — polling faster would
// just re-serve the same cached payload.
const DASHBOARD_POLL_MS = 120_000;

export function useShopifyDashboard(): UseShopifyDashboardResult {
  const { data, isLoading, error } = useFetch<ShopifyDashboard>(
    '/api/v1/shopify/dashboard',
    { refreshInterval: DASHBOARD_POLL_MS },
  );

  return { dashboard: data, isLoading, error };
}
