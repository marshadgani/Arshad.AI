import { useCallback, useEffect, useMemo, useState } from 'react';

import { getToken } from '../../auth/tokenStorage';
import type { IntegrationItem } from './types';

/**
 * Owns loading GET /api/v1/integrations and grouping the result by
 * category. Extracted from the page component so that "how the list is
 * fetched" and "what the list looks like" are separately readable and
 * separately changeable — the page was previously doing both, plus three
 * modals and a polling loop, in one 600-line function.
 *
 * Returns the same { items, loading, error } triple as the rest of the
 * app's data hooks (see .claude/rules/frontend.md), with `refetch` for
 * the actions that must resync after mutating state.
 */
export function useIntegrationsList() {
  const [items, setItems] = useState<IntegrationItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refetch = useCallback(async () => {
    const token = getToken();
    if (!token) return;
    setLoading(true);
    try {
      const res = await fetch('/api/v1/integrations', {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const body = (await res.json()) as { data: IntegrationItem[] };
      setItems(body.data ?? []);
      setError(null);
    } catch (e: unknown) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refetch();
  }, [refetch]);

  const grouped = useMemo(() => {
    const sections: Record<string, IntegrationItem[]> = {};
    for (const it of items) {
      (sections[it.category] ??= []).push(it);
    }
    return Object.entries(sections).sort(([a], [b]) => a.localeCompare(b));
  }, [items]);

  return { items, grouped, loading, error, refetch };
}
