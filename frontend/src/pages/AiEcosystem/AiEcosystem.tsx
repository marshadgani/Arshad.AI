import { useState } from 'react';
import { useFetch } from '../../hooks/useFetch';
import AgentCard, { AgentData, AgentMetric } from './AgentCard';
import styles from './AiEcosystem.module.css';
import TimePeriodFilter, { Period } from './TimePeriodFilter';

interface MetricsInner {
  period: Period;
  agents: AgentMetric[];
}

interface SummaryInner {
  period: Period;
  total_invocations: number;
  total_tokens: number;
  most_used_agent: string | null;
  most_efficient_agent: string | null;
}

type FilterKey = 'development' | 'cicd' | 'other';

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: 'development', label: 'Development' },
  { key: 'cicd', label: 'CI/CD' },
  { key: 'other', label: 'Other' },
];

const CICD_KEYWORDS = ['cicd', 'devops', 'deploy', 'pipeline', 'workflow', 'release', 'infra', 'kubernetes', 'docker', 'monitor', 'heal'];

function resolveFilter(agent: AgentData): FilterKey {
  if (agent.category === 'development_team') return 'development';
  const name = agent.agent_name.toLowerCase();
  if (CICD_KEYWORDS.some((kw) => name.includes(kw))) return 'cicd';
  return 'other';
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

export default function AiEcosystem() {
  const [period, setPeriod] = useState<Period>('1d');
  const [activeFilters, setActiveFilters] = useState<Set<FilterKey>>(
    new Set(['development', 'cicd', 'other'])
  );

  const { data: agentsData } = useFetch<AgentData[]>('/api/v1/ai-ecosystem/agents', 30_000);
  const { data: metricsData } = useFetch<MetricsInner>(`/api/v1/ai-ecosystem/metrics?period=${period}`);
  const { data: summaryData } = useFetch<SummaryInner>(`/api/v1/ai-ecosystem/summary?period=${period}`);

  const agents = agentsData ?? [];
  const metricMap = new Map<string, AgentMetric>(
    (metricsData?.agents ?? []).map((m) => [m.agent_name, m])
  );

  const visibleAgents = agents
    .filter((a) => activeFilters.has(resolveFilter(a)))
    .sort((a, b) => {
      // dev team sorted by pipeline stage, everything else alphabetically
      if (a.category === 'development_team' && b.category === 'development_team') {
        return (a.pipeline_stage ?? 999) - (b.pipeline_stage ?? 999);
      }
      return a.display_name.localeCompare(b.display_name);
    });

  function toggleFilter(key: FilterKey) {
    setActiveFilters((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        // keep at least one active
        if (next.size > 1) next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }

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

      <div className={styles.controls}>
        <div className={styles.filterBar}>
          {FILTERS.map(({ key, label }) => (
            <button
              key={key}
              type="button"
              className={`${styles.filterBtn} ${activeFilters.has(key) ? styles.filterBtnActive : ''}`}
              onClick={() => toggleFilter(key)}
            >
              {label}
              <span className={styles.filterCount}>
                {agents.filter((a) => resolveFilter(a) === key).length}
              </span>
            </button>
          ))}
        </div>
        <TimePeriodFilter value={period} onChange={setPeriod} />
      </div>

      {visibleAgents.length > 0 ? (
        <div className={styles.grid}>
          {visibleAgents.map((agent) => (
            <AgentCard
              key={agent.agent_name}
              agent={agent}
              metric={metricMap.get(agent.agent_name)}
            />
          ))}
        </div>
      ) : (
        <div className={styles.empty}>
          {agents.length === 0 ? 'Loading agents…' : 'No agents match the selected filters.'}
        </div>
      )}
    </div>
  );
}
