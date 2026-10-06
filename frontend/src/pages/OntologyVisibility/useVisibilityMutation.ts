/**
 * Custom hook that owns the PATCH /api/v1/ontology/entities/visibility call.
 *
 * Responsibilities:
 *  - tracking which entity ids are in-flight (`changing`)
 *  - surfacing a human-readable `mutationError`
 *  - recording whether any successful change has occurred (`changed`)
 *  - handling 401 → redirect to login
 *
 * The hook intentionally does NOT own the `overrides` or `selected` state; those
 * belong to the page component because they are derived from the entity list, not
 * from the mutation itself.  On success, `mutate` returns the ids that were passed
 * in so the caller can update its own state.  On failure, it returns `null`.
 */

import { useState } from 'react';

import { clearToken, getToken } from '../../auth/tokenStorage';
import type { Visibility } from './types';

export type UseVisibilityMutationResult = {
  changing: Set<string>;
  mutationError: string | null;
  changed: boolean;
  mutate: (ids: readonly string[], visibility: Visibility) => Promise<readonly string[] | null>;
};

async function describeFailure(resp: Response): Promise<string> {
  if (resp.status === 404) {
    return 'Some of these entities no longer exist. Reloading the list.';
  }
  let serverMessage = '';
  try {
    const body = (await resp.json()) as { error?: { message?: unknown } };
    if (typeof body.error?.message === 'string') serverMessage = ` ${body.error.message}`;
  } catch (err) {
    console.error('Could not parse visibility error body', err);
  }
  return `Could not update visibility (${resp.status}).${serverMessage}`;
}

export function useVisibilityMutation(): UseVisibilityMutationResult {
  const [changing, setChanging] = useState<Set<string>>(new Set());
  const [mutationError, setMutationError] = useState<string | null>(null);
  const [changed, setChanged] = useState(false);

  async function mutate(
    ids: readonly string[],
    visibility: Visibility,
  ): Promise<readonly string[] | null> {
    setMutationError(null);
    setChanging((prev) => new Set([...prev, ...ids]));
    try {
      const token = getToken();
      const resp = await fetch('/api/v1/ontology/entities/visibility', {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ ids, visibility }),
      });
      if (resp.status === 401) {
        clearToken();
        window.location.href = '/login';
        return null;
      }
      if (!resp.ok) {
        setMutationError(await describeFailure(resp));
        return null;
      }
      setChanged(true);
      return ids;
    } catch (err) {
      console.error('Visibility mutation network error', err);
      setMutationError('Could not update visibility: network error.');
      return null;
    } finally {
      setChanging((prev) => {
        const next = new Set(prev);
        ids.forEach((id) => next.delete(id));
        return next;
      });
    }
  }

  return { changing, mutationError, changed, mutate };
}
