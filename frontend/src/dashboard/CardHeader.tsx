import { type ReactNode } from 'react';

import styles from './Dashboard.module.css';

export interface CardHeaderProps {
  title: string;
  /** Right-aligned kicker: counts, freshness, scope. */
  meta: string;
  /** Pulsing accent dot, used by cards that show live data. */
  live?: boolean;
  /**
   * Extra pill rendered between the title and the meta text — e.g. the
   * live/seed source badge on ingestion-backed cards. Optional so the six
   * cards that don't need it are unaffected.
   */
  badge?: ReactNode;
}

// The title/meta bar repeated by eight dashboard cards, so the three-class
// structure (.cardHead > .cardTitle + .cardMeta) is written once.
export function CardHeader({ title, meta, live = false, badge }: CardHeaderProps) {
  return (
    <div className={styles.cardHead}>
      <div className={styles.cardTitle}>
        {live && <span className={styles.dot} aria-hidden="true" />}
        {title}
        {badge}
      </div>
      <div className={styles.cardMeta}>{meta}</div>
    </div>
  );
}
