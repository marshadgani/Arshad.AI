import { useEffect, useMemo, useState } from 'react';
import { clearToken, getToken } from '../../auth/tokenStorage';
import { useFetch } from '../../hooks/useFetch';
import styles from './ObsidianExportPanel.module.css';

type Domain = 'calendar' | 'email' | 'github';

interface DomainExportState {
  last_exported_at: string | null;
  notes_written: number;
  last_error: string | null;
}

interface LatestJob {
  job_id: string;
  status: string;
  requested_at: string | null;
  completed_at: string | null;
  error: string | null;
}

interface ExportStatusResponse {
  domains: Record<Domain, DomainExportState>;
  latest_job: LatestJob | null;
}

const DOMAIN_META: Record<Domain, { label: string; glyph: string; accentVar: string }> = {
  calendar: { label: 'Calendar', glyph: '◈', accentVar: '--accent' },
  email: { label: 'Email', glyph: '◇', accentVar: '--accent-health' },
  github: { label: 'GitHub', glyph: '◆', accentVar: '--accent-commerce' },
};

const DOMAINS: Domain[] = ['calendar', 'email', 'github'];

const ACTIVE_JOB_STATUSES = new Set(['pending', 'running', 'in_progress']);

function formatTimestamp(iso: string | null): string {
  if (!iso) return 'Never';
  const date = new Date(iso);
  return date.toLocaleString('en-GB', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export interface ObsidianExportPanelProps {
  /** Base API path — overridable for tests, defaults to the real endpoint. */
  apiBase?: string;
}

export default function ObsidianExportPanel({
  apiBase = '/api/v1/obsidian',
}: ObsidianExportPanelProps) {
  const [selectedDomains, setSelectedDomains] = useState<Set<Domain>>(
    new Set(DOMAINS)
  );
  const [triggering, setTriggering] = useState(false);
  const [triggerError, setTriggerError] = useState<string | null>(null);

  const {
    data: status,
    isLoading,
    error,
    refetch,
  } = useFetch<ExportStatusResponse>(`${apiBase}/export/status`, {
    refreshInterval: 10_000,
  });

  const jobIsActive = Boolean(
    status?.latest_job && ACTIVE_JOB_STATUSES.has(status.latest_job.status)
  );

  // Re-poll faster while a job is actively running so the UI reflects
  // completion promptly without the user needing to refresh manually.
  useEffect(() => {
    if (!jobIsActive) return;
    const id = setInterval(refetch, 3_000);
    return () => clearInterval(id);
  }, [jobIsActive, refetch]);

  const hasEverExported = useMemo(() => {
    if (!status) return false;
    return DOMAINS.some((d) => status.domains[d]?.last_exported_at);
  }, [status]);

  function authHeaders(): Record<string, string> {
    const token = getToken();
    return token ? { Authorization: `Bearer ${token}` } : {};
  }

  function toggleDomain(domain: Domain) {
    setSelectedDomains((prev) => {
      const next = new Set(prev);
      if (next.has(domain)) {
        if (next.size > 1) next.delete(domain);
      } else {
        next.add(domain);
      }
      return next;
    });
  }

  async function handleTriggerExport() {
    setTriggering(true);
    setTriggerError(null);
    try {
      const resp = await fetch(`${apiBase}/export`, {
        method: 'POST',
        headers: { ...authHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ domains: Array.from(selectedDomains) }),
      });
      if (resp.status === 401) {
        clearToken();
        window.location.href = '/login';
        return;
      }
      if (!resp.ok) {
        const body = await resp.text();
        throw new Error(`${resp.status}: ${body.slice(0, 200)}`);
      }
      refetch();
    } catch (err) {
      setTriggerError(
        err instanceof Error ? err.message : 'Export failed to start.'
      );
    } finally {
      setTriggering(false);
    }
  }

  // ── Error state ──────────────────────────────────────────────────
  if (error) {
    return (
      <div className={styles.panel} role="alert">
        <div className={styles.errorState}>
          <span className={styles.errorGlyph} aria-hidden="true">
            ⚠
          </span>
          <p className={styles.errorMessage}>
            Could not load export status — {error.message}
          </p>
          <button type="button" className={styles.retryBtn} onClick={refetch}>
            Retry
          </button>
        </div>
      </div>
    );
  }

  // ── Loading state ────────────────────────────────────────────────
  if (isLoading && !status) {
    return (
      <div className={styles.panel}>
        <div className={styles.grid}>
          {DOMAINS.map((d) => (
            <div key={d} className={styles.skeletonCard} aria-hidden="true">
              <div className={styles.skeletonGlyph} />
              <div className={styles.skeletonLine} />
              <div className={styles.skeletonLineShort} />
            </div>
          ))}
        </div>
        <p className={styles.loadingHint}>Reading export ledger…</p>
      </div>
    );
  }

  const domainsData = status?.domains ?? ({} as Record<Domain, DomainExportState>);
  const latestJob = status?.latest_job ?? null;

  return (
    <div className={styles.panel}>
      <div className={styles.intro}>
        <h2 className={styles.introTitle}>Vault Export</h2>
        <p className={styles.introBody}>
          One-way sync — pushes ingested calendar, email, and GitHub records
          out to your Obsidian vault as structured markdown notes.
        </p>
      </div>

      {/* ── Empty state — never exported anything yet ── */}
      {!hasEverExported && !jobIsActive && (
        <div className={styles.empty}>
          <span className={styles.emptyGlyph} aria-hidden="true">
            ⟡
          </span>
          <p className={styles.emptyText}>
            No records exported yet. Select domains below and run your first
            export.
          </p>
        </div>
      )}

      {/* ── Domain status grid ── */}
      <div className={styles.grid}>
        {DOMAINS.map((domain) => {
          const meta = DOMAIN_META[domain];
          const state = domainsData[domain];
          const isSelected = selectedDomains.has(domain);
          const hasError = Boolean(state?.last_error);

          return (
            <div
              key={domain}
              className={`${styles.domainCard} ${hasError ? styles.domainCardError : ''}`}
              style={{ ['--domain-accent' as string]: `var(${meta.accentVar})` }}
            >
              <label className={styles.domainCardHeader}>
                <input
                  type="checkbox"
                  className={styles.checkbox}
                  checked={isSelected}
                  onChange={() => toggleDomain(domain)}
                  aria-label={`Include ${meta.label} in next export`}
                />
                <span className={styles.domainGlyph} aria-hidden="true">
                  {meta.glyph}
                </span>
                <span className={styles.domainLabel}>{meta.label}</span>
              </label>

              <dl className={styles.domainStats}>
                <div className={styles.statRow}>
                  <dt>Last exported</dt>
                  <dd>{formatTimestamp(state?.last_exported_at ?? null)}</dd>
                </div>
                <div className={styles.statRow}>
                  <dt>Notes written</dt>
                  <dd>{(state?.notes_written ?? 0).toLocaleString()}</dd>
                </div>
              </dl>

              {hasError && (
                <p className={styles.domainError}>{state?.last_error}</p>
              )}
            </div>
          );
        })}
      </div>

      {/* ── Job status + trigger ── */}
      <div className={styles.actionRow}>
        <div className={styles.jobStatus} role="status" aria-live="polite">
          {jobIsActive ? (
            <>
              <span className={styles.spinner} aria-hidden="true" />
              Export {latestJob?.status} — started{' '}
              {formatTimestamp(latestJob?.requested_at ?? null)}
            </>
          ) : latestJob?.status === 'error' ? (
            <span className={styles.jobError}>
              Last export failed: {latestJob.error ?? 'unknown error'}
            </span>
          ) : latestJob ? (
            <span className={styles.jobDone}>
              Last run {latestJob.status} · completed{' '}
              {formatTimestamp(latestJob.completed_at)}
            </span>
          ) : (
            'No export has run yet.'
          )}
        </div>

        <button
          type="button"
          className={styles.exportBtn}
          onClick={handleTriggerExport}
          disabled={triggering || jobIsActive || selectedDomains.size === 0}
        >
          {triggering || jobIsActive ? 'Exporting…' : '⇪ Export to Vault'}
        </button>
      </div>

      {triggerError && (
        <p className={styles.triggerError} role="alert">
          {triggerError}
        </p>
      )}
    </div>
  );
}
