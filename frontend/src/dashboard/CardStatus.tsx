import styles from './Dashboard.module.css';

export interface CardSkeletonProps {
  /** Number of shimmering placeholder rows to render. */
  rows?: number;
}

// Shared by every list-shaped widget so a still-loading card (data === null)
// reads as "loading" instead of rendering the same blank list a genuinely
// empty result would.
export function CardSkeleton({ rows = 3 }: CardSkeletonProps) {
  return (
    <div aria-hidden="true">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className={styles.skeletonLine} style={{ width: `${85 - i * 12}%` }} />
      ))}
    </div>
  );
}

export interface EmptyStateProps {
  message: string;
}

export function EmptyState({ message }: EmptyStateProps) {
  return <div className={styles.emptyState}>{message}</div>;
}
