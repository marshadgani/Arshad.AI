import { type Decision } from '../../data/mockData';
import { CardHeader } from '../CardHeader';
import styles from '../Dashboard.module.css';

export interface DecisionQueueCardProps {
  decisions: Decision[] | null;
}

export function DecisionQueueCard({ decisions }: DecisionQueueCardProps) {
  const rows = decisions ?? [];

  return (
    <section className={styles.card}>
      <CardHeader title="Decision queue" meta={`${rows.length} waiting`} />
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
    </section>
  );
}
