import { useEffect } from 'react';

import { useSyncJob } from '../../hooks/useSyncJob';
import type { SyncJobView } from '../../hooks/useSyncJob';

export interface SyncJobWatcherProps {
  slug: string;
  jobId: string;
  onUpdate: (view: SyncJobView) => void;
  /** Called once polling gives up after repeated status-endpoint failures,
   * so the page can stop showing "Syncing…" for a job it can no longer
   * observe. */
  onError?: (error: Error) => void;
}

/**
 * Headless controller — subscribes to useSyncJob and forwards every update
 * to the parent. Exists so a page can start one poll per in-flight sync
 * job without calling hooks conditionally or inside a loop (rules of
 * hooks): each tracked job gets its own mounted instance instead.
 */
export default function SyncJobWatcher({
  slug,
  jobId,
  onUpdate,
  onError,
}: SyncJobWatcherProps) {
  const { job, error } = useSyncJob(slug, jobId);

  useEffect(() => {
    if (job) onUpdate(job);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job]);

  useEffect(() => {
    if (error) onError?.(error);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [error]);

  return null;
}
