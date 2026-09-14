import { useEffect, useRef, useState } from 'react';

import { useFetch } from './useFetch';

export type SyncJobProgress = 'processing' | 'completed' | 'failed' | 'stalled';
export type SyncJobStalledReason =
  | 'no_worker_running'
  | 'worker_not_responding'
  | 'worker_timeout'
  | null;

export interface SyncJobView {
  job_id: string;
  status: string;
  progress: SyncJobProgress;
  stalled_reason: SyncJobStalledReason;
  retrying: boolean;
  attempt: number;
  worker_enabled: boolean;
  worker_alive: boolean | null;
  error_text: string | null;
  requested_at: string | null;
  picked_at: string | null;
  completed_at: string | null;
}

export interface UseSyncJobResult {
  job: SyncJobView | null;
  /** False once the job reached a terminal progress, or the client-side
   * polling ceiling was hit. */
  isPolling: boolean;
  /** True only when polling stopped because of the 15-minute client
   * ceiling — NOT the same as progress === 'stalled', which is a
   * server-derived verdict. */
  timedOut: boolean;
  /** Set once the status endpoint has failed MAX_CONSECUTIVE_ERRORS times
   * in a row (the job row was deleted, the backend is down, ...). Polling
   * stops at that point: without this the caller would sit on "Syncing…"
   * for the full 15 minutes while every poll silently 404s. */
  error: Error | null;
}

const TERMINAL: ReadonlySet<SyncJobProgress> = new Set(['completed', 'failed', 'stalled']);
const FAST_POLL_MS = 2_000;
const SLOW_POLL_MS = 5_000;
const FAST_POLL_WINDOW_MS = 30_000;
const HARD_CEILING_MS = 15 * 60 * 1000;
// One failed poll is usually a blip (sleeping laptop, redeploy). Three in
// a row is a real problem worth telling the user about.
const MAX_CONSECUTIVE_ERRORS = 3;

/**
 * Polls GET /api/v1/integrations/{slug}/sync/status?job_id=<id> via the
 * existing useFetch polling primitive (refreshInterval + skip), so 401
 * handling, abort-on-unmount, and envelope unwrap are shared rather than
 * reimplemented in a hand-rolled setInterval (FEAT-144).
 *
 * Polls every 2s for the first 30s, then every 5s, until the server
 * reports a terminal progress (completed|failed|stalled) or a 15-minute
 * client-side ceiling is reached. The ceiling only stops polling — it
 * never invents a "stalled" verdict; that classification is server-only
 * (see backend sync_status.derive_job_view).
 */
export function useSyncJob(slug: string, jobId: string | null): UseSyncJobResult {
  const startRef = useRef<number | null>(null);
  const [interval, setPollInterval] = useState(FAST_POLL_MS);
  const [timedOut, setTimedOut] = useState(false);

  // Latched terminal view. `skip` below depends on it, and useFetch nulls
  // `data` the instant skip flips true — so the terminal view is kept here
  // rather than read back off `data`, which would otherwise disappear from
  // the hook's return value the render after it arrived.
  const [finalJob, setFinalJob] = useState<SyncJobView | null>(null);
  const failuresRef = useRef(0);
  const [pollError, setPollError] = useState<Error | null>(null);

  useEffect(() => {
    startRef.current = jobId ? Date.now() : null;
    setPollInterval(FAST_POLL_MS);
    setTimedOut(false);
    setFinalJob(null);
    failuresRef.current = 0;
    setPollError(null);
  }, [jobId]);

  const url = jobId
    ? `/api/v1/integrations/${slug}/sync/status?job_id=${encodeURIComponent(jobId)}`
    : '';

  const terminal = finalJob !== null;

  // Stop polling on a terminal verdict. Without `terminal` in `skip`, a
  // job that settles on 'stalled' — which Integrations.tsx deliberately
  // keeps mounted so the card banner persists — would keep hitting
  // /sync/status every 5s for as long as the tab stayed open.
  const { data, error } = useFetch<SyncJobView>(url, {
    skip: !jobId || timedOut || terminal || pollError !== null,
    refreshInterval: interval,
  });

  useEffect(() => {
    if (!data) return;
    failuresRef.current = 0;
    if (TERMINAL.has(data.progress)) setFinalJob(data);
  }, [data]);

  // A poll that keeps failing must surface, not be swallowed into a
  // permanent "Syncing…" — useFetch already wiped the token on a 401, so
  // the remaining cases (404 job gone, 5xx, network down) are ones the
  // user needs to hear about.
  useEffect(() => {
    if (!error) return;
    failuresRef.current += 1;
    if (failuresRef.current >= MAX_CONSECUTIVE_ERRORS) setPollError(error);
  }, [error]);

  useEffect(() => {
    if (!jobId || terminal || pollError || !startRef.current) return;
    const elapsed = Date.now() - startRef.current;
    if (elapsed > HARD_CEILING_MS) {
      setTimedOut(true);
      return;
    }
    setPollInterval(elapsed > FAST_POLL_WINDOW_MS ? SLOW_POLL_MS : FAST_POLL_MS);
  }, [jobId, terminal, pollError, data]);

  return {
    job: finalJob ?? data,
    isPolling: Boolean(jobId) && !timedOut && !terminal && pollError === null,
    timedOut,
    error: pollError,
  };
}
