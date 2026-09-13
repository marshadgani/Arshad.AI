import { useState } from 'react';

import { useOntologyEntities } from '../../../hooks/useOntologyEntities';
import { useOntologyStatus } from '../../../hooks/useOntologyStatus';
import { useTriggerOntologySync } from '../../../hooks/useTriggerOntologySync';
import { OntologyEntityList } from '../OntologyEntityList';
import { OntologyStatusPanel } from '../OntologyStatusPanel';
import { OntologySyncButton } from '../OntologySyncButton';
import styles from './OntologyTab.module.css';

/**
 * The "Ontology" tab of the Obsidian page (FEAT-141).
 *
 * Owns every ontology hook and all cross-component filter state (domain
 * tile selection feeding the entity list's query) so the page component
 * above stays a thin tab router, matching the ShopifyStore.tsx precedent
 * of a page-level state router with feature logic pushed into
 * components/<domain>/.
 */
export function OntologyTab() {
  const { status, isLoading: statusLoading, error: statusError, refetch: refetchStatus } =
    useOntologyStatus();
  const { trigger, isSyncing, result, error: syncError } = useTriggerOntologySync();

  const [activeDomain, setActiveDomain] = useState<string | null>(null);
  const [entityType, setEntityType] = useState('');
  const [syncState, setSyncState] = useState('');

  const {
    entities,
    isLoading: entitiesLoading,
    error: entitiesError,
    hasMore,
    loadMore,
    refetch: refetchEntities,
  } = useOntologyEntities({
    domain: activeDomain ?? undefined,
    entity_type: entityType || undefined,
    sync_state: syncState || undefined,
  });

  async function handleSync(dryRun: boolean) {
    await trigger({ dry_run: dryRun });
    if (!dryRun) {
      refetchStatus();
      refetchEntities();
    }
  }

  return (
    <div className={styles.tab}>
      <div className={styles.header}>
        <div>
          <h2 className={styles.title}>Ontology Layer</h2>
          <p className={styles.subtitle}>
            Linked entities, relationships, and Maps of Content synced from Arshad.AI's
            ingested domains.
          </p>
        </div>
        <OntologySyncButton
          onSync={handleSync}
          isSyncing={isSyncing}
          error={syncError}
          deduplicated={result?.deduplicated}
        />
      </div>

      <OntologyStatusPanel
        status={status}
        isLoading={statusLoading}
        error={statusError}
        activeDomain={activeDomain}
        onSelectDomain={setActiveDomain}
      />

      <OntologyEntityList
        entities={entities}
        isLoading={entitiesLoading}
        error={entitiesError}
        hasMore={hasMore}
        onLoadMore={loadMore}
        entityType={entityType}
        onEntityTypeChange={setEntityType}
        syncState={syncState}
        onSyncStateChange={setSyncState}
        activeDomain={activeDomain}
      />
    </div>
  );
}
