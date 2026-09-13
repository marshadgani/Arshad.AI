import { type Decision } from '../../data/mockData';
import { CardHeader } from '../CardHeader';
import { SourceBadge, WidgetStatus } from '../WidgetStatus';
import styles from '../Dashboard.module.css';

export interface DecisionQueueCardProps {
  decisions: Decision[] | null;
  isLoading?: boolean;
  error?: Error | null;
  mode?: string;
}

export function DecisionQueueCard({
  decisions,
  isLoading = false,
  error = null,
  mode,
}: DecisionQueueCardProps) {
  const rows = decisions ?? [];

  return (
    <section className={styles.card}>
      <CardHeader
        title="Decision queue"
        meta={`${rows.length} waiting`}
        badge={<SourceBadge mode={mode} />}
      />
      <WidgetStatus
        isLoading={isLoading}
        error={error}
        isEmpty={!isLoading && !error && rows.length === 0}
        emptyMessage="Nothing waiting on you."
      >
        <div className={styles.list}>
          {rows.map((d) => (
            <div key={d.id} className={styles.decision}>
              <div className={styles.decisionTitle}>{d.title}</div>
              <div className={styles.decisionContext}>{d.context}</div>
              <div className={styles.decisionMeta}>
                <span>{d.source}</span>
                <span>waiting {d.waitingSince}</span>
              </div>
            </div>
          ))}
        </div>
      </WidgetStatus>
    </section>
  );
}
