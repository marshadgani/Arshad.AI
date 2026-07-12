import { useState } from 'react';
import { useFetch } from '../../hooks/useFetch';
import AgentCard, { AgentData, AgentMetric } from './AgentCard';
import SkillCard, { SkillData } from './SkillCard';
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

type View = 'agents' | 'skills';
type AgentFilterKey = 'development' | 'cicd' | 'other';
type SkillFilterKey = 'development' | 'security' | 'data' | 'other';

const AGENT_FILTERS: { key: AgentFilterKey; label: string }[] = [
  { key: 'development', label: 'Development' },
  { key: 'cicd', label: 'CI/CD' },
  { key: 'other', label: 'Other' },
];

const SKILL_FILTERS: { key: SkillFilterKey; label: string }[] = [
  { key: 'development', label: 'Development' },
  { key: 'security', label: 'Security' },
  { key: 'data', label: 'Data' },
  { key: 'other', label: 'Other' },
];

const CICD_KEYWORDS = ['cicd', 'devops', 'deploy', 'pipeline', 'workflow', 'release', 'infra', 'kubernetes', 'docker', 'monitor', 'heal'];

function resolveAgentFilter(agent: AgentData): AgentFilterKey {
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
  const [activeView, setActiveView] = useState<View>('agents');
  const [period, setPeriod] = useState<Period>('1d');
  const [activeAgentFilters, setActiveAgentFilters] = useState<Set<AgentFilterKey>>(
    new Set(['development', 'cicd', 'other'])
  );
  const [activeSkillFilters, setActiveSkillFilters] = useState<Set<SkillFilterKey>>(
    new Set(['development', 'security', 'data', 'other'])
  );

  const { data: agentsData } = useFetch<AgentData[]>('/api/v1/ai-ecosystem/agents', 30_000);
  const { data: metricsData } = useFetch<MetricsInner>(`/api/v1/ai-ecosystem/metrics?period=${period}`);
  const { data: summaryData } = useFetch<SummaryInner>(`/api/v1/ai-ecosystem/summary?period=${period}`);
  const { data: skillsResponse } = useFetch<{ data: SkillData[]; total: number }>('/api/v1/ai-ecosystem/skills', 30_000);

  const agents = agentsData ?? [];
  const skills = skillsResponse?.data ?? [];
  const metricMap = new Map<string, AgentMetric>(
    (metricsData?.agents ?? []).map((m) => [m.agent_name, m])
  );

  const visibleAgents = agents
    .filter((a) => activeAgentFilters.has(resolveAgentFilter(a)))
    .sort((a, b) => {
      if (a.category === 'development_team' && b.category === 'development_team') {
        return (a.pipeline_stage ?? 999) - (b.pipeline_stage ?? 999);
      }
      return a.display_name.localeCompare(b.display_name);
    });

  const visibleSkills = skills
    .filter((s) => activeSkillFilters.has((s.category as SkillFilterKey) ?? 'other'))
    .sort((a, b) => a.display_name.localeCompare(b.display_name));

  function toggleAgentFilter(key: AgentFilterKey) {
    setActiveAgentFilters((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        if (next.size > 1) next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }

  function toggleSkillFilter(key: SkillFilterKey) {
    setActiveSkillFilters((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        if (next.size > 1) next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }

  const subtitle = activeView === 'agents'
    ? `${agents.length} agents registered`
    : `${skills.length} skills registered`;

  return (
    <div className={styles.page}>
      <div className={styles.pageHeader}>
        <div>
          <h1 className={styles.title}>AI Ecosystem</h1>
          <p className={styles.subtitle}>{subtitle}</p>
        </div>
        {activeView === 'agents' && summaryData && (
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

      {/* View switcher */}
      <div className={styles.viewSwitcher}>
        <button
          type="button"
          className={`${styles.viewBtn} ${activeView === 'agents' ? styles.viewBtnActive : ''}`}
          onClick={() => setActiveView('agents')}
        >
          Agents
          <span className={styles.filterCount}>{agents.length}</span>
        </button>
        <button
          type="button"
          className={`${styles.viewBtn} ${activeView === 'skills' ? styles.viewBtnActive : ''}`}
          onClick={() => setActiveView('skills')}
        >
          Skills
          <span className={styles.filterCount}>{skills.length}</span>
        </button>
      </div>

      {activeView === 'agents' ? (
        <>
          <div className={styles.controls}>
            <div className={styles.filterBar}>
              {AGENT_FILTERS.map(({ key, label }) => (
                <button
                  key={key}
                  type="button"
                  className={`${styles.filterBtn} ${activeAgentFilters.has(key) ? styles.filterBtnActive : ''}`}
                  onClick={() => toggleAgentFilter(key)}
                >
                  {label}
                  <span className={styles.filterCount}>
                    {agents.filter((a) => resolveAgentFilter(a) === key).length}
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
        </>
      ) : (
        <>
          <div className={styles.controls}>
            <div className={styles.filterBar}>
              {SKILL_FILTERS.map(({ key, label }) => (
                <button
                  key={key}
                  type="button"
                  className={`${styles.filterBtn} ${activeSkillFilters.has(key) ? styles.filterBtnActive : ''}`}
                  onClick={() => toggleSkillFilter(key)}
                >
                  {label}
                  <span className={styles.filterCount}>
                    {skills.filter((s) => (s.category ?? 'other') === key).length}
                  </span>
                </button>
              ))}
            </div>
          </div>

          {visibleSkills.length > 0 ? (
            <div className={styles.grid}>
              {visibleSkills.map((skill) => (
                <SkillCard key={skill.skill_name} skill={skill} />
              ))}
            </div>
          ) : (
            <div className={styles.empty}>
              {skills.length === 0 ? 'Loading skills…' : 'No skills match the selected filters.'}
            </div>
          )}
        </>
      )}
    </div>
  );
}
