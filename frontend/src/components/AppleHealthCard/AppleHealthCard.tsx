import { useState } from 'react';

import { useAppleHealth } from '../../hooks/useAppleHealth';
import { useAppleHealthConnect } from '../../hooks/useAppleHealthConnect';
import { hasAnyMetric, type AppleHealthSnapshot } from '../../types/appleHealth';
import AppleHealthMetrics from './AppleHealthMetrics';
import styles from './AppleHealthCard.module.css';
import ConnectModal from './ConnectModal';

export interface AppleHealthCardProps {
  /** Injectable for tests; defaults to the real fetch-backed hook. */
  useHook?: typeof useAppleHealth;
}

/**
 * Apple Health tile for the Health & Fitness page.
 *
 * Composition only. Data comes from useAppleHealth, the connect flow from
 * useAppleHealthConnect, the metric grid from AppleHealthMetrics, and the
 * modal from ConnectModal. What is left here is the one decision that is
 * genuinely this component's: which of six states the card is in.
 *
 * That decision used to be six independent JSX guards, each restating the
 * previous ones in negated form (`!isLoading && !error && data &&
 * data.connected && !data.stale && ...` — and a five-term metric check
 * written out twice). Nothing made them exhaustive or mutually exclusive;
 * they just happened to be. `cardState` makes them one switch, so a new
 * state is a compile-time obligation rather than a seventh guard that has
 * to remember to exclude the other six.
 */

type CardState =
  | { kind: 'loading' }
  | { kind: 'error' }
  | { kind: 'disconnected' }
  | { kind: 'stale' }
  | { kind: 'awaiting-first-push' }
  | { kind: 'ready'; snapshot: AppleHealthSnapshot };

function cardState(
  data: AppleHealthSnapshot | null,
  isLoading: boolean,
  error: Error | null,
): CardState {
  if (isLoading) return { kind: 'loading' };
  if (error) return { kind: 'error' };
  if (!data || !data.connected) return { kind: 'disconnected' };
  if (data.stale) return { kind: 'stale' };
  if (!hasAnyMetric(data)) return { kind: 'awaiting-first-push' };
  return { kind: 'ready', snapshot: data };
}

function Skeleton() {
  return (
    <div className={styles.skeleton} aria-busy="true" aria-label="Loading Apple Health data">
      <div className={styles.skeletonBar} style={{ width: '40%' }} />
      <div className={styles.skeletonGrid}>
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className={styles.skeletonTile} />
        ))}
      </div>
    </div>
  );
}

export default function AppleHealthCard({ useHook = useAppleHealth }: AppleHealthCardProps) {
  const { data, isLoading, error, refetch } = useHook();
  const [modalOpen, setModalOpen] = useState(false);
  const { state: connectState, reset: resetConnect, connect } = useAppleHealthConnect();

  const openConnectModal = () => {
    resetConnect();
    setModalOpen(true);
  };

  const closeModal = () => {
    setModalOpen(false);
    // A token was just minted, so the integration now exists server-side;
    // re-read rather than leaving the card disconnected until the next poll.
    if (connectState.status === 'showing-token') refetch();
  };

  const state = cardState(data ?? null, isLoading, error);

  return (
    <div className={styles.card}>
      <div className={styles.cardHead}>
        <p className={styles.cardTitle}>Apple Health</p>
        {/* Keyed off the snapshot, not `state`, on purpose: useFetch keeps
            the previous data through a failed refresh, and a live sync that
            hit one bad poll is still live. */}
        {data?.connected && !data.stale && (
          <span className={styles.liveDot} aria-label="Live" title="Receiving pushes" />
        )}
      </div>

      {state.kind === 'loading' && <Skeleton />}

      {state.kind === 'error' && (
        <div className={styles.errorState} role="alert">
          <p>Couldn&rsquo;t reach Apple Health data.</p>
          <button type="button" className={styles.retryBtn} onClick={refetch}>
            Retry
          </button>
        </div>
      )}

      {state.kind === 'disconnected' && (
        <div className={styles.connectPanel}>
          <p className={styles.connectDesc}>
            Push steps, resting HR, HRV, sleep and VO2max from your iPhone via an iOS
            Shortcut. No live cloud API exists for HealthKit, so this is a manual,
            user-controlled sync — set it up once.
          </p>
          <button type="button" className={styles.connectBtn} onClick={openConnectModal}>
            Connect Apple Health
          </button>
        </div>
      )}

      {state.kind === 'stale' && (
        <div className={styles.stalePanel} role="status">
          <p className={styles.staleTitle}>Sync has gone quiet</p>
          <p className={styles.connectDesc}>
            No push received recently — the Shortcut may have stopped running on your
            device. Reissue a token if you need to reconfigure it.
          </p>
          <button type="button" className={styles.connectBtn} onClick={openConnectModal}>
            Reissue sync token
          </button>
        </div>
      )}

      {state.kind === 'awaiting-first-push' && (
        <div className={styles.emptyPanel}>
          <p className={styles.connectDesc}>
            Connected — waiting for the first push from your Shortcut.
          </p>
        </div>
      )}

      {state.kind === 'ready' && <AppleHealthMetrics snapshot={state.snapshot} />}

      {modalOpen && (
        <ConnectModal state={connectState} onConnect={connect} onClose={closeModal} />
      )}
    </div>
  );
}
