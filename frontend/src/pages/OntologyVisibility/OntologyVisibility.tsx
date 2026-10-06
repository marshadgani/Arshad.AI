import { useState } from 'react';
import { Link } from 'react-router-dom';

import { useFetch } from '../../hooks/useFetch';
import type { EntityList, Filter } from './types';
import { EntityType, EXPORT_COMMAND, parseFilter, Visibility, VAULT_REPO } from './types';
import { useVisibilityMutation } from './useVisibilityMutation';
import styles from './OntologyVisibility.module.css';

export type OntologyVisibilityProps = Readonly<{
  pageSize?: number;
}>;

export default function OntologyVisibility({ pageSize = 20 }: OntologyVisibilityProps) {
  const [offset, setOffset] = useState(0);
  const [typeFilter, setTypeFilter] = useState<Filter<EntityType>>('');
  const [visibilityFilter, setVisibilityFilter] = useState<Filter<Visibility>>('');
  const [overrides, setOverrides] = useState<Record<string, Visibility>>({});
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bannerDismissed, setBannerDismissed] = useState(false);

  const { changing, mutationError, changed, mutate } = useVisibilityMutation();

  const params = new URLSearchParams({ limit: String(pageSize), offset: String(offset) });
  if (typeFilter) params.set('type', typeFilter);
  if (visibilityFilter) params.set('visibility', visibilityFilter);
  const { data, isLoading, error, refetch } = useFetch<EntityList>(
    `/api/v1/ontology/entities?${params.toString()}`,
  );

  const entities = data?.entities ?? [];
  const total = data?.total ?? 0;
  const visibilityOf = (id: string, base: Visibility): Visibility => overrides[id] ?? base;
  const hasPerson = entities.some((e) => e.entity_type === EntityType.Person);
  const allSelected = entities.length > 0 && entities.every((e) => selected.has(e.id));

  async function handleMutate(ids: readonly string[], visibility: Visibility) {
    const updatedIds = await mutate(ids, visibility);
    if (updatedIds !== null) {
      setOverrides((prev) => ({
        ...prev,
        ...Object.fromEntries(updatedIds.map((id) => [id, visibility])),
      }));
      setSelected(new Set());
    } else {
      refetch();
    }
  }

  function toggleSelected(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAll() {
    setSelected(allSelected ? new Set() : new Set(entities.map((e) => e.id)));
  }

  function changeFilter<T extends string>(setter: (v: T) => void, value: T) {
    setter(value);
    setOffset(0);
    setSelected(new Set());
  }

  const selectedIds = [...selected];

  return (
    <div className={styles.page}>
      <h1 className={styles.title}>Entity Visibility</h1>
      <p className={styles.help}>
        Public means the note will be written to the private vault repo {VAULT_REPO} on the next
        export. Private entities are never exported.
      </p>

      {hasPerson && !bannerDismissed && (
        <div className={styles.notice} role="note">
          <span>
            Person entities represent GitHub contributors, who may be other people. Publishing a
            person writes their GitHub login name to the private vault repo {VAULT_REPO}.
          </span>
          <button
            type="button"
            className={styles.btn}
            onClick={() => setBannerDismissed(true)}
          >
            Dismiss
          </button>
        </div>
      )}

      <div className={styles.filters}>
        <label className={styles.field}>
          Type
          <select
            value={typeFilter}
            onChange={(e) => changeFilter(setTypeFilter, parseFilter(EntityType, e.target.value))}
          >
            <option value="">All</option>
            <option value="person">Person</option>
            <option value="project">Project</option>
          </select>
        </label>
        <label className={styles.field}>
          Visibility
          <select
            value={visibilityFilter}
            onChange={(e) =>
              changeFilter(setVisibilityFilter, parseFilter(Visibility, e.target.value))
            }
          >
            <option value="">All</option>
            <option value="public">Public</option>
            <option value="private">Private</option>
          </select>
        </label>
      </div>

      {mutationError && (
        <div className={styles.error} role="alert">
          {mutationError}
        </div>
      )}

      {isLoading && (
        <ul className={styles.list} aria-busy="true" aria-label="Loading entities">
          {[0, 1, 2].map((i) => (
            <li key={i} className={`${styles.row} ${styles.skeleton}`} />
          ))}
        </ul>
      )}

      {!isLoading && error && (
        <div className={styles.error} role="alert">
          <span>Could not load entities.</span>
          <button type="button" className={styles.btn} onClick={refetch}>
            Retry
          </button>
        </div>
      )}

      {!isLoading && !error && entities.length === 0 && (
        <p className={styles.empty}>
          No entities found. <Link to="/obsidian">Sync your vault</Link> and run the ontology
          extraction first.
        </p>
      )}

      {!isLoading && !error && entities.length > 0 && (
        <>
          <div className={styles.bulk}>
            <label className={styles.check}>
              <input type="checkbox" checked={allSelected} onChange={toggleAll} />
              Select all in view
            </label>
            {selectedIds.length > 0 && (
              <>
                <span>{selectedIds.length} selected</span>
                <button
                  type="button"
                  className={styles.btn}
                  onClick={() => void handleMutate(selectedIds, Visibility.Public)}
                >
                  Publish selected
                </button>
                <button
                  type="button"
                  className={styles.btn}
                  onClick={() => void handleMutate(selectedIds, Visibility.Private)}
                >
                  Unpublish selected
                </button>
              </>
            )}
          </div>

          <ul className={styles.list}>
            {entities.map((e) => {
              const vis = visibilityOf(e.id, e.visibility);
              const target =
                vis === Visibility.Public ? Visibility.Private : Visibility.Public;
              const busy = changing.has(e.id);
              return (
                <li key={e.id} className={styles.row}>
                  <input
                    type="checkbox"
                    className={styles.rowCheck}
                    aria-label={`Select ${e.external_key}`}
                    checked={selected.has(e.id)}
                    onChange={() => toggleSelected(e.id)}
                  />
                  <span className={styles.kind}>{e.entity_type}</span>
                  <span className={styles.key}>{e.external_key}</span>
                  <span
                    className={
                      vis === Visibility.Public ? styles.badgePublic : styles.badgePrivate
                    }
                  >
                    {vis}
                  </span>
                  <button
                    type="button"
                    className={styles.btn}
                    disabled={busy}
                    aria-label={`Set ${e.external_key} to ${target}`}
                    onClick={() => void handleMutate([e.id], target)}
                  >
                    {busy ? 'Saving…' : `Make ${target}`}
                  </button>
                </li>
              );
            })}
          </ul>

          <div className={styles.pager}>
            <button
              type="button"
              className={styles.btn}
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - pageSize))}
            >
              Previous
            </button>
            <span>
              {offset + 1}–{Math.min(offset + pageSize, total)} of {total}
            </span>
            <button
              type="button"
              className={styles.btn}
              disabled={offset + pageSize >= total}
              onClick={() => setOffset(offset + pageSize)}
            >
              Next
            </button>
          </div>
        </>
      )}

      {changed && (
        <div className={styles.cli} role="status">
          <p>Visibility saved. Nothing is exported automatically. To export, run:</p>
          <pre>
            <code>{EXPORT_COMMAND}</code>
          </pre>
        </div>
      )}
    </div>
  );
}
