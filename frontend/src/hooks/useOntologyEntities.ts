/**
 * Paginated, filterable list of tracked ontology entities
 * (GET /api/v1/obsidian/ontology/entities).
 *
 * The endpoint's envelope is `{ data: [...], total }` — `total` sits
 * alongside `data`, not nested inside it, so useFetch (which only unwraps
 * `body.data`) can't surface it. Rather than special-case useFetch for one
 * caller, this hook infers `hasMore` from page size instead: a full page
 * means there is probably another page; a short page means we've reached
 * the end. That's sufficient for a "Load more" control and avoids a second
 * source of truth for pagination state.
 */

import { useEffect, useState } from 'react';

import { getToken, clearToken } from '../auth/tokenStorage';
import type { OntologyEntity, OntologyEntityFilters } from '../types/ontology';

export interface UseOntologyEntitiesResult {
  entities: OntologyEntity[];
  isLoading: boolean;
  error: Error | null;
  hasMore: boolean;
  loadMore: () => void;
  refetch: () => void;
}

const PAGE_SIZE = 25;

function buildUrl(filters: OntologyEntityFilters, limit: number, offset: number): string {
  const params = new URLSearchParams();
  if (filters.domain) params.set('domain', filters.domain);
  if (filters.entity_type) params.set('entity_type', filters.entity_type);
  if (filters.sync_state) params.set('sync_state', filters.sync_state);
  params.set('limit', String(limit));
  params.set('offset', String(offset));
  return `/api/v1/obsidian/ontology/entities?${params.toString()}`;
}

export function useOntologyEntities(
  filters: OntologyEntityFilters,
): UseOntologyEntitiesResult {
  const [entities, setEntities] = useState<OntologyEntity[]>([]);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [tick, setTick] = useState(0);

  const filterKey = `${filters.domain ?? ''}|${filters.entity_type ?? ''}|${filters.sync_state ?? ''}`;

  // Filter change resets pagination — a new query is not "page 2" of the
  // old one.
  useEffect(() => {
    setOffset(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterKey]);

  useEffect(() => {
    const controller = new AbortController();
    setIsLoading(true);
    setError(null);

    const token = getToken();
    const headers: Record<string, string> = {};
    if (token) headers.Authorization = `Bearer ${token}`;

    fetch(buildUrl(filters, PAGE_SIZE, offset), { signal: controller.signal, headers })
      .then(async (res) => {
        if (res.status === 401) {
          clearToken();
          throw new Error('401 Unauthorized');
        }
        if (!res.ok) {
          const body = await res.text();
          throw new Error(`${res.status} ${res.statusText}: ${body.slice(0, 200)}`);
        }
        return res.json() as Promise<{ data: OntologyEntity[] }>;
      })
      .then((body) => {
        if (controller.signal.aborted) return;
        const page = body.data ?? [];
        setEntities((prev) => (offset === 0 ? page : [...prev, ...page]));
        setHasMore(page.length === PAGE_SIZE);
      })
      .catch((err: Error) => {
        if (err.name === 'AbortError') return;
        if (!controller.signal.aborted) setError(err);
      })
      .finally(() => {
        if (!controller.signal.aborted) setIsLoading(false);
      });

    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterKey, offset, tick]);

  return {
    entities,
    isLoading,
    error,
    hasMore,
    loadMore: () => setOffset((o) => o + PAGE_SIZE),
    refetch: () => {
      setOffset(0);
      setTick((t) => t + 1);
    },
  };
}
