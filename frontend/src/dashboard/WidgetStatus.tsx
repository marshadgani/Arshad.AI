import { type ReactNode } from 'react';

import styles from './Dashboard.module.css';

export interface WidgetStatusProps {
  isLoading: boolean;
  error: Error | null;
  isEmpty: boolean;
  emptyMessage: ReactNode;
  /** Number of skeleton rows to render while loading. */
  skeletonRows?: number;
  children: ReactNode;
}

/**
 * The four-state contract every ingestion-backed dashboard card follows:
 * loading (skeleton), error (inline banner, no silent swallow), empty
 * (helpful copy — never a blank card), content (the card's own markup).
 *
 * Kept separate from CardHeader so a card can still show its header +
 * count while the body cycles through these states.
 */
export function WidgetStatus({
  isLoading,
  error,
  isEmpty,
  emptyMessage,
  skeletonRows = 3,
  children,
}: WidgetStatusProps) {
  if (isLoading) {
    return (
      <div className={styles.list} aria-busy="true" aria-live="polite">
        <span className={styles.srOnly}>Loading…</span>
        {Array.from({ length: skeletonRows }, (_, i) => (
          <div key={i} className={styles.skeletonRow} aria-hidden="true" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className={styles.stateError} role="alert">
        <span aria-hidden="true">⚠</span>
        <span>Couldn&apos;t load this — {error.message}</span>
      </div>
    );
  }

  if (isEmpty) {
    return <p className={styles.stateEmpty}>{emptyMessage}</p>;
  }

  return <>{children}</>;
}

export interface SourceBadgeProps {
  /** `"live"` | `"seed"` | undefined (endpoint doesn't report a mode). */
  mode?: string;
}

/**
 * Distinguishes rows derived from a real connected account (`live`) from
 * the Phase-A seed fallback (`seed`) — additive to the badge-less cards
 * that never had this ambiguity. Renders nothing when the endpoint didn't
 * report a mode, so opting a card in is a one-line change.
 */
export function SourceBadge({ mode }: SourceBadgeProps) {
  if (mode !== 'live' && mode !== 'seed') return null;
  const isLive = mode === 'live';
  return (
    <span
      className={isLive ? styles.badgeLive : styles.badgeSeed}
      title={isLive ? 'Derived from your connected account' : 'Sample data — connect an account for live data'}
    >
      {isLive ? 'Live' : 'Demo'}
    </span>
  );
}
