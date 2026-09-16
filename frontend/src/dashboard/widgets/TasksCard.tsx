import { type Task } from '../../data/mockData';
import { CardHeader } from '../CardHeader';
import styles from '../Dashboard.module.css';

export interface TasksCardProps {
  tasks: Task[] | null;
}

const VISIBLE_TASKS = 5;

// Urgency is inferred from the human-readable due label the API already
// sends ("Yesterday 18:00", "Today 09:30"); there is no separate machine
// field to key off. Named here so the branch is testable and the reason
// for string matching is recorded at the one place it happens.
function dueClass(due: string): string {
  if (due.startsWith('Yesterday')) return styles.dueOverdue;
  if (due.startsWith('Today')) return styles.dueToday;
  return '';
}

export function TasksCard({ tasks }: TasksCardProps) {
  const rows = tasks ?? [];

  return (
    <section className={styles.card}>
      <CardHeader title="My tasks" meta={`${rows.length} open`} />
      <div className={styles.list}>
        {rows.slice(0, VISIBLE_TASKS).map((t) => (
          <div key={t.id} className={styles.row3}>
            <span className={`${styles.priority} ${styles[t.priority]}`}>{t.priority.toUpperCase()}</span>
            <span className={styles.rowText}>
              {t.title}<span className={styles.tag}>{t.source}</span>
            </span>
            <span className={`${styles.due} ${dueClass(t.due)}`}>{t.due}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
