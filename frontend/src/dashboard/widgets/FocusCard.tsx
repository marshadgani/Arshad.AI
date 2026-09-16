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
      <h2 className={styles.focusTitle}>{focus?.title ?? '—'}</h2>
      <div className={styles.focusSubtitle}>{focus?.subtitle ?? ''}</div>
      <p className={styles.focusContext}>{focus?.context ?? ''}</p>
      <button className={styles.focusBtn}>{focus?.action ?? 'Open'}</button>
    </section>
  );
}
