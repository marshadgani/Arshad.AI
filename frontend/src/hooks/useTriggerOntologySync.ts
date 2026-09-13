/**
 * Mutation hook for POST /api/v1/obsidian/ontology/sync.
 *
 * Kept separate from useOntologyStatus/useOntologyEntities because it's a
 * write, not a poll — it owns its own in-flight/result/error state instead
 * of piggy-backing on a read hook's shape.
 */

import { useState } from 'react';

import { clearToken, getToken } from '../auth/tokenStorage';
import type {
  TriggerOntologySyncRequest,
  TriggerOntologySyncResponse,
} from '../types/ontology';

export interface UseTriggerOntologySyncResult {
  trigger: (body?: TriggerOntologySyncRequest) => Promise<void>;
  isSyncing: boolean;
  result: TriggerOntologySyncResponse | null;
  error: Error | null;
}

export function useTriggerOntologySync(): UseTriggerOntologySyncResult {
  const [isSyncing, setIsSyncing] = useState(false);
  const [result, setResult] = useState<TriggerOntologySyncResponse | null>(null);
  const [error, setError] = useState<Error | null>(null);

  async function trigger(body: TriggerOntologySyncRequest = {}): Promise<void> {
    setIsSyncing(true);
    setError(null);
    try {
      const token = getToken();
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (token) headers.Authorization = `Bearer ${token}`;

      const resp = await fetch('/api/v1/obsidian/ontology/sync', {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
      });

      if (resp.status === 401) {
        clearToken();
        window.location.href = '/login';
        return;
      }
      if (!resp.ok) {
        const text = await resp.text();
        throw new Error(`${resp.status} ${resp.statusText}: ${text.slice(0, 200)}`);
      }
      const json = (await resp.json()) as { data: TriggerOntologySyncResponse };
      setResult(json.data);
    } catch (err) {
      setError(err instanceof Error ? err : new Error('Ontology sync failed'));
    } finally {
      setIsSyncing(false);
    }
  }

  return { trigger, isSyncing, result, error };
}
