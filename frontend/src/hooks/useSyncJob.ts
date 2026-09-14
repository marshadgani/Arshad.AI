import { useCallback, useEffect, useRef, useState } from 'react';

import { getToken } from '../auth/tokenStorage';

/**
 * Polls a sync-status endpoint (GET /{slug}/sync/status or
 * /obsidian/sync/status — both return the shared shape produced by
 * backend/src/services/sync_status.py) until the job reaches a terminal
 * state. Used by Integrations.tsx and Obsidian.tsx instead of each page
 * re-implementing its own polling loop (which previously drifted into a
 * fake `setTimeout` in one of them). See CLAUDE.md FEAT-144.
 */

export type SyncPhase = 'idle' | 'running' | 'completed' | 'failed' | 'stalled';

export interface SyncJobState {
  phase: SyncPhase;
  message: string;
  jobId: string | null;
  attempt: number;
  error: string | null;
}

interface SyncStatusResponse {
  job_id: string;
  status: 'pending' | 'picked' | 'completed' | 'failed' | 'stalled';
  attempt: number;
  error: string | null;
  message: string | null;
}

const FAST_POLL_MS = 3_000;
const SLOW_POLL_MS = 15_000;
// A first-ever Gmail/GitHub ingest can legitimately run past 90s; rather
// than giving up, polling just slows down and the phase stays 'running'.
const SOFT_CEILING_MS = 120_000;

const IDLE_STATE: SyncJobState = {
  phase: 'idle',
  message: '',
  jobId: null,
  attempt: 0,
  error: null,
};

/**
 * Terminal for the UI, not just for the job: a stalled job cannot make
 * further progress without the worker being fixed, so polling it forever
 * would only keep a button disabled.
 */
export function isTerminalPhase(phase: SyncPhase): boolean {
  return phase === 'completed' || phase === 'failed' || phase === 'stalled';
}

function phaseFromStatus(status: SyncStatusResponse['status']): SyncPhase {
  if (status === 'pending' || status === 'picked') return 'running';
  return status;
}

function messageFor(phase: SyncPhase, body: SyncStatusResponse | null): string {
  if (phase === 'running') {
    const attempt = body?.attempt ?? 0;
    return attempt > 1 ? `Syncing… (attempt ${attempt})` : 'Syncing…';
  }
  if (phase === 'completed') return 'Synced';
  if (phase === 'failed') return `Sync failed: ${body?.error ?? 'unknown error'}`;
  if (phase === 'stalled') {
    return body?.message ?? 'Sync is stalled — the background worker may not be running.';
  }
  return '';
}

export function useSyncJob() {
  const [state, setState] = useState<SyncJobState>(IDLE_STATE);
  const pollRef = useRef<number | null>(null);
  const startedAtRef = useRef<number>(0);
  // Aborts whatever fetch is currently in flight so a slow response can
  // never land (and call setState) after stopPolling/reset/unmount — the
  // same convention useFetch.ts already uses. Without this, a fetch that
  // was in flight when the component unmounted still resolves and both
  // wastes the round trip and races a state update against nothing.
  const abortRef = useRef<AbortController | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current !== null) {
      window.clearTimeout(pollRef.current);
      pollRef.current = null;
    }
    abortRef.current?.abort();
    abortRef.current = null;
  }, []);

  const reset = useCallback(() => {
    stopPolling();
    setState(IDLE_STATE);
  }, [stopPolling]);

  const start = useCallback(
    (jobId: string, statusUrl: string) => {
      stopPolling();
      startedAtRef.current = Date.now();
      setState({ ...IDLE_STATE, phase: 'running', jobId, message: 'Queued…' });

      const poll = async () => {
        const controller = new AbortController();
        abortRef.current = controller;
        try {
          const token = getToken();
          const res = await fetch(`${statusUrl}?job_id=${jobId}`, {
            headers: token ? { Authorization: `Bearer ${token}` } : {},
            signal: controller.signal,
          });
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          const body = (await res.json()) as { data: SyncStatusResponse | null };

          if (controller.signal.aborted) return;

          if (body.data === null) {
            // Job not found yet (rare race) — keep polling as 'running'.
            scheduleNext('running');
            return;
          }

          const phase = phaseFromStatus(body.data.status);
          setState({
            phase,
            message: messageFor(phase, body.data),
            jobId,
            attempt: body.data.attempt,
            error: body.data.error,
          });

          if (isTerminalPhase(phase)) {
            stopPolling();
            return;
          }
          scheduleNext(phase);
        } catch {
          if (controller.signal.aborted) return;
          // Transient network error — keep polling rather than surfacing
          // a false failure for what may just be a dropped request.
          scheduleNext('running');
        }
      };

      const scheduleNext = (phase: SyncPhase) => {
        const elapsed = Date.now() - startedAtRef.current;
        const interval = elapsed > SOFT_CEILING_MS ? SLOW_POLL_MS : FAST_POLL_MS;
        if (elapsed > SOFT_CEILING_MS && phase === 'running') {
          setState((prev) => ({
            ...prev,
            message: 'Still syncing — this can take a few minutes',
          }));
        }
        pollRef.current = window.setTimeout(poll, interval);
      };

      poll();
    },
    [stopPolling],
  );

  useEffect(() => stopPolling, [stopPolling]);

  return { state, start, reset };
}
