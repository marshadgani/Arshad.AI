import { type QuickAction } from '../../data/mockData';
import { CardHeader } from '../CardHeader';
import styles from '../Dashboard.module.css';

export interface QuickActionsCardProps {
  quickActions: QuickAction[] | null;
}

export function QuickActionsCard({ quickActions }: QuickActionsCardProps) {
  return (
    <section className={styles.card}>
      <CardHeader title="Quick actions" meta="shortcuts" />
      <div className={styles.qaGrid}>
        {(quickActions ?? []).map((q) => (
          <button key={q.id} className={styles.qa}>
            <div className={styles.qaLabel}>{q.label}</div>
            {q.hint && <div className={styles.qaHint}>{q.hint}</div>}
          </button>
        ))}
      </div>
    </section>
  );
}
