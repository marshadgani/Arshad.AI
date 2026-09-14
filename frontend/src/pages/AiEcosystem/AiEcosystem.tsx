import { useEffect, useState } from 'react';
import { useFetch } from '../../hooks/useFetch';
import { usePaginatedFetch } from '../../hooks/usePaginatedFetch';
import AgentCard, { AgentData, AgentMetric } from './AgentCard';
import SkillCard, { asSkillCategory, SkillCategory, SkillData } from './SkillCard';
import SkillCardSkeleton from './SkillCardSkeleton';
import styles from './AiEcosystem.module.css';
import TimePeriodFilter, { Period } from './TimePeriodFilter';

const SKILLS_SKELETON_COUNT = 12;

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
// Reuses SkillData's category union instead of redeclaring the same four
// literals a third time (the backend Literal and SkillData already had it
// independently) — one more place these could have silently drifted apart.
type SkillFilterKey = SkillCategory;

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

const SKILLS_PAGE_SIZE = 50;
const SKILLS_SEARCH_DEBOUNCE_MS = 300;

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
  const [skillCategory, setSkillCategory] = useState<SkillFilterKey | 'all'>('all');
  const [skillSearchInput, setSkillSearchInput] = useState('');
  const [skillSearch, setSkillSearch] = useState('');
  const [skillOffset, setSkillOffset] = useState(0);

  const { data: agentsData } = useFetch<AgentData[]>('/api/v1/ai-ecosystem/agents', {
    refreshInterval: 30_000,
  });
  const { data: metricsData } = useFetch<MetricsInner>(`/api/v1/ai-ecosystem/metrics?period=${period}`);
  const { data: summaryData } = useFetch<SummaryInner>(`/api/v1/ai-ecosystem/summary?period=${period}`);

  // Debounce free-text search before it hits the URL/network.
  useEffect(() => {
    const id = setTimeout(() => {
      setSkillSearch(skillSearchInput.trim());
      setSkillOffset(0);
    }, SKILLS_SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(id);
  }, [skillSearchInput]);

  const skillsParams = new URLSearchParams({
    limit: String(SKILLS_PAGE_SIZE),
    offset: String(skillOffset),
  });
  if (skillCategory !== 'all') skillsParams.set('category', skillCategory);
  if (skillSearch) skillsParams.set('q', skillSearch);

  const {
    data: skills,
    total: skillsTotal,
    isLoading: skillsLoading,
    error: skillsError,
    refetch: refetchSkills,
  } = usePaginatedFetch<SkillData>(`/api/v1/ai-ecosystem/skills?${skillsParams.toString()}`);

  const skillFiltersActive = skillCategory !== 'all' || skillSearch !== '';

  const agents = agentsData ?? [];
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

  function selectSkillFilter(key: SkillFilterKey) {
    setSkillCategory((prev) => (prev === key ? 'all' : key));
    setSkillOffset(0);
  }

  const skillsRangeStart = skillsTotal === 0 ? 0 : skillOffset + 1;
  const skillsRangeEnd = Math.min(skillOffset + skills.length, skillsTotal);
  const hasNextSkillsPage = skillOffset + skills.length < skillsTotal;

  const subtitle = activeView === 'agents'
    ? `${agents.length} agents registered`
    : `${skillsTotal} skills registered`;

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
          <span className={styles.filterCount}>{skillsTotal}</span>
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
                  className={`${styles.filterBtn} ${skillCategory === key ? styles.filterBtnActive : ''}`}
                  onClick={() => selectSkillFilter(key)}
                >
                  {label}
                </button>
              ))}
            </div>
            <input
              type="text"
              className={styles.searchInput}
              placeholder="Search skills…"
              value={skillSearchInput}
              onChange={(e) => setSkillSearchInput(e.target.value)}
              aria-label="Search skills"
            />
          </div>

          {skillsError ? (
            <div className={styles.errorState} role="alert">
              <span className={styles.errorGlyph} aria-hidden="true">
                !
              </span>
              <div>
                <p className={styles.errorTitle}>Couldn&apos;t load skills</p>
                <p className={styles.errorDetail}>{skillsError.message}</p>
              </div>
              <button type="button" className={styles.retryBtn} onClick={refetchSkills}>
                Retry
              </button>
            </div>
          ) : skillsLoading && skills.length === 0 ? (
            <div className={styles.grid} aria-busy="true" aria-live="polite">
              <span className={styles.srOnly}>Loading skills…</span>
              {Array.from({ length: SKILLS_SKELETON_COUNT }).map((_, i) => (
                <SkillCardSkeleton key={i} index={i} />
              ))}
            </div>
          ) : skills.length > 0 ? (
            <>
              <div className={styles.grid}>
                {skills.map((skill, i) => (
                  <SkillCard
                    key={skill.skill_name}
                    // usePaginatedFetch trusts the wire response's shape via
                    // an unchecked type cast (see its `as Promise<...>`) — it
                    // does not runtime-validate that `category` is actually
                    // one of the four known values, so normalize at the
                    // boundary where the fetched row turns into UI, rather
                    // than trusting the static type all the way into render.
                    skill={{ ...skill, category: asSkillCategory(skill.category) }}
                    index={i}
                  />
                ))}
              </div>
              <div className={styles.pagination}>
                <span className={styles.pageInfo}>
                  Showing {skillsRangeStart}–{skillsRangeEnd} of {skillsTotal}
                </span>
                <button
                  type="button"
                  className={styles.pageBtn}
                  onClick={() => setSkillOffset((o) => Math.max(0, o - SKILLS_PAGE_SIZE))}
                  disabled={skillOffset === 0}
                >
                  Prev
                </button>
                <button
                  type="button"
                  className={styles.pageBtn}
                  onClick={() => setSkillOffset((o) => o + SKILLS_PAGE_SIZE)}
                  disabled={!hasNextSkillsPage}
                >
                  Next
                </button>
              </div>
            </>
          ) : skillFiltersActive ? (
            <div className={styles.empty}>
              <p className={styles.emptyTitle}>No skills match</p>
              <p className={styles.emptyDetail}>
                Nothing found{skillSearch ? ` for “${skillSearch}”` : ''}
                {skillCategory !== 'all' ? ` in ${skillCategory}` : ''}. Try a different search or
                category.
              </p>
              <button
                type="button"
                className={styles.retryBtn}
                onClick={() => {
                  setSkillCategory('all');
                  setSkillSearchInput('');
                  setSkillSearch('');
                  setSkillOffset(0);
                }}
              >
                Clear filters
              </button>
            </div>
          ) : (
            <div className={styles.empty}>
              <p className={styles.emptyTitle}>Skill registry is empty</p>
              <p className={styles.emptyDetail}>
                No skills have been synced from <code>.claude/skills/</code> yet. Run{' '}
                <code>backend/scripts/register_skills.py</code> to regenerate the manifest, then
                restart the backend so the seed step converges it into the database.
              </p>
            </div>
          )}
        </>
      )}
    </div>
  );
}
