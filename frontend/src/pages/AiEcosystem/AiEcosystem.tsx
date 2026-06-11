import React, { useState } from 'react';
import { useFetch } from '../../hooks/useFetch';
import AgentCard, { AgentData, AgentMetric } from './AgentCard';
import styles from './AiEcosystem.module.css';
import TimePeriodFilter, { Period } from './TimePeriodFilter';

interface AgentsResponse {
  data: AgentData[];
  total: number;
}

interface MetricsInner {
  period: Period;
  agents: AgentMetric[];
}

interface MetricsResponse {
  data: MetricsInner;
}

interface SummaryInner {
  period: Period;
  total_invocations: number;
  total_tokens: number;
  most_used_agent: string | null;
  most_efficient_agent: string | null;
}

interface SummaryResponse {
  data: SummaryInner;
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

export default function AiEcosystem() {
  const [period, setPeriod] = useState<Period>('1d');

  // Poll every 30 s so newly registered agents appear without a page refresh.
  const { data: agentsData } = useFetch<AgentsResponse['data']>('/api/v1/ai-ecosystem/agents', 30_000);
  const { data: metricsData } = useFetch<MetricsInner>(`/api/v1/ai-ecosystem/metrics?period=${period}`);
  const { data: summaryData } = useFetch<SummaryInner>(`/api/v1/ai-ecosystem/summary?period=${period}`);

  const agents = agentsData ?? [];
  const metricMap = new Map<string, AgentMetric>(
    (metricsData?.agents ?? []).map((m) => [m.agent_name, m])
  );

  const devTeam = agents
    .filter((a) => a.category === 'development_team')
    .sort((a, b) => (a.pipeline_stage ?? 999) - (b.pipeline_stage ?? 999));

  const otherAgents = agents
    .filter((a) => a.category === 'other')
    .sort((a, b) => a.display_name.localeCompare(b.display_name));

  return (
    <div className={styles.page}>
      <div className={styles.pageHeader}>
        <div>
          <h1 className={styles.title}>AI Ecosystem</h1>
          <p className={styles.subtitle}>{agents.length} agents registered</p>
        </div>
        {summaryData && (
          <div className={styles.summaryStats}>
            <div className={styles.stat}>
              <span className={styles.statValue}>{summaryData.total_invocations.toLocaleString()}</span>
              <span className={styles.statLabel}>Invocations</span>
            </div>
            <div className={styles.stat}>
              <span className={styles.statValue}>{formatTokens(summaryData.total_tokens)}</span>
              <span className={styles.statLabel}>Tokens used</span>
            </div>
            {summaryData.most_used_agent && (
              <div className={styles.stat}>
                <span className={styles.statValue}>{summaryData.most_used_agent}</span>
                <span className={styles.statLabel}>Most used</span>
              </div>
            )}
          </div>
        )}
      </div>

      <TimePeriodFilter value={period} onChange={setPeriod} />

      {devTeam.length > 0 && (
        <section className={styles.section}>
          <div className={styles.sectionHeader}>
            <h2 className={styles.sectionTitle}>Development Team</h2>
            <span className={styles.sectionCount}>{devTeam.length} agents</span>
          </div>
          <div className={styles.grid}>
            {devTeam.map((agent) => (
              <AgentCard
                key={agent.agent_name}
                agent={agent}
                metric={metricMap.get(agent.agent_name)}
              />
            ))}
          </div>
        </section>
      )}

      {otherAgents.length > 0 && (
        <section className={styles.section}>
          <div className={styles.sectionHeader}>
            <h2 className={styles.sectionTitle}>Other Agents</h2>
            <span className={styles.sectionCount}>{otherAgents.length} agents</span>
          </div>
          <div className={styles.grid}>
            {otherAgents.map((agent) => (
              <AgentCard
                key={agent.agent_name}
                agent={agent}
                metric={metricMap.get(agent.agent_name)}
              />
            ))}
          </div>
        </section>
      )}

      {agents.length === 0 && (
        <div className={styles.empty}>Loading agents…</div>
      )}
    </div>
  );
}
