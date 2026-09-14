import { type AgentHealth, type DomainAgent } from '../../data/mockData';
import styles from './DomainPage.module.css';
import DomainSection from './DomainSection';

export interface AgentsSectionProps {
  agents: DomainAgent[];
}

const healthClass: Record<AgentHealth, string> = {
  healthy: styles.healthHealthy,
  degraded: styles.healthDegraded,
  offline: styles.healthOffline,
  training: styles.healthTraining,
};

// Read-only catalogue, same as ApplicationsSection: there is no per-agent
// config surface to navigate to, so no "Configure" button here (FEAT-148).
export default function AgentsSection({ agents }: AgentsSectionProps) {
  return (
    <DomainSection title="Agents" meta={`${agents.length} active`}>
      <div className={styles.agents}>
        {agents.map((agent) => (
          <article key={agent.name} className={styles.agent}>
            <div className={styles.agentHead}>
              <span className={`${styles.healthDot} ${healthClass[agent.health]}`} />
              <span className={styles.agentName}>{agent.name}</span>
            </div>
            <div className={styles.agentDesc}>{agent.description}</div>
            <div className={styles.agentMetrics}>
              <div className={styles.metric}>
                <span className={styles.metricLabel}>Uptime</span>
                <span className={styles.metricValue}>{agent.uptime}</span>
              </div>
              <div className={styles.metric}>
                <span className={styles.metricLabel}>Accuracy</span>
                <span className={styles.metricValue}>{agent.accuracy}%</span>
              </div>
            </div>
            <div className={styles.agentLast}>↳ {agent.lastAction}</div>
            <div className={styles.agentFoot}>
              <span className={styles.agentRun}>{agent.lastRun}</span>
            </div>
          </article>
        ))}
      </div>
    </DomainSection>
  );
}
