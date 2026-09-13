import { OntologyEmptyState } from '../OntologyEmptyState';
import { OntologyErrorPanel } from '../OntologyErrorPanel';
import { OntologySyncStateBadge } from '../OntologySyncStateBadge';
import {
  ONTOLOGY_ENTITY_TYPES,
  ONTOLOGY_SYNC_STATES,
} from '../../../types/ontology';
import type { OntologyEntity } from '../../../types/ontology';
import styles from './OntologyEntityList.module.css';

export interface OntologyEntityListProps {
  entities: OntologyEntity[];
  isLoading: boolean;
  error: Error | null;
  hasMore: boolean;
  onLoadMore: () => void;
  entityType: string;
  onEntityTypeChange: (value: string) => void;
  syncState: string;
  onSyncStateChange: (value: string) => void;
  activeDomain: string | null;
}

function formatRelative(iso: string | null): string {
  if (!iso) return '—';
  const diffMs = Date.now() - new Date(iso).getTime();
  const mins = Math.round(diffMs / 60_000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

const SKELETON_ROWS = 6;

/**
 * The entity table beneath the MOC status grid. Filters compose with
 * OntologyStatusPanel's domain-tile selection (passed down as
 * `activeDomain`, owned by the page) rather than duplicating a domain
 * filter here.
 *
 * Four states: loading (skeleton rows, first fetch only — gated on
 * entities.length === 0 so a filter change doesn't blank an already
 * populated list), error, empty (filters matched nothing), content.
 */
export function OntologyEntityList({
  entities,
  isLoading,
  error,
  hasMore,
  onLoadMore,
  entityType,
  onEntityTypeChange,
  syncState,
  onSyncStateChange,
  activeDomain,
}: OntologyEntityListProps) {
  return (
    <div className={styles.wrap}>
      <div className={styles.filters}>
        {activeDomain && (
          <span className={styles.domainChip}>
            {activeDomain}
            <span aria-hidden="true"> ·</span>
          </span>
        )}
        <label className={styles.filterLabel}>
          Type
          <select
            className={styles.select}
            value={entityType}
            onChange={(e) => onEntityTypeChange(e.target.value)}
          >
            <option value="">All</option>
            {ONTOLOGY_ENTITY_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.filterLabel}>
          Sync state
          <select
            className={styles.select}
            value={syncState}
            onChange={(e) => onSyncStateChange(e.target.value)}
          >
            <option value="">All</option>
            {ONTOLOGY_SYNC_STATES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
      </div>

      {isLoading && entities.length === 0 ? (
        <div className={styles.list} aria-busy="true">
          {Array.from({ length: SKELETON_ROWS }).map((_, i) => (
            <div key={i} className={`${styles.row} ${styles.rowSkeleton}`}>
              <span className={styles.skeletonBar} />
            </div>
          ))}
          <span className="sr-only" role="status">
            Loading ontology entities…
          </span>
        </div>
      ) : error && entities.length === 0 ? (
        <OntologyErrorPanel message="Failed to load ontology entities." />
      ) : entities.length === 0 ? (
        <OntologyEmptyState
          icon="◇"
          title="No matching entities"
          description="No entities match the current domain/type/sync-state filters. Try broadening them, or run a sync if the vault hasn't been populated yet."
        />
      ) : (
        <>
          <div className={styles.list}>
            {entities.map((entity) => (
              <div key={entity.id} className={styles.row}>
                <div className={styles.rowMain}>
                  <span className={styles.entityType}>{entity.entity_type}</span>
                  <span className={styles.name}>{entity.display_name}</span>
                  <OntologySyncStateBadge state={entity.sync_state} />
                </div>
                <div className={styles.rowMeta}>
                  <code className={styles.path}>{entity.vault_path}</code>
                  {entity.tags.slice(0, 3).map((tag) => (
                    <span key={tag} className={styles.tag}>
                      #{tag}
                    </span>
                  ))}
                  <span className={styles.synced}>
                    synced {formatRelative(entity.last_synced_at)}
                  </span>
                </div>
                {entity.conflict_reason && (
                  <div className={styles.conflictReason}>
                    Conflict: {entity.conflict_reason}
                  </div>
                )}
              </div>
            ))}
          </div>
          {hasMore && (
            <button type="button" className={styles.loadMore} onClick={onLoadMore}>
              Load more
            </button>
          )}
        </>
      )}
    </div>
  );
}
