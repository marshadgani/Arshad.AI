import styles from './OntologySyncStateBadge.module.css';

export interface OntologySyncStateBadgeProps {
  state: string;
}

const LABELS: Record<string, string> = {
  pending: 'Pending',
  synced: 'Synced',
  deferred: 'Deferred',
  conflict: 'Conflict',
  archived: 'Archived',
};

/**
 * Small coloured pill for an entity's `sync_state`. A dedicated component
 * (rather than inline classnames) because this exact mapping — state string
 * to label + colour — is needed in both OntologyEntityList rows and any
 * future detail view; duplicating the switch would let the two drift.
 */
export function OntologySyncStateBadge({ state }: OntologySyncStateBadgeProps) {
  const known = LABELS[state] !== undefined;
  return (
    <span
      className={`${styles.badge} ${known ? styles[state] : styles.unknown}`}
      title={`Sync state: ${state}`}
    >
      <span className={styles.dot} aria-hidden="true" />
      {LABELS[state] ?? state}
    </span>
  );
}
