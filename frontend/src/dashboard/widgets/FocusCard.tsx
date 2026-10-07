import { CardSkeleton } from '../CardSkeleton';
import { type FocusRes } from '../useDashboardData';
import styles from '../Dashboard.module.css';

export interface FocusCardProps {
  focus: FocusRes | null;
}

// Does not use CardHeader: the focus panel is a .focusBig surface whose
// title is a bare .cardTitle with no .cardHead row or meta slot.
export function FocusCard({ focus }: FocusCardProps) {
  return (
    <section className={styles.focusBig}>
      <div className={styles.cardTitle}><span className={styles.dot} />Focus now</div>
      {focus ? (
        <>
          <h2 className={styles.focusTitle}>{focus.title}</h2>
          <div className={styles.focusSubtitle}>{focus.subtitle}</div>
          <p className={styles.focusContext}>{focus.context}</p>
          {focus.url ? (
            <a
              className={styles.focusBtn}
              href={focus.url}
              target="_blank"
              rel="noopener noreferrer"
            >
              {focus.action}
            </a>
          ) : (
            <a className={styles.focusBtn} href="/integrations">
              {focus.action}
            </a>
          )}
        </>
      ) : (
        <div className={styles.cardSkeletonWrap}>
          <CardSkeleton rows={3} />
        </div>
      )}
    </section>
  );
}
