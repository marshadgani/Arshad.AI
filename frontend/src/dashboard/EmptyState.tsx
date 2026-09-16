import styles from './Dashboard.module.css';

export interface EmptyStateProps {
  message: string;
}

/**
 * Pairs with `CardSkeleton`: render this for `data === []` (a real,
 * resolved, zero-item response), never for `data === null` (still loading).
 */
export function EmptyState({ message }: EmptyStateProps) {
  return <div className={styles.emptyState}>{message}</div>;
}
