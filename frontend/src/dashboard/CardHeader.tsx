import styles from './Dashboard.module.css';

export interface CardHeaderProps {
  title: string;
  /** Right-aligned kicker: counts, freshness, scope. */
  meta: string;
  /** Pulsing accent dot, used by cards that show live data. */
  live?: boolean;
}

// The title/meta bar repeated by eight dashboard cards, so the three-class
// structure (.cardHead > .cardTitle + .cardMeta) is written once.
export function CardHeader({ title, meta, live = false }: CardHeaderProps) {
  return (
    <div className={styles.cardHead}>
      <div className={styles.cardTitle}>
        {live && <span className={styles.dot} />}
        {title}
      </div>
      <div className={styles.cardMeta}>{meta}</div>
    </div>
  );
}
