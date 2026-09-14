import styles from './SkillsLoadingState.module.css';

export interface SkillsLoadingStateProps {
  /** How many skeleton cards to render — mirrors the eventual grid density. */
  count?: number;
}

/**
 * Skeleton grid shown while `/api/v1/ai-ecosystem/skills` is in flight.
 * Reuses the exact card geometry of `SkillCard` so there is zero layout
 * shift when real data lands — only the shimmer sweep signals "loading".
 */
export default function SkillsLoadingState({ count = 8 }: SkillsLoadingStateProps) {
  return (
    <div className={styles.grid} role="status" aria-live="polite" aria-label="Loading skills">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className={styles.skeletonCard} aria-hidden="true">
          <div className={styles.skeletonHeader}>
            <span className={styles.skeletonLine} style={{ width: '60%' }} />
            <span className={styles.skeletonPill} />
          </div>
          <span className={styles.skeletonLine} style={{ width: '100%' }} />
          <span className={styles.skeletonLine} style={{ width: '82%' }} />
          <span className={styles.skeletonLine} style={{ width: '45%' }} />
          <div className={styles.skeletonFooter}>
            <span className={styles.skeletonBadge} />
          </div>
        </div>
      ))}
      <span className="sr-only">Loading skills…</span>
    </div>
  );
}
