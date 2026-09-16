import styles from './Dashboard.module.css';

export interface CardSkeletonProps {
  /**
   * Row count — should match the typical item count for this widget so the
   * skeleton height matches the loaded state and avoids layout shift.
   * Defaults to 3 (most list widgets show 3 items).
   */
  rows?: number;
}

/**
 * Shared by every list-shaped widget so a still-loading card (`data ===
 * null`) reads as "loading" instead of rendering the same blank list a
 * genuinely empty result (`data === []`) would — see `EmptyState`.
 */
export function CardSkeleton({ rows = 3 }: CardSkeletonProps) {
  return (
    <div aria-hidden="true">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className={styles.skeletonLine} style={{ width: `${Math.max(30, 85 - i * 12)}%` }} />
      ))}
    </div>
  );
}
