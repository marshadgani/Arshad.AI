/**
 * The "Sync now" action for brokerage holdings: fan out a sync request per
 * connected broker, then refresh exactly once.
 *
 * Split out of useFinanceHoldings so that read state (useFetch) and write
 * state (this) are separate concerns rather than one hook owning both. The
 * transport itself belongs to neither and lives in api/integrations.ts.
 *
 * Takes the broker list rather than calling useFinanceHoldings itself:
 * depending upward on its own consumer would make the pair mutually
 * recursive and untestable in isolation.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { syncIntegration } from '../api/integrations';
import type { BrokerHoldings } from '../types/finance';

export interface UseBrokerSyncResult {
  syncAll: () => void;
  isSyncing: boolean;
  syncError: Error | null;
}

/**
 * @param brokers  Connected brokers, or null before the first load.
 * @param onSettled Called once after all requests settle, whatever the
 *                  outcome — a partial success must still be shown, and a
 *                  stale read beats a blank one.
 */
export function useBrokerSync(
  brokers: BrokerHoldings[] | null,
  onSettled: () => void,
): UseBrokerSyncResult {
  const [isSyncing, setIsSyncing] = useState(false);
  const [syncError, setSyncError] = useState<Error | null>(null);

  // The sync request itself is fire-and-forget on the server -- there is
  // nothing to abort -- but the settle callbacks below call setState. If
  // the user navigates away from /finance or /stocks (both mount this
  // hook) while a sync is in flight, those setState calls would otherwise
  // fire on an unmounted component: a React warning today, and a real
  // async gap that keeps the closure over `targets`/`brokers` (and
  // whatever `onSettled` itself closes over) alive in memory until the
  // promise settles instead of letting it get collected at unmount.
  const isMountedRef = useRef(true);
  useEffect(() => {
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  const syncAll = useCallback(() => {
    if (isSyncing || !brokers || brokers.length === 0) return;

    // A broker that needs reauth would just 400 on sync -- skip it rather
    // than manufacture a doomed request.
    const targets = brokers.filter((b) => !b.needs_reauth);
    if (targets.length === 0) {
      // Returning silently here left the button looking functional while
      // doing nothing at all -- say why instead of swallowing the click.
      setSyncError(new Error('Reconnect your broker before syncing.'));
      return;
    }

    setIsSyncing(true);
    setSyncError(null);

    Promise.allSettled(targets.map((b) => syncIntegration(b.broker)))
      .then((results) => {
        // The user-facing message is deliberately one generic sentence, not
        // the upstream status text — exposing the raw reason risks leaking
        // upstream error detail. The reason still goes to the console so a
        // failure is not undebuggable six months from now.
        let anyFailed = false;
        results.forEach((result, i) => {
          if (result.status !== 'rejected') return;
          anyFailed = true;
          // eslint-disable-next-line no-console
          console.error(`Broker sync failed for "${targets[i].broker}":`, result.reason);
        });
        if (anyFailed && isMountedRef.current) {
          setSyncError(new Error('One or more brokers failed to sync.'));
        }
      })
      .finally(() => {
        if (!isMountedRef.current) return;
        setIsSyncing(false);
        onSettled();
      });
  }, [brokers, isSyncing, onSettled]);

  return { syncAll, isSyncing, syncError };
}
