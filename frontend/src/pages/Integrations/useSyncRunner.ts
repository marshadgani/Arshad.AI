import { useCallback, useEffect, useRef, useState } from 'react';

import { getToken } from '../../auth/tokenStorage';
import { isTerminalPhase, useSyncJob } from '../../hooks/useSyncJob';

/**
 * Drives POST /{slug}/sync and, for queue-backed providers, the polling
 * that follows it.
 *
 * The honesty rule this exists to protect (CLAUDE.md FEAT-144): a
 * queue-backed sync has NOT happened when the POST returns — only an
 * enqueue has. The endpoint says so with `mode: 'queued'`, and the UI
 * must keep the card in a pending state until GET /{slug}/sync/status
 * reports a terminal phase, rather than flashing a success toast.
 *
 * That rule used to be spread across the page component as a mode
 * branch, a `pollingSlug` state, a `queued` flag threaded through a
 * try/finally, and a separate effect watching the job phase — four
 * pieces that had to stay consistent with each other, in the middle of
 * 600 lines of unrelated modal handling. Here it is one unit, and the
 * page only has to know "did this leave a sync in flight?".
 */

export type SyncStart =
  | { mode: 'queued' }
  | { mode: 'completed'; summary: string };

interface SyncRunnerOptions {
  /** Called once when a polled job reaches a terminal phase. */
  onSettled: (message: string) => void;
}

export function useSyncRunner({ onSettled }: SyncRunnerOptions) {
  // Which card is showing a pending state while its enqueued job is
  // polled. Keyed by slug so multiple cards could in principle poll
  // independently; only one useSyncJob instance is mounted because this
  // app only ever has one sync in flight from the user's own clicks.
  const [pollingSlug, setPollingSlug] = useState<string | null>(null);
  const syncJob = useSyncJob();

  // Held in a ref so a caller passing an inline arrow function (the
  // normal case) doesn't re-run the terminal-phase effect on every
  // render and re-fire onSettled for the same job.
  const onSettledRef = useRef(onSettled);
  onSettledRef.current = onSettled;

  const startSync = useCallback(
    async (slug: string): Promise<SyncStart> => {
      const token = getToken();
      const res = await fetch(`/api/v1/integrations/${slug}/sync`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body?.error?.message ?? `HTTP ${res.status}`);

      if (body?.data?.mode === 'queued') {
        setPollingSlug(slug);
        syncJob.start(
          body.data.job_id as string,
          `/api/v1/integrations/${slug}/sync/status`,
        );
        return { mode: 'queued' };
      }
      return { mode: 'completed', summary: body?.data?.summary ?? 'Synced' };
    },
    [syncJob],
  );

  const phase = syncJob.state.phase;
  useEffect(() => {
    if (!pollingSlug || !isTerminalPhase(phase)) return;
    const message = syncJob.state.message;
    setPollingSlug(null);
    syncJob.reset();
    onSettledRef.current(message);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, pollingSlug]);

  return {
    pollingSlug,
    /** Live progress text for the card currently polling ('' otherwise). */
    message: syncJob.state.message,
    startSync,
  };
}
