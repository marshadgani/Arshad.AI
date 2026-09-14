import { type Decision } from '../../data/mockData';
import { CardHeader } from '../CardHeader';
import { CardSkeleton } from '../CardSkeleton';
import { EmptyState } from '../EmptyState';
import styles from '../Dashboard.module.css';

export interface DecisionQueueCardProps {
  decisions: Decision[] | null;
}

export function DecisionQueueCard({ decisions }: DecisionQueueCardProps) {
  return (
    <section className={styles.card}>
      <CardHeader
        title="Decision queue"
        meta={decisions === null ? '···' : `${decisions.length} waiting`}
      />
      <div className={styles.list}>
        {decisions === null ? (
          <CardSkeleton />
        ) : decisions.length === 0 ? (
          <EmptyState message="Nothing waiting on you right now." />
        ) : (
          decisions.map((d) => (
            <div key={d.id} className={styles.decision}>
              <div className={styles.decisionTitle}>{d.title}</div>
              <div className={styles.decisionContext}>{d.context}</div>
              <div className={styles.decisionMeta}>
                <span>{d.source}</span>
                <span>waiting {d.waitingSince}</span>
              </div>
            </div>
          ))
        )}
      </div>
    </section>
  );
}
