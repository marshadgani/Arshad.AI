import { type AgentHealth, type DomainAgent } from '../../../data/mockData';
import { DomainSection } from '../DomainSection';
import styles from './AgentList.module.css';

export interface AgentListProps {
  agents: DomainAgent[];
}

const healthClass: Record<AgentHealth, string> = {
  healthy: styles.healthHealthy,
  degraded: styles.healthDegraded,
  offline: styles.healthOffline,
  training: styles.healthTraining,
};

/** Agents section: health, metrics and last action for each domain agent. */
export function AgentList({ agents }: AgentListProps) {
  return (
    <DomainSection title="Agents" meta={`${agents.length} active`}>
      <div className={styles.agents}>
        {agents.map((a) => (
          <article key={a.name} className={styles.agent}>
            <div className={styles.agentHead}>
              <span className={`${styles.healthDot} ${healthClass[a.health]}`} />
              <span className={styles.agentName}>{a.name}</span>
            </div>
            <div className={styles.agentDesc}>{a.description}</div>
            <div className={styles.agentMetrics}>
              <div className={styles.metric}>
                <span className={styles.metricLabel}>Uptime</span>
                <span className={styles.metricValue}>{a.uptime}</span>
              </div>
              <div className={styles.metric}>
                <span className={styles.metricLabel}>Accuracy</span>
                <span className={styles.metricValue}>{a.accuracy}%</span>
              </div>
            </div>
            <div className={styles.agentLast}>↳ {a.lastAction}</div>
            <div className={styles.agentFoot}>
              <span className={styles.agentRun}>{a.lastRun}</span>
            </div>
          </article>
        ))}
      </div>
    </DomainSection>
  );
}
