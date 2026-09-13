/**
 * Ontology sync status summary for the /obsidian page's "Ontology" tab.
 *
 * Thin wrapper over useFetch — polls so a sync triggered from another tab
 * (or the hourly Airflow/queue-worker run) shows up without a manual
 * refresh. 20s matches the cadence of a running sync job, which is the
 * only time this value is likely to change mid-session.
 */

import { useFetch } from './useFetch';
import type { OntologyStatus } from '../types/ontology';

export interface UseOntologyStatusResult {
  status: OntologyStatus | null;
  isLoading: boolean;
  error: Error | null;
  refetch: () => void;
}

const STATUS_POLL_MS = 20_000;

export function useOntologyStatus(): UseOntologyStatusResult {
  const { data, isLoading, error, refetch } = useFetch<OntologyStatus>(
    '/api/v1/obsidian/ontology/status',
    { refreshInterval: STATUS_POLL_MS },
  );

  return { status: data, isLoading, error, refetch };
}
