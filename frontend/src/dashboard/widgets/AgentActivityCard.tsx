import { type AgentTick } from '../../data/mockData';
import { CardHeader } from '../CardHeader';
import { SourceBadge, WidgetStatus } from '../WidgetStatus';
import styles from '../Dashboard.module.css';

export interface AgentActivityCardProps {
  agentActivity: AgentTick[] | null;
  isLoading?: boolean;
  error?: Error | null;
  /** `"live"` (from GitHub PRs) | `"seed"` (Phase-A fallback) | undefined. */
  mode?: string;
}

export function AgentActivityCard({
  agentActivity,
  isLoading = false,
  error = null,
  mode,
}: AgentActivityCardProps) {
  const rows = agentActivity ?? [];
  // The header's pulsing dot previously always claimed "live" even when
  // showing seed rows; it now only lights up once the mode is confirmed live.
  const isLive = mode === 'live';

  return (
    <section className={styles.card}>
      <CardHeader
        title="Agent activity"
        meta={isLive ? 'live' : 'recent'}
        live={isLive}
        badge={<SourceBadge mode={mode} />}
      />
      <WidgetStatus
        isLoading={isLoading}
        error={error}
        isEmpty={!isLoading && !error && rows.length === 0}
        emptyMessage="No open pull requests tracked yet."
      >
        <div className={styles.list}>
          {rows.map((a) => (
            <div key={a.id} className={styles.tick}>
              <span className={styles.tickAgent}>{a.agent}</span>
              <span className={styles.tickMsg}>{a.message}</span>
              <span className={styles.tickTime}>{a.time}</span>
            </div>
          ))}
        </div>
      </WidgetStatus>
    </section>
  );
}
