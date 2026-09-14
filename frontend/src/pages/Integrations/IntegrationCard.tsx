import styles from './Integrations.module.css';
import type { IntegrationItem, IntegrationStatus } from './types';

const STATUS_DOT: Record<IntegrationStatus, string> = {
  connected: 'var(--status-ok)',
  disconnected: 'var(--text-faint)',
  error: 'var(--status-danger)',
  expired: 'var(--status-warn)',
  coming_soon: 'var(--accent-pending)',
};

const STATUS_LABEL: Record<IntegrationStatus, string> = {
  connected: 'Connected',
  disconnected: 'Not connected',
  error: 'Error',
  expired: 'Re-auth required',
  coming_soon: 'Coming soon',
};

const KIND_LABEL: Record<string, string> = {
  personal_oauth: 'OAuth',
  personal_push: 'Push sync',
};

function timeAgo(iso: string | null): string {
  if (!iso) return 'Never';
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 60_000) return 'Just now';
  if (ms < 3_600_000) return `${Math.floor(ms / 60_000)}m ago`;
  if (ms < 86_400_000) return `${Math.floor(ms / 3_600_000)}h ago`;
  return `${Math.floor(ms / 86_400_000)}d ago`;
}

export interface IntegrationCardProps {
  item: IntegrationItem;
  /** True while any action on this card is in flight. */
  busy: boolean;
  /**
   * True while an enqueued sync for this card is still being polled —
   * the honest "queued, not yet synced" state. `syncMessage` is the
   * live progress text that goes with it.
   */
  syncing: boolean;
  syncMessage: string;
  onConnect: () => void;
  onSync: () => void;
  onDisconnect: () => void;
}

/**
 * One integration's card. Pure presentation: every decision it makes is
 * a function of its props, and every action is delegated upward. The
 * page owns which integration is busy and which is syncing; the card
 * only owns how that looks.
 */
export default function IntegrationCard({
  item,
  busy,
  syncing,
  syncMessage,
  onConnect,
  onSync,
  onDisconnect,
}: IntegrationCardProps) {
  const accountEmail = item.extra?.account_email as string | undefined;
  const keyPrefix = item.extra?.key_prefix as string | undefined;

  return (
    <article className={syncing ? `${styles.card} ${styles.cardSyncing}` : styles.card}>
      <div className={styles.cardHead}>
        <div className={styles.cardTitle}>
          <span className={styles.iconBox} aria-hidden="true">
            {item.display_name[0]}
          </span>
          <div>
            <strong>{item.display_name}</strong>
            <div className={styles.status}>
              <span
                className={syncing ? `${styles.dot} ${styles.dotPulse}` : styles.dot}
                style={{
                  background: STATUS_DOT[item.status],
                  color: STATUS_DOT[item.status],
                }}
                aria-hidden="true"
              />
              {syncing ? syncMessage || 'Syncing…' : STATUS_LABEL[item.status]}
            </div>
          </div>
        </div>
        <span className={styles.kind}>{KIND_LABEL[item.kind] ?? 'API key'}</span>
      </div>

      <p className={styles.desc}>{item.description}</p>

      {item.status === 'connected' && (
        <div className={styles.meta}>
          Last synced: {timeAgo(item.last_synced_at)}
          {accountEmail && <> · {accountEmail}</>}
          {keyPrefix && <> · key {keyPrefix}</>}
        </div>
      )}

      {item.last_error && (
        <div className={styles.errBanner} title={item.last_error}>
          {item.last_error}
        </div>
      )}

      {item.coming_soon && item.coming_soon_reason && (
        <div className={styles.comingSoonReason} title={item.coming_soon_reason}>
          {item.coming_soon_reason}
        </div>
      )}

      <div className={styles.actions}>
        {item.coming_soon ? (
          <button type="button" disabled title={item.coming_soon_reason ?? ''}>
            Coming soon
          </button>
        ) : item.status === 'connected' ? (
          <>
            {item.kind === 'personal_push' ? (
              <button
                type="button"
                onClick={onConnect}
                disabled={busy}
                title="Revokes the current token and issues a new one"
              >
                {busy ? '…' : 'Reissue token'}
              </button>
            ) : (
              <button
                type="button"
                className={syncing ? styles.syncing : undefined}
                onClick={onSync}
                disabled={busy}
                aria-busy={busy}
                title={syncing ? syncMessage : undefined}
              >
                {syncing ? syncMessage || 'Processing…' : busy ? '…' : 'Sync now'}
              </button>
            )}
            <button
              type="button"
              className={styles.secondary}
              onClick={onDisconnect}
              disabled={busy}
            >
              Disconnect
            </button>
          </>
        ) : (
          <button
            type="button"
            className={styles.primary}
            onClick={onConnect}
            disabled={busy}
          >
            {busy ? '…' : 'Connect'}
          </button>
        )}
        {item.docs_url && (
          <a
            className={styles.docsLink}
            href={item.docs_url}
            target="_blank"
            rel="noreferrer"
          >
            Docs ↗
          </a>
        )}
      </div>
    </article>
  );
}
