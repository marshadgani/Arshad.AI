import { useState } from 'react';

import ApiKeyModal from './ApiKeyModal';
import ConnectPromptModal from './ConnectPromptModal';
import DisconnectConfirmModal from './DisconnectConfirmModal';
import IngestTokenModal from './IngestTokenModal';
import IntegrationCard from './IntegrationCard';
import styles from './Integrations.module.css';
import type { IntegrationItem } from './types';
import { useConnectFlow } from './useConnectFlow';
import { useDisconnectFlow } from './useDisconnectFlow';
import { useIntegrationsList } from './useIntegrationsList';
import { useSyncRunner } from './useSyncRunner';
import { useToast } from './useToast';

/**
 * Integrations page — composition only.
 *
 * Each concern this screen has now lives behind its own seam: loading
 * the list (useIntegrationsList), the connect conversation and its three
 * modals (useConnectFlow), the enqueue-then-poll sync contract
 * (useSyncRunner), transient feedback (useToast), and how one
 * integration renders (IntegrationCard). What is left here is the part
 * that genuinely belongs to the page: which integration currently has an
 * action in flight, and the page layout.
 */

const SKELETON_CARD_COUNT = 4;

export default function Integrations() {
  const { items, grouped, loading, error, refetch } = useIntegrationsList();
  const { toast, flashToast } = useToast();
  // A single slug at a time, shared by connect, sync, and disconnect:
  // one card can only have one action in flight.
  const [busySlug, setBusySlug] = useState<string | null>(null);

  const connect = useConnectFlow({ setBusySlug, onToast: flashToast, refetch });
  const disconnect = useDisconnectFlow({ setBusySlug, onToast: flashToast, refetch });

  const sync = useSyncRunner({
    // A polled job reaching a terminal phase is the only honest moment to
    // release the button and refresh last_synced_at — that field is
    // written by the ingestion runner, not by the enqueue call.
    onSettled: (message) => {
      flashToast(message);
      setBusySlug(null);
      refetch();
    },
  });

  const onSync = async (item: IntegrationItem) => {
    setBusySlug(item.slug);
    let queued = false;
    try {
      const started = await sync.startSync(item.slug);
      if (started.mode === 'queued') {
        // Nothing has synced yet — stay busy until polling settles.
        queued = true;
        return;
      }
      flashToast(started.summary);
      await refetch();
    } catch (e: unknown) {
      flashToast(`Sync failed: ${(e as Error).message}`);
    } finally {
      if (!queued) setBusySlug(null);
    }
  };

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <h1>Integrations</h1>
          <p className={styles.sub}>
            Connect your accounts and infrastructure to power Arshad.AI's chat and
            dashboard.
          </p>
        </div>
        <button
          type="button"
          className={styles.refresh}
          onClick={refetch}
          disabled={loading}
          aria-busy={loading}
        >
          {loading ? 'Refreshing…' : 'Refresh'}
        </button>
      </header>

      {error && (
        <div className={styles.banner} role="alert">
          <span>Failed to load integrations: {error}</span>
          <button type="button" className={styles.bannerRetry} onClick={refetch}>
            Retry
          </button>
        </div>
      )}

      {loading && items.length === 0 && !error && (
        <div className={styles.grid} aria-hidden="true">
          {Array.from({ length: SKELETON_CARD_COUNT }).map((_, i) => (
            <div key={i} className={styles.skeletonCard}>
              <div className={styles.skeletonRow} />
              <div className={styles.skeletonRow} />
              <div className={styles.skeletonRow} />
            </div>
          ))}
        </div>
      )}

      {grouped.map(([category, list]) => (
        <section key={category} className={styles.section}>
          <h2 className={styles.sectionTitle}>{category}</h2>
          <div className={styles.grid}>
            {list.map((it) => (
              <IntegrationCard
                key={it.slug}
                item={it}
                busy={busySlug === it.slug}
                syncing={sync.pollingSlug === it.slug}
                syncMessage={sync.message}
                onConnect={() => connect.begin(it)}
                onSync={() => onSync(it)}
                onDisconnect={() => disconnect.begin(it)}
              />
            ))}
          </div>
        </section>
      ))}

      {!loading && items.length === 0 && !error && (
        <div className={styles.empty} role="status">
          No integrations registered. Backend may not have loaded providers.
        </div>
      )}

      {connect.apiKey.item && (
        <ApiKeyModal
          item={connect.apiKey.item}
          value={connect.apiKey.value}
          error={connect.apiKey.error}
          busy={busySlug === connect.apiKey.item.slug}
          onChange={connect.apiKey.setValue}
          onSubmit={connect.apiKey.submit}
          onClose={connect.apiKey.close}
        />
      )}

      {connect.prompt.item && (
        <ConnectPromptModal
          item={connect.prompt.item}
          value={connect.prompt.value}
          error={connect.prompt.error}
          busy={busySlug === connect.prompt.item.slug}
          onChange={connect.prompt.setValue}
          onSubmit={connect.prompt.submit}
          onClose={connect.prompt.close}
        />
      )}

      {connect.ingestToken.value && (
        <IngestTokenModal
          item={connect.ingestToken.value.item}
          token={connect.ingestToken.value.token}
          onClose={connect.ingestToken.close}
        />
      )}

      {disconnect.item && (
        <DisconnectConfirmModal
          item={disconnect.item}
          submitting={disconnect.submitting}
          error={disconnect.error}
          onConfirm={disconnect.confirm}
          onClose={disconnect.close}
        />
      )}

      {toast && (
        <div className={styles.toast} role="status" aria-live="polite">
          {toast}
        </div>
      )}
    </div>
  );
}
