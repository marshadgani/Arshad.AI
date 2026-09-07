import { useState } from 'react';

import { getToken } from '../../auth/tokenStorage';
import { useAppleHealth } from '../../hooks/useAppleHealth';
import {
  formatCount,
  formatMetric,
  timeAgo,
} from '../../utils/healthFormat';
import styles from './AppleHealthCard.module.css';

export interface AppleHealthCardProps {
  /** Injectable for tests; defaults to the real fetch-backed hook. */
  useHook?: typeof useAppleHealth;
}

interface ConnectState {
  status: 'idle' | 'connecting' | 'showing-token' | 'error';
  ingestToken: string | null;
  errorMessage: string | null;
}

const INGEST_URL = `${window.location.origin}/api/v1/apple-health/ingest`;

// ── Connect / re-issue-token modal ──────────────────────────────────────

function ConnectModal({
  state,
  onConnect,
  onClose,
}: {
  state: ConnectState;
  onConnect: () => void;
  onClose: () => void;
}) {
  const [copied, setCopied] = useState(false);

  const copyToken = async () => {
    if (!state.ingestToken) return;
    try {
      await navigator.clipboard.writeText(state.ingestToken);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard API can be blocked (permissions, insecure context); the
      // token is still selectable/visible in the <code> block below.
    }
  };

  return (
    <div className={styles.modalBackdrop} role="presentation" onClick={onClose}>
      <div
        className={styles.modal}
        role="dialog"
        aria-modal="true"
        aria-labelledby="apple-health-modal-title"
        onClick={(e) => e.stopPropagation()}
      >
        {state.status === 'showing-token' && state.ingestToken ? (
          <>
            <h2 id="apple-health-modal-title" className={styles.modalTitle}>
              One-time sync token
            </h2>
            <p className={styles.modalDesc}>
              This token is shown once. Paste it into your iOS Shortcut&rsquo;s
              &ldquo;Get Contents of URL&rdquo; header — losing it means reconnecting to
              mint a new one.
            </p>
            <div className={styles.tokenRow}>
              <code className={styles.tokenValue}>{state.ingestToken}</code>
              <button type="button" className={styles.copyBtn} onClick={copyToken}>
                {copied ? 'Copied' : 'Copy'}
              </button>
            </div>

            <div className={styles.instructions}>
              <p className={styles.instructionsTitle}>Shortcut setup</p>
              <ol>
                <li>Create a new Shortcut → add &ldquo;Get Contents of URL&rdquo;.</li>
                <li>
                  URL: <code>{INGEST_URL}</code>
                </li>
                <li>Method: POST · Request Body: JSON.</li>
                <li>
                  Headers: <code>Authorization</code> ={' '}
                  <code>Bearer {'<the token above>'}</code>
                </li>
                <li>
                  Body keys (all optional): <code>resting_heart_rate</code>,{' '}
                  <code>heart_rate_variability_ms</code>, <code>sleep_hours</code>,{' '}
                  <code>active_energy_kcal</code>, <code>steps</code>,{' '}
                  <code>vo2_max</code>.
                </li>
                <li>Automate it hourly, or run on &ldquo;App closed&rdquo; for Health.</li>
              </ol>
            </div>

            <div className={styles.modalActions}>
              <button type="button" className={styles.primaryBtn} onClick={onClose}>
                Done — I&rsquo;ve saved it
              </button>
            </div>
          </>
        ) : (
          <>
            <h2 id="apple-health-modal-title" className={styles.modalTitle}>
              Connect Apple Health
            </h2>
            <p className={styles.modalDesc}>
              Apple doesn&rsquo;t offer a cloud API for HealthKit — your phone has to push
              data to us instead of us pulling it. Connecting mints a one-time bearer
              token for an iOS Shortcut you control to POST your health data on a
              schedule. Nothing is ever written to a database; each push only lives in a
              short-TTL cache until the next one arrives.
            </p>
            {state.status === 'error' && (
              <div className={styles.modalErr} role="alert">
                {state.errorMessage}
              </div>
            )}
            <div className={styles.modalActions}>
              <button
                type="button"
                className={styles.secondaryBtn}
                onClick={onClose}
                disabled={state.status === 'connecting'}
              >
                Cancel
              </button>
              <button
                type="button"
                className={styles.primaryBtn}
                onClick={onConnect}
                disabled={state.status === 'connecting'}
              >
                {state.status === 'connecting' ? 'Connecting…' : 'Generate token'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ── Skeleton / loading state ─────────────────────────────────────────────

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

// ── Main component ────────────────────────────────────────────────────────

export default function AppleHealthCard({ useHook = useAppleHealth }: AppleHealthCardProps) {
  const { data, isLoading, error, refetch } = useHook();
  const [modalOpen, setModalOpen] = useState(false);
  const [connectState, setConnectState] = useState<ConnectState>({
    status: 'idle',
    ingestToken: null,
    errorMessage: null,
  });

  const openConnectModal = () => {
    setConnectState({ status: 'idle', ingestToken: null, errorMessage: null });
    setModalOpen(true);
  };

  const closeModal = () => {
    setModalOpen(false);
    if (connectState.status === 'showing-token') refetch();
  };

  const doConnect = async () => {
    setConnectState((s) => ({ ...s, status: 'connecting', errorMessage: null }));
    try {
      const token = getToken();
      const res = await fetch('/api/v1/integrations/apple_health/connect', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({}),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body?.error?.message ?? `HTTP ${res.status}`);
      const ingestToken = body?.data?.ingest_token as string | null;
      if (!ingestToken) {
        throw new Error('Server did not return an ingest token.');
      }
      setConnectState({ status: 'showing-token', ingestToken, errorMessage: null });
    } catch (e: unknown) {
      setConnectState({
        status: 'error',
        ingestToken: null,
        errorMessage: (e as Error).message,
      });
    }
  };

  return (
    <div className={styles.card}>
      <div className={styles.cardHead}>
        <p className={styles.cardTitle}>Apple Health</p>
        {data?.connected && !data.stale && (
          <span className={styles.liveDot} aria-label="Live" title="Receiving pushes" />
        )}
      </div>

      {isLoading && <Skeleton />}

      {!isLoading && error && (
        <div className={styles.errorState} role="alert">
          <p>Couldn&rsquo;t reach Apple Health data.</p>
          <button type="button" className={styles.retryBtn} onClick={refetch}>
            Retry
          </button>
        </div>
      )}

      {!isLoading && !error && data && !data.connected && (
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

      {!isLoading && !error && data && data.connected && data.stale && (
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

      {!isLoading &&
        !error &&
        data &&
        data.connected &&
        !data.stale &&
        data.resting_heart_rate == null &&
        data.steps == null &&
        data.sleep_hours == null &&
        data.active_energy_kcal == null &&
        data.vo2_max == null && (
          <div className={styles.emptyPanel}>
            <p className={styles.connectDesc}>
              Connected — waiting for the first push from your Shortcut.
            </p>
          </div>
        )}

      {!isLoading &&
        !error &&
        data &&
        data.connected &&
        !data.stale &&
        (data.resting_heart_rate != null ||
          data.steps != null ||
          data.sleep_hours != null ||
          data.active_energy_kcal != null ||
          data.vo2_max != null) && (
          <>
            <div className={styles.metricsGrid}>
              <div className={styles.metric}>
                <div className={styles.metricVal}>
                  {formatMetric(data.resting_heart_rate, ' bpm')}
                </div>
                <div className={styles.metricKey}>Resting HR</div>
              </div>
              <div className={styles.metric}>
                <div className={styles.metricVal}>
                  {formatMetric(data.heart_rate_variability_ms, ' ms')}
                </div>
                <div className={styles.metricKey}>HRV</div>
              </div>
              <div className={styles.metric}>
                <div className={styles.metricVal}>{formatMetric(data.sleep_hours, 'h', 1)}</div>
                <div className={styles.metricKey}>Sleep</div>
              </div>
              <div className={styles.metric}>
                <div className={styles.metricVal}>
                  {formatMetric(data.active_energy_kcal, ' kcal')}
                </div>
                <div className={styles.metricKey}>Active Energy</div>
              </div>
              <div className={styles.metric}>
                <div className={styles.metricVal}>
                  {formatCount(data.steps)}
                </div>
                <div className={styles.metricKey}>Steps</div>
              </div>
              <div className={styles.metric}>
                <div className={styles.metricVal}>{formatMetric(data.vo2_max, '', 1)}</div>
                <div className={styles.metricKey}>VO2 Max</div>
              </div>
            </div>
            {timeAgo(data.received_at) && (
              <p className={styles.freshness}>Last push {timeAgo(data.received_at)}</p>
            )}
          </>
        )}

      {modalOpen && (
        <ConnectModal state={connectState} onConnect={doConnect} onClose={closeModal} />
      )}
    </div>
  );
}
