import styles from './LiveBadge.module.css';

export interface LiveBadgeProps {
  /**
   * `md` sits beside the page title, `sm` inside a card header. The two
   * differ only in type scale and padding — they are not independent
   * designs, which is why they share one component.
   */
  size?: 'sm' | 'md';
}

/**
 * The pulsing "Live" pill used wherever the page is showing data that
 * refreshes on its own.
 *
 * Extracted because the page header and the recent-orders card each had
 * their own copy of the markup, the pill styling and the `pulse` keyframes,
 * including a duplicated prefers-reduced-motion override that had to be
 * remembered twice.
 */
export function LiveBadge({ size = 'md' }: LiveBadgeProps) {
  return (
    <span className={`${styles.badge} ${styles[size]}`}>
      <span className={styles.dot} aria-hidden="true" />
      Live
    </span>
  );
}
