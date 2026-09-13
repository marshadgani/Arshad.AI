import { type Task } from '../../data/mockData';
import { CardHeader } from '../CardHeader';
import { SourceBadge, WidgetStatus } from '../WidgetStatus';
import styles from '../Dashboard.module.css';

export interface TasksCardProps {
  tasks: Task[] | null;
  isLoading?: boolean;
  error?: Error | null;
  /** `"live"` (from Gmail) | `"seed"` (Phase-A fallback) | undefined. */
  mode?: string;
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

export function TasksCard({ tasks, isLoading = false, error = null, mode }: TasksCardProps) {
  const rows = tasks ?? [];
  const visible = rows.slice(0, VISIBLE_TASKS);

  return (
    <section className={styles.card}>
      <CardHeader
        title="My tasks"
        meta={`${rows.length} open`}
        badge={<SourceBadge mode={mode} />}
      />
      <WidgetStatus
        isLoading={isLoading}
        error={error}
        isEmpty={!isLoading && !error && rows.length === 0}
        emptyMessage="No starred or important emails need action right now."
      >
        <div className={styles.list}>
          {visible.map((t) => (
            <div key={t.id} className={styles.row3}>
              <span className={`${styles.priority} ${styles[t.priority]}`}>{t.priority.toUpperCase()}</span>
              <span className={styles.rowText}>
                {t.title}<span className={styles.tag}>{t.source}</span>
              </span>
              <span className={`${styles.due} ${dueClass(t.due)}`}>{t.due}</span>
            </div>
          ))}
        </div>
      </WidgetStatus>
    </section>
  );
}
