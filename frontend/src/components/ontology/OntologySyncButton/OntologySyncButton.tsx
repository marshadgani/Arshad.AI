import { useState } from 'react';
import styles from './OntologySyncButton.module.css';

export interface OntologySyncButtonProps {
  onSync: (dryRun: boolean) => void;
  isSyncing: boolean;
  error: Error | null;
  deduplicated?: boolean;
}

/**
 * Triggers a push-sync job (POST /ontology/sync). The dry-run checkbox maps
 * straight to the backend's `dry_run` flag — a preview run that reports
 * counts without committing, useful before a first sync on a new domain.
 */
export function OntologySyncButton({
  onSync,
  isSyncing,
  error,
  deduplicated,
}: OntologySyncButtonProps) {
  const [dryRun, setDryRun] = useState(false);

  return (
    <div className={styles.wrap}>
      <label className={styles.dryRunLabel}>
        <input
          type="checkbox"
          checked={dryRun}
          onChange={(e) => setDryRun(e.target.checked)}
          disabled={isSyncing}
        />
        Dry run
      </label>
      <button
        type="button"
        className={`${styles.button} ${isSyncing ? styles.buttonActive : ''}`}
        onClick={() => onSync(dryRun)}
        disabled={isSyncing}
      >
        <span className={styles.glyph} aria-hidden="true">
          ⟡
        </span>
        {isSyncing ? 'Syncing vault…' : 'Sync Ontology'}
      </button>
      {deduplicated && !isSyncing && !error && (
        <span className={styles.note} role="status">
          A sync is already queued.
        </span>
      )}
      {error && (
        <span className={styles.error} role="alert">
          {error.message}
        </span>
      )}
    </div>
  );
}
