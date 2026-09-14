import { useEffect, useRef } from 'react';

import styles from './ConnectResultBanner.module.css';

export type ConnectResultKind = 'success' | 'error';

export interface ConnectResultBannerProps {
  /** 'success' announces politely; 'error' interrupts (role="alert"). */
  kind: ConnectResultKind;
  /** Short, bold headline — e.g. "GitHub connected" or "Connect failed". */
  title: string;
  /** Optional supporting detail — e.g. the human-readable error reason. */
  message?: string;
  onDismiss: () => void;
  /** 0 disables the timer; the user must dismiss manually. */
  autoDismissMs?: number;
}

/**
 * Surfaces the outcome of a full-page OAuth redirect round trip (connect an
 * additional provider while already signed in — see
 * backend/src/integrations/personal/attach_callback.py) back on the page
 * the user started from.
 *
 * A toast alone under-serves this moment: the browser just did a hard
 * navigation away and back, so there is no continuity of context for the
 * user to anchor a small transient toast to. This renders as a persistent,
 * high-contrast banner anchored to the top of the content instead, and
 * still self-dismisses so it doesn't become clutter.
 *
 * Generic over any connect-style success/failure outcome (OAuth, API key,
 * store-domain flows) — nothing here is GitHub/Gmail/Calendar-specific —
 * so any future provider gets the same treatment for free.
 */
export function ConnectResultBanner({
  kind,
  title,
  message,
  onDismiss,
  autoDismissMs = 6000,
}: ConnectResultBannerProps) {
  const onDismissRef = useRef(onDismiss);
  onDismissRef.current = onDismiss;

  useEffect(() => {
    if (autoDismissMs <= 0) return;
    const timer = setTimeout(() => onDismissRef.current(), autoDismissMs);
    return () => clearTimeout(timer);
  }, [autoDismissMs]);

  const isError = kind === 'error';

  return (
    <div
      className={`${styles.banner} ${isError ? styles.error : styles.success}`}
      role={isError ? 'alert' : 'status'}
      aria-live={isError ? 'assertive' : 'polite'}
    >
      <span className={styles.icon} aria-hidden="true">
        {isError ? '!' : '✓'}
      </span>
      <div className={styles.body}>
        <p className={styles.title}>{title}</p>
        {message && <p className={styles.message}>{message}</p>}
      </div>
      <button
        type="button"
        className={styles.dismiss}
        onClick={onDismiss}
        aria-label="Dismiss notification"
      >
        &times;
      </button>
    </div>
  );
}
