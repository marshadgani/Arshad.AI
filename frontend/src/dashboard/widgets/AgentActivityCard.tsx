import { type AgentTick } from '../../data/mockData';
import { CardHeader } from '../CardHeader';
import styles from '../Dashboard.module.css';

export interface AgentActivityCardProps {
  agentActivity: AgentTick[] | null;
}

export function AgentActivityCard({ agentActivity }: AgentActivityCardProps) {
  return (
    <section className={styles.card}>
      <CardHeader title="Agent activity" meta="live" live />
      <div className={styles.list}>
        {(agentActivity ?? []).map((a) => (
          <div key={a.id} className={styles.tick}>
            <span className={styles.tickAgent}>{a.agent}</span>
            <span className={styles.tickMsg}>{a.message}</span>
            <span className={styles.tickTime}>{a.time}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
