import { useState } from 'react';

import type { AppleHealthConnectState } from '../../hooks/useAppleHealthConnect';
import styles from './AppleHealthCard.module.css';

export interface ConnectModalProps {
  state: AppleHealthConnectState;
  onConnect: () => void;
  onClose: () => void;
}

/**
 * Two-phase modal: explain-and-mint, then show-the-token-once.
 *
 * Presentation only — it renders whatever state useAppleHealthConnect is
 * in and reports intent upward. It performs no fetch and holds no token of
 * its own, which is what lets the connect flow be tested without a DOM and
 * this file be read as markup.
 */

const INGEST_URL = `${window.location.origin}/api/v1/apple-health/ingest`;

function TokenPanel({ token }: { token: string }) {
  const [copied, setCopied] = useState(false);

  const copyToken = async () => {
    try {
      await navigator.clipboard.writeText(token);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard API can be blocked (permissions, insecure context); the
      // token is still selectable/visible in the <code> block below.
    }
  };

  return (
    <div className={styles.tokenRow}>
      <code className={styles.tokenValue}>{token}</code>
      <button type="button" className={styles.copyBtn} onClick={copyToken}>
        {copied ? 'Copied' : 'Copy'}
      </button>
    </div>
  );
}

function ShortcutInstructions() {
  return (
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
          <code>active_energy_kcal</code>, <code>steps</code>, <code>vo2_max</code>.
        </li>
        <li>Automate it hourly, or run on &ldquo;App closed&rdquo; for Health.</li>
      </ol>
    </div>
  );
}

export default function ConnectModal({ state, onConnect, onClose }: ConnectModalProps) {
  const showingToken = state.status === 'showing-token' && state.ingestToken;

  return (
    <div className={styles.modalBackdrop} role="presentation" onClick={onClose}>
      <div
        className={styles.modal}
        role="dialog"
        aria-modal="true"
        aria-labelledby="apple-health-modal-title"
        onClick={(e) => e.stopPropagation()}
      >
        {showingToken ? (
          <>
            <h2 id="apple-health-modal-title" className={styles.modalTitle}>
              One-time sync token
            </h2>
            <p className={styles.modalDesc}>
              This token is shown once. Paste it into your iOS Shortcut&rsquo;s
              &ldquo;Get Contents of URL&rdquo; header — losing it means reconnecting to
              mint a new one.
            </p>
            <TokenPanel token={state.ingestToken as string} />
            <ShortcutInstructions />
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
