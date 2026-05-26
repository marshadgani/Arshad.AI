import { type DomainConfig, type Application, type DomainAgent, type AgentHealth } from '../data/mockData';
import { useFetch } from '../hooks/useFetch';
import styles from './DomainPage.module.css';

export interface DomainPageProps {
  slug: string;
}

const healthClass: Record<AgentHealth, string> = {
  healthy: styles.healthHealthy,
  degraded: styles.healthDegraded,
  offline: styles.healthOffline,
  training: styles.healthTraining,
};

const statusClass: Record<Application['status'], string> = {
  live: styles.live,
  beta: styles.beta,
  planned: styles.planned,
};

export default function DomainPage({ slug }: DomainPageProps) {
  const { data: domain, isLoading, error } = useFetch<DomainConfig>(`/api/v1/domains/${slug}`);

  if (error) return <div className={styles.page}>Failed to load domain "{slug}": {error.message}</div>;
  if (isLoading || !domain) return <div className={styles.page}>Loading {slug}…</div>;

  return (
    <div className={styles.page}>
      {/* ── Header + KPIs ──────────────────────────────────── */}
      <header className={styles.header}>
        <div className={styles.headerEmoji}>{domain.emoji}</div>
        <div className={styles.headerText}>
          <span className={styles.headerKicker}>// DOMAIN · {domain.slug.toUpperCase()}</span>
          <h1 className={styles.headerTitle}>{domain.title}</h1>
          <p className={styles.headerTagline}>{domain.tagline}</p>
        </div>
        <div className={styles.kpis}>
          {domain.kpis.map((k) => (
            <div key={k.label} className={styles.kpi}>
              <div className={styles.kpiLabel}>{k.label}</div>
              <div className={styles.kpiValue}>{k.value}</div>
              {k.delta && <div className={styles.kpiDelta}>{k.delta}</div>}
            </div>
          ))}
        </div>
      </header>

      {/* ── Applications ───────────────────────────────────── */}
      <section className={styles.section}>
        <div className={styles.sectionHead}>
          <div className={styles.sectionTitle}>Applications</div>
          <div className={styles.sectionMeta}>{domain.applications.length} total</div>
        </div>
        <div className={styles.appGrid}>
          {domain.applications.map((app) => (
            <article key={app.id} className={styles.app}>
              <div className={styles.appName}>{app.name}</div>
              <div className={styles.appDesc}>{app.description}</div>
              <div className={styles.appFoot}>
                <span className={`${styles.statusTag} ${statusClass[app.status]}`}>{app.status}</span>
                {app.status !== 'planned' ? (
                  <button className={styles.appOpen}>Open →</button>
                ) : null}
              </div>
            </article>
          ))}
        </div>
      </section>

      {/* ── Agents ─────────────────────────────────────────── */}
      <section className={styles.section}>
        <div className={styles.sectionHead}>
          <div className={styles.sectionTitle}>Agents</div>
          <div className={styles.sectionMeta}>{domain.agents.length} active</div>
        </div>
        <div className={styles.agents}>
          {domain.agents.map((a: DomainAgent) => (
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
                <button className={styles.agentConfig}>Configure</button>
              </div>
            </article>
          ))}
        </div>
      </section>

      {/* ── Activity feed ──────────────────────────────────── */}
      <section className={styles.section}>
        <div className={styles.sectionHead}>
          <div className={styles.sectionTitle}>Recent activity</div>
          <div className={styles.sectionMeta}>last 24 h</div>
        </div>
        <div className={styles.feed}>
          {domain.feed.map((row) => (
            <div key={row.id} className={styles.feedRow}>
              <span className={styles.feedTime}>{row.time}</span>
              <span className={styles.feedMsg}>{row.message}</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
