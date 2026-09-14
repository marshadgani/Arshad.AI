import styles from './SkillCardSkeleton.module.css';

export interface SkillCardSkeletonProps {
  /** Stable stagger index — offsets the shimmer animation slightly per card. */
  index?: number;
}

/**
 * Placeholder shown while skills are loading. Mirrors SkillCard's layout
 * exactly (header/description/footer) so the grid doesn't jump when real
 * cards arrive — measure, don't guess, per .claude/rules/frontend.md
 * performance guidance on layout shift.
 */
export default function SkillCardSkeleton({ index = 0 }: SkillCardSkeletonProps) {
  return (
    <div
      className={styles.card}
      style={{ animationDelay: `${(index % 8) * 45}ms` }}
      aria-hidden="true"
    >
      <div className={styles.header}>
        <span className={`${styles.bar} ${styles.name}`} />
        <span className={`${styles.bar} ${styles.pill}`} />
      </div>
      <span className={`${styles.bar} ${styles.line}`} />
      <span className={`${styles.bar} ${styles.line}`} />
      <span className={`${styles.bar} ${styles.lineShort}`} />
      <div className={styles.footer}>
        <span className={`${styles.bar} ${styles.badge}`} />
      </div>
    </div>
  );
}
