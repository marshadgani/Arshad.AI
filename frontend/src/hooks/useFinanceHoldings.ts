/**
 * Brokerage holdings for the /finance and /stocks pages.
 *
 * A composition of two single-purpose hooks -- useFetch for the read,
 * useBrokerSync for the write -- exposed as one object so BrokerageHoldings
 * still consumes a single hook and knows nothing about the split.
 *
 * No refreshInterval: holdings change at most once per day, when a
 * provider's sync() runs (see backend/src/integrations/personal/{upstox,
 * zerodha_kite}.py) -- polling would manufacture load for zero additional
 * freshness. syncAll() is the explicit alternative.
 */

import type { FinanceHoldingsResponse } from '../types/finance';
import { useBrokerSync } from './useBrokerSync';
import { useFetch } from './useFetch';

export interface UseFinanceHoldingsResult {
  data: FinanceHoldingsResponse | null;
  isLoading: boolean;
  error: Error | null;
  refetch: () => void;
  syncAll: () => void;
  isSyncing: boolean;
  syncError: Error | null;
}

export function useFinanceHoldings(): UseFinanceHoldingsResult {
  const { data, isLoading, error, refetch } = useFetch<FinanceHoldingsResponse>(
    '/api/v1/finance/holdings',
  );
  const { syncAll, isSyncing, syncError } = useBrokerSync(data?.brokers ?? null, refetch);

  return { data, isLoading, error, refetch, syncAll, isSyncing, syncError };
}
