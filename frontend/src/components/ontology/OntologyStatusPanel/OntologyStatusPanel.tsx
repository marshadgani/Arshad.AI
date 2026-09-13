import { OntologyEmptyState } from '../OntologyEmptyState';
import { OntologyErrorPanel } from '../OntologyErrorPanel';
import type { OntologyStatus } from '../../../types/ontology';
import styles from './OntologyStatusPanel.module.css';

export interface OntologyStatusPanelProps {
  status: OntologyStatus | null;
  isLoading: boolean;
  error: Error | null;
  /** Which domain tile is currently selected as an entity-list filter. */
  activeDomain: string | null;
  onSelectDomain: (domain: string | null) => void;
}

const DOMAIN_LABELS: Record<string, string> = {
  calendar: 'Calendar',
  email: 'Email',
  github: 'GitHub',
  people: 'People',
};

const RUN_STATUS_LABELS: Record<string, string> = {
  running: 'Running',
  succeeded: 'Succeeded',
  partial: 'Partial',
  deferred: 'Deferred',
  failed: 'Failed',
  dry_run: 'Dry run',
};

function formatRelative(iso: string | null): string {
  if (!iso) return 'never';
  const diffMs = Date.now() - new Date(iso).getTime();
  const mins = Math.round(diffMs / 60_000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

/**
 * The knowledge-graph "control tower" — sync freshness, run status, and a
 * per-domain entity-count grid that doubles as the entity-list filter (each
 * tile is a MOC-style navigation target, not just a stat).
 *
 * Four states per .claude/rules/frontend.md:
 *   loading  — skeleton tiles, gated on !status so polling never blanks
 *              an already-rendered panel
 *   error    — OntologyErrorPanel, only when there's no cached status
 *   empty    — no sync has ever run (total_entities === 0, last_run_at null)
 *   content  — the real grid + run metadata
 */
export function OntologyStatusPanel({
  status,
  isLoading,
  error,
  activeDomain,
  onSelectDomain,
}: OntologyStatusPanelProps) {
  if (isLoading && !status) {
    return (
      <div className={styles.panel} aria-busy="true">
        <div className={styles.grid}>
          {['calendar', 'email', 'github', 'people'].map((d) => (
            <div key={d} className={`${styles.tile} ${styles.tileSkeleton}`}>
              <span className={styles.skeletonLabel} />
              <span className={styles.skeletonValue} />
            </div>
          ))}
        </div>
        <span className="sr-only" role="status">
          Loading ontology status…
        </span>
      </div>
    );
  }

  if (error && !status) {
    return <OntologyErrorPanel message="Failed to load ontology status." />;
  }

  if (!status || (status.total_entities === 0 && !status.last_run_at)) {
    return (
      <OntologyEmptyState
        icon="⟡"
        title="No ontology sync yet"
        description="Push-sync your ingested calendar, email, and GitHub data into the vault as linked entity notes and Maps of Content."
      />
    );
  }

  const domains = Object.keys(DOMAIN_LABELS).filter(
    (d) => status.entity_counts_by_domain[d] !== undefined,
  );

  return (
    <div className={styles.panel}>
      <div className={styles.grid}>
        {domains.map((domain) => {
          const count = status.entity_counts_by_domain[domain] ?? 0;
          const isActive = activeDomain === domain;
          return (
            <button
              key={domain}
              type="button"
              className={`${styles.tile} ${isActive ? styles.tileActive : ''}`}
              onClick={() => onSelectDomain(isActive ? null : domain)}
              aria-pressed={isActive}
            >
              <span className={styles.tileLabel}>{DOMAIN_LABELS[domain]} MOC</span>
              <span className={styles.tileValue}>{count.toLocaleString()}</span>
            </button>
          );
        })}
      </div>

      <div className={styles.meta}>
        <span className={styles.metaItem}>
          <span className={styles.metaLabel}>Last run</span>
          {formatRelative(status.last_run_at)}
          {status.last_run_status && (
            <span
              className={`${styles.runBadge} ${styles[`run_${status.last_run_status}`] ?? ''}`}
            >
              {RUN_STATUS_LABELS[status.last_run_status] ?? status.last_run_status}
            </span>
          )}
        </span>
        {status.last_commit_sha && (
          <span className={styles.metaItem}>
            <span className={styles.metaLabel}>Commit</span>
            <code className={styles.commitSha}>{status.last_commit_sha.slice(0, 7)}</code>
          </span>
        )}
        {status.deferred > 0 && (
          <span className={`${styles.metaItem} ${styles.warn}`}>
            {status.deferred} deferred
          </span>
        )}
        {status.conflicts > 0 && (
          <span className={`${styles.metaItem} ${styles.danger}`}>
            {status.conflicts} conflict{status.conflicts !== 1 ? 's' : ''}
          </span>
        )}
        {status.archived > 0 && (
          <span className={styles.metaItem}>{status.archived} archived</span>
        )}
      </div>
    </div>
  );
}
