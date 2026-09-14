import { useCallback, useEffect, useMemo, useState } from 'react';

import { ConnectError, connectIntegration } from '../api/integrations';
import { getToken } from '../auth/tokenStorage';
import { ConnectResultBanner } from '../components/ConnectResultBanner';
import { DisconnectDialog } from '../components/DisconnectDialog';
import { SyncJobWatcher } from '../components/SyncJobWatcher';
import type { SyncJobView } from '../hooks/useSyncJob';
import styles from './Integrations.module.css';

const SKELETON_CARD_COUNT = 6;

// The three providers whose sync() enqueues a background DAG job instead
// of syncing synchronously (backend IntegrationProvider.sync_dag_id).
// Mirrors the backend declaration rather than deriving it, since the list
// endpoint doesn't currently expose sync_dag_id to the frontend — kept
// narrow and named so a future provider addition is a one-line change
// here, not a silent gap.
const DAG_BACKED_SLUGS = new Set(['google_calendar', 'gmail', 'github']);

const STALLED_REASON_COPY: Record<string, string> = {
  no_worker_running:
    'Sync queued but no worker is processing it — ENABLE_INPROCESS_WORKER is not set on the server.',
  worker_not_responding: 'Sync queued but the background worker stopped responding.',
  worker_timeout: 'Sync started but did not finish in time — it may need attention.',
};

type IntegrationKind =
  | 'personal_oauth'
  | 'personal_apikey'
  | 'personal_push'
  | 'project_apikey'
  | 'static';
type IntegrationStatus = 'connected' | 'disconnected' | 'error' | 'expired' | 'coming_soon';

interface IntegrationItem {
  slug: string;
  kind: IntegrationKind;
  display_name: string;
  category: string;
  description: string;
  docs_url: string | null;
  icon: string;
  status: IntegrationStatus;
  last_synced_at: string | null;
  last_error: string | null;
  extra: Record<string, unknown>;
  coming_soon: boolean;
  coming_soon_reason: string | null;
  connect_prompt?: { label: string; placeholder: string } | null;
  // FEAT-145: which disconnect confirm/outcome copy to show. 'revokes' —
  // the backend will attempt an upstream token revoke. 'no_revoke' — a
  // real credential is stored locally and will be deleted, but the
  // provider has no revoke API (or the URL isn't wired up yet) so the
  // grant itself stays live until removed from the provider's own
  // dashboard. 'no_credential' — nothing is stored for this slug at all
  // (e.g. Gmail/Calendar share the Google sign-in grant).
  revocation_kind: 'revokes' | 'no_revoke' | 'no_credential';
}

// Status → design token. The value is genuinely dynamic (it depends on
// the row's status), so it rides an inline `style`; the colour itself
// stays in tokens.css per .claude/rules/frontend.md — no hardcoded hex.
const STATUS_DOT: Record<IntegrationStatus, string> = {
  connected: 'var(--status-ok)',
  disconnected: 'var(--status-neutral)',
  error: 'var(--status-danger)',
  expired: 'var(--status-warn)',
  coming_soon: 'var(--status-soon)',
};

const STATUS_LABEL: Record<IntegrationStatus, string> = {
  connected: 'Connected',
  disconnected: 'Not connected',
  error: 'Error',
  expired: 'Re-auth required',
  coming_soon: 'Coming soon',
};

// Machine-readable ?error=<code> values the backend's attach-OAuth flow
// (backend/src/integrations/personal/attach_callback.py) and the legacy
// Phase-H generic callback (backend/src/integrations/routers.py) can
// redirect back with. Kept as an as-const map per .claude/rules/
// frontend.md's enum-alternative guidance, with a default fallback for
// any code not enumerated here.
const ERROR_CODE_LABELS = {
  invalid_state: 'the connect link expired — try again',
  provider_mismatch: 'the connect link did not match that provider',
  access_denied: 'you cancelled the provider consent screen',
  scope_not_granted: 'required permission was not granted — try again and leave every box ticked',
  account_owned_by_another_user: 'that provider account is already linked to a different user',
  provider_already_linked: 'a different account for this provider is already linked',
  user_missing: 'your session user could not be found — sign in again',
  unknown_provider: 'unsupported provider',
  missing_client_id: 'the backend is not configured for this provider yet',
  missing_client_secret: 'the backend is not configured for this provider yet',
  oauth_provider_http_error: 'the provider returned an error',
  oauth_provider_unreachable: 'could not reach the provider',
  callback_crashed: 'something went wrong completing the connection',
} as const;

function errorLabel(code: string | null): string {
  if (code && code in ERROR_CODE_LABELS) {
    return ERROR_CODE_LABELS[code as keyof typeof ERROR_CODE_LABELS];
  }
  return 'unexpected error';
}

function timeAgo(iso: string | null): string {
  if (!iso) return 'Never';
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 60_000) return 'Just now';
  if (ms < 3_600_000) return `${Math.floor(ms / 60_000)}m ago`;
  if (ms < 86_400_000) return `${Math.floor(ms / 3_600_000)}h ago`;
  return `${Math.floor(ms / 86_400_000)}d ago`;
}

export default function Integrations() {
  const [items, setItems] = useState<IntegrationItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actioning, setActioning] = useState<string | null>(null);
  const [apiKeyModal, setApiKeyModal] = useState<IntegrationItem | null>(null);
  const [apiKeyDraft, setApiKeyDraft] = useState('');
  const [apiKeyErr, setApiKeyErr] = useState<string | null>(null);
  // Generic domain/account-input modal for any provider that declares
  // connect_prompt (e.g. Shopify's *.myshopify.com domain). No slug
  // special-casing: any future provider gets this modal automatically.
  const [shopConnectModal, setShopConnectModal] = useState<IntegrationItem | null>(null);
  const [shopDomainDraft, setShopDomainDraft] = useState('');
  const [shopDomainErr, setShopDomainErr] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  // personal_push providers (e.g. Apple Health) hand back a one-time
  // ingest token on connect. Without this, the generic connect flow
  // below silently dropped it after showing a "connected" toast — the
  // user would have no way to configure the Shortcut/webhook that
  // actually needs it.
  const [ingestTokenModal, setIngestTokenModal] = useState<{
    item: IntegrationItem;
    token: string;
  } | null>(null);
  const [tokenCopied, setTokenCopied] = useState(false);
  // slug -> job_id for DAG-backed syncs currently being polled.
  const [syncJobIds, setSyncJobIds] = useState<Record<string, string>>({});
  // slug -> latest polled view, kept for rendering (spinner / stalled banner).
  const [syncJobViews, setSyncJobViews] = useState<Record<string, SyncJobView>>({});
  // Item currently targeted by the disconnect confirmation dialog (FEAT-145).
  // null renders nothing — the dialog's "empty" state.
  const [disconnectTarget, setDisconnectTarget] = useState<IntegrationItem | null>(null);
  const [disconnectError, setDisconnectError] = useState<string | null>(null);

  const fetchAll = async () => {
    const token = getToken();
    if (!token) return;
    setLoading(true);
    try {
      const res = await fetch('/api/v1/integrations', {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const body = (await res.json()) as { data: IntegrationItem[] };
      setItems(body.data ?? []);
      setError(null);
    } catch (e: unknown) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAll();
  }, []);

  // Surfaces the result of the OAuth "attach provider to current user"
  // flow (backend/src/integrations/personal/attach_callback.py) once the
  // browser lands back here. Reads the query string exactly once on
  // mount, then strips it via replaceState so a page refresh can't
  // re-trigger the toast — same pattern as AuthCallback.tsx's fragment
  // handling.
  const [pendingFlash, setPendingFlash] = useState<
    { kind: 'connected'; slug: string } | { kind: 'error'; slug: string | null; code: string | null } | null
  >(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const connected = params.get('connected');
    const err = params.get('error');
    if (connected) {
      setPendingFlash({ kind: 'connected', slug: connected });
      window.history.replaceState({}, '', '/integrations');
    } else if (err) {
      setPendingFlash({ kind: 'error', slug: params.get('slug'), code: err });
      window.history.replaceState({}, '', '/integrations');
    }
  }, []);

  // Surfaced as a persistent banner (not just a toast) because the browser
  // just completed a full-page OAuth redirect round trip — there's no
  // on-screen continuity for the user to anchor a transient toast to. See
  // components/ConnectResultBanner for why.
  const [connectResult, setConnectResult] = useState<
    { kind: 'success' | 'error'; title: string; message?: string } | null
  >(null);

  // Deferred until `items` is populated so the banner can use the
  // provider's display_name instead of its raw slug — items is []
  // on first mount, before fetchAll's response lands.
  useEffect(() => {
    if (!pendingFlash || items.length === 0) return;
    if (pendingFlash.kind === 'connected') {
      const match = items.find((it) => it.slug === pendingFlash.slug);
      setConnectResult({
        kind: 'success',
        title: `${match?.display_name ?? pendingFlash.slug} connected`,
      });
      fetchAll();
    } else {
      setConnectResult({
        kind: 'error',
        title: 'Connect failed',
        message: errorLabel(pendingFlash.code),
      });
      fetchAll();
    }
    setPendingFlash(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingFlash, items]);

  // Page-reload resilience: rehydrate any in-flight DAG-backed sync job so
  // a refresh mid-sync doesn't lose the "Syncing…" state. One job_id-less
  // status call per DAG-backed, connected integration.
  useEffect(() => {
    if (items.length === 0) return;
    const token = getToken();
    if (!token) return;
    for (const it of items) {
      if (!DAG_BACKED_SLUGS.has(it.slug) || it.status !== 'connected') continue;
      if (syncJobIds[it.slug]) continue;
      fetch(`/api/v1/integrations/${it.slug}/sync/status`, {
        headers: { Authorization: `Bearer ${token}` },
      })
        .then(async (res) => {
          if (!res.ok) return; // 404 (no job yet), 401, 409 — nothing to rehydrate
          const body = (await res.json()) as { data: SyncJobView | null };
          const view = body.data;
          if (view && (view.progress === 'processing' || view.progress === 'stalled')) {
            setSyncJobIds((prev) => ({ ...prev, [it.slug]: view.job_id }));
            setSyncJobViews((prev) => ({ ...prev, [it.slug]: view }));
          }
        })
        .catch(() => {});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items]);

  const handleSyncJobUpdate = useCallback((slug: string, view: SyncJobView) => {
    setSyncJobViews((prev) => ({ ...prev, [slug]: view }));
  }, []);

  // Polling gave up (job row gone, backend unreachable). Stop tracking and
  // say so — leaving the card on "Syncing…" forever would be the same kind
  // of dishonest state FEAT-144 exists to remove.
  const handleSyncJobError = (slug: string, err: Error) => {
    flashToast(`Sync status unavailable: ${err.message}`);
    setSyncJobIds((prev) => {
      const next = { ...prev };
      delete next[slug];
      return next;
    });
    setSyncJobViews((prev) => {
      const next = { ...prev };
      delete next[slug];
      return next;
    });
  };

  // Reacts to terminal progress values reported by SyncJobWatcher: toast +
  // refresh on success, toast + refresh (to pick up last_error) on
  // failure, stop tracking either way. 'stalled' is left in place so the
  // persistent card banner keeps showing until the user syncs again.
  useEffect(() => {
    for (const [slug, view] of Object.entries(syncJobViews)) {
      if (!syncJobIds[slug]) continue;
      if (view.progress === 'completed') {
        flashToast('Synced');
        fetchAll();
        setSyncJobIds((prev) => {
          const next = { ...prev };
          delete next[slug];
          return next;
        });
        setSyncJobViews((prev) => {
          const next = { ...prev };
          delete next[slug];
          return next;
        });
      } else if (view.progress === 'failed') {
        flashToast(`Sync failed: ${view.error_text ?? 'unknown error'}`);
        fetchAll();
        // Both maps are cleared, same as the completed branch: a view left
        // behind with no matching job id is state nothing reads and the
        // next sync has to overwrite.
        setSyncJobIds((prev) => {
          const next = { ...prev };
          delete next[slug];
          return next;
        });
        setSyncJobViews((prev) => {
          const next = { ...prev };
          delete next[slug];
          return next;
        });
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [syncJobViews]);

  const grouped = useMemo(() => {
    const sections: Record<string, IntegrationItem[]> = {};
    for (const it of items) {
      (sections[it.category] ??= []).push(it);
    }
    return Object.entries(sections).sort(([a], [b]) => a.localeCompare(b));
  }, [items]);

  const flashToast = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 3000);
  };

  const onConnect = async (item: IntegrationItem) => {
    if (item.kind === 'project_apikey') {
      setApiKeyModal(item);
      setApiKeyDraft('');
      setApiKeyErr(null);
      return;
    }
    if (item.kind === 'personal_oauth' && item.connect_prompt) {
      setShopConnectModal(item);
      setShopDomainDraft('');
      setShopDomainErr(null);
      return;
    }
    // personal_oauth — POST connect; if it returns a redirect_url, navigate there
    setActioning(item.slug);
    try {
      const { redirect_url: url, ingest_token: ingestToken } = await connectIntegration(
        item.slug,
      );
      if (url) {
        window.location.href = url;
        return;
      }
      if (ingestToken) {
        setIngestTokenModal({ item, token: ingestToken });
        setTokenCopied(false);
        await fetchAll();
        return;
      }
      flashToast(`${item.display_name} connected`);
      await fetchAll();
    } catch (e: unknown) {
      flashToast(`Connect failed: ${(e as Error).message}`);
    } finally {
      setActioning(null);
    }
  };

  const copyIngestToken = async () => {
    if (!ingestTokenModal) return;
    try {
      await navigator.clipboard.writeText(ingestTokenModal.token);
      setTokenCopied(true);
      setTimeout(() => setTokenCopied(false), 2000);
    } catch {
      // Clipboard API can be blocked — token remains visible/selectable.
    }
  };

  const submitApiKey = async () => {
    if (!apiKeyModal) return;
    if (!apiKeyDraft.trim()) {
      setApiKeyErr('API key required');
      return;
    }
    setActioning(apiKeyModal.slug);
    try {
      await connectIntegration(apiKeyModal.slug, { api_key: apiKeyDraft.trim() });
      flashToast(`${apiKeyModal.display_name} connected`);
      setApiKeyModal(null);
      setApiKeyDraft('');
      await fetchAll();
    } catch (e: unknown) {
      setApiKeyErr((e as Error).message);
    } finally {
      setActioning(null);
    }
  };

  const submitShopConnect = async () => {
    if (!shopConnectModal) return;
    if (!shopDomainDraft.trim()) {
      setShopDomainErr('Store domain required');
      return;
    }
    setActioning(shopConnectModal.slug);
    try {
      const { redirect_url: url } = await connectIntegration(shopConnectModal.slug, {
        shop: shopDomainDraft.trim(),
      }).catch((e: unknown) => {
        // A failed HMAC or a skewed timestamp means the nonce this modal
        // was opened with is no longer usable — the user's fix is to start
        // the flow again, which the raw upstream message does not say.
        const code = e instanceof ConnectError ? e.code : null;
        if (code === 'invalid_hmac' || code === 'timestamp_skew') {
          throw new Error('Authentication failed. Please click Connect again.');
        }
        throw e;
      });
      if (url) {
        window.location.href = url;
        return;
      }
      flashToast(`${shopConnectModal.display_name} connected`);
      setShopConnectModal(null);
      setShopDomainDraft('');
      await fetchAll();
    } catch (e: unknown) {
      setShopDomainErr((e as Error).message);
    } finally {
      setActioning(null);
    }
  };

  const onSync = async (item: IntegrationItem) => {
    setActioning(item.slug);
    try {
      const token = getToken();
      const res = await fetch(`/api/v1/integrations/${item.slug}/sync`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body?.error?.message ?? `HTTP ${res.status}`);
      const data = body?.data ?? {};
      if (data.mode === 'enqueued' && data.job_id) {
        // Honest state: the sync is queued, not done. A poll (via
        // SyncJobWatcher below) reports completion/failure/stall.
        setSyncJobIds((prev) => ({ ...prev, [item.slug]: data.job_id as string }));
        setSyncJobViews((prev) => {
          const next = { ...prev };
          delete next[item.slug];
          return next;
        });
        flashToast(data.summary ?? 'Sync queued');
      } else {
        flashToast(data.summary ?? 'Synced');
        await fetchAll();
      }
    } catch (e: unknown) {
      flashToast(`Sync failed: ${(e as Error).message}`);
    } finally {
      setActioning(null);
    }
  };

  const openDisconnectDialog = (item: IntegrationItem) => {
    setDisconnectTarget(item);
    setDisconnectError(null);
  };

  const closeDisconnectDialog = () => {
    if (disconnectTarget && actioning === disconnectTarget.slug) return; // ignore close while submitting
    setDisconnectTarget(null);
    setDisconnectError(null);
  };

  const confirmDisconnect = async () => {
    const item = disconnectTarget;
    if (!item) return;
    setActioning(item.slug);
    setDisconnectError(null);
    try {
      const token = getToken();
      const res = await fetch(`/api/v1/integrations/${item.slug}/disconnect`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      const body = await res.json().catch(() => null);
      if (!res.ok) throw new Error(body?.error?.message ?? `HTTP ${res.status}`);
      // A 'failed' upstream revoke must never read as clean success — the
      // local credential is gone either way, but the third-party grant
      // may still be live until the user revokes it manually.
      if (body?.data?.upstream_revocation === 'failed') {
        flashToast(
          `${item.display_name} disconnected here, but revoking with ${item.display_name} failed — remove access in its dashboard too.`,
        );
      } else {
        flashToast(`${item.display_name} disconnected`);
      }
      setDisconnectTarget(null);
      await fetchAll();
    } catch (e: unknown) {
      // Stays open in a retry state — .claude/skills/frontend-design error
      // state, not a toast, since the user needs to decide whether to
      // retry or cancel from within the dialog.
      setDisconnectError((e as Error).message);
    } finally {
      setActioning(null);
    }
  };

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <h1>Integrations</h1>
          <p className={styles.sub}>
            Connect your accounts and infrastructure to power Arshad.AI's chat and dashboard.
          </p>
        </div>
        <button
          type="button"
          className={styles.refresh}
          onClick={fetchAll}
          disabled={loading}
        >
          {loading ? 'Refreshing…' : 'Refresh'}
        </button>
      </header>

      {connectResult && (
        <ConnectResultBanner
          kind={connectResult.kind}
          title={connectResult.title}
          message={connectResult.message}
          onDismiss={() => setConnectResult(null)}
        />
      )}

      {error && (
        <div className={styles.banner} role="alert">
          Failed to load integrations: {error}
        </div>
      )}

      {loading && items.length === 0 && !error && (
        <div className={styles.grid} aria-hidden="true">
          {Array.from({ length: SKELETON_CARD_COUNT }).map((_, i) => (
            <div key={i} className={styles.skeletonCard}>
              <div className={styles.skeletonHead}>
                <span className={`${styles.skeletonBar} ${styles.skeletonIcon}`} />
                <span className={`${styles.skeletonBar} ${styles.skeletonBarMid}`} />
              </div>
              <span className={`${styles.skeletonBar} ${styles.skeletonBarFull}`} />
              <span className={`${styles.skeletonBar} ${styles.skeletonBarWide}`} />
              <span className={`${styles.skeletonBar} ${styles.skeletonBarNarrow}`} />
            </div>
          ))}
        </div>
      )}

      {!loading &&
        !error &&
        grouped.map(([category, list]) => (
        <section key={category} className={styles.section}>
          <h2 className={styles.sectionTitle}>{category}</h2>
          <div className={styles.grid}>
            {list.map((it) => (
              <article
                key={it.slug}
                className={styles.card}
                aria-busy={syncJobViews[it.slug]?.progress === 'processing'}
              >
                <div className={styles.cardHead}>
                  <div className={styles.cardTitle}>
                    <span className={styles.iconBox}>{it.display_name[0]}</span>
                    <div>
                      <strong>{it.display_name}</strong>
                      <div className={styles.status}>
                        <span
                          className={styles.dot}
                          style={{ background: STATUS_DOT[it.status] }}
                        />
                        {STATUS_LABEL[it.status]}
                      </div>
                    </div>
                  </div>
                  <span className={styles.kind}>
                    {it.kind === 'personal_oauth'
                      ? 'OAuth'
                      : it.kind === 'personal_push'
                        ? 'Push sync'
                        : 'API key'}
                  </span>
                </div>

                <p className={styles.desc}>{it.description}</p>

                {it.status === 'connected' && (
                  <div className={styles.meta}>
                    Last synced: {timeAgo(it.last_synced_at)}
                    {(it.extra?.account_email as string) && (
                      <> · {it.extra.account_email as string}</>
                    )}
                    {(it.extra?.key_prefix as string) && (
                      <> · key {it.extra.key_prefix as string}</>
                    )}
                  </div>
                )}

                {it.last_error && (
                  <div className={styles.errBanner} title={it.last_error}>
                    {it.last_error}
                  </div>
                )}

                {syncJobIds[it.slug] && (
                  <SyncJobWatcher
                    slug={it.slug}
                    jobId={syncJobIds[it.slug]}
                    onUpdate={(view) => handleSyncJobUpdate(it.slug, view)}
                    onError={(err) => handleSyncJobError(it.slug, err)}
                  />
                )}

                {syncJobViews[it.slug]?.progress === 'stalled' && (
                  <div className={styles.stalledBanner} role="status" aria-live="polite">
                    <span className={styles.stalledIcon} aria-hidden="true">
                      ⚠
                    </span>
                    {STALLED_REASON_COPY[syncJobViews[it.slug].stalled_reason ?? ''] ??
                      'Sync queued but did not complete.'}
                  </div>
                )}

                {it.coming_soon && it.coming_soon_reason && (
                  <div className={styles.comingSoonReason} title={it.coming_soon_reason}>
                    {it.coming_soon_reason}
                  </div>
                )}

                <div className={styles.actions}>
                  {it.coming_soon ? (
                    <button type="button" disabled title={it.coming_soon_reason ?? ''}>
                      Coming soon
                    </button>
                  ) : it.status === 'connected' ? (
                    <>
                      {it.kind === 'personal_push' ? (
                        <button
                          type="button"
                          onClick={() => onConnect(it)}
                          disabled={actioning === it.slug}
                          title="Revokes the current token and issues a new one"
                        >
                          {actioning === it.slug ? '…' : 'Reissue token'}
                        </button>
                      ) : (
                        <button
                          type="button"
                          className={
                            syncJobViews[it.slug]?.progress === 'processing'
                              ? styles.syncingBtn
                              : undefined
                          }
                          onClick={() => onSync(it)}
                          disabled={
                            actioning === it.slug ||
                            syncJobViews[it.slug]?.progress === 'processing'
                          }
                          aria-busy={syncJobViews[it.slug]?.progress === 'processing'}
                        >
                          {syncJobViews[it.slug]?.progress === 'processing' && (
                            <span
                              className={`${styles.syncDot} ${
                                syncJobViews[it.slug]?.retrying ? styles.retrying : ''
                              }`}
                              aria-hidden="true"
                            />
                          )}
                          {syncJobViews[it.slug]?.progress === 'processing'
                            ? syncJobViews[it.slug]?.retrying
                              ? `Retrying (attempt ${syncJobViews[it.slug].attempt})…`
                              : 'Syncing…'
                            : actioning === it.slug
                              ? '…'
                              : 'Sync now'}
                        </button>
                      )}
                      <button
                        type="button"
                        className={styles.secondary}
                        onClick={() => openDisconnectDialog(it)}
                        disabled={actioning === it.slug}
                      >
                        Disconnect
                      </button>
                    </>
                  ) : (
                    <button
                      type="button"
                      className={styles.primary}
                      onClick={() => onConnect(it)}
                      disabled={actioning === it.slug}
                    >
                      {actioning === it.slug ? '…' : 'Connect'}
                    </button>
                  )}
                  {it.docs_url && (
                    <a
                      className={styles.docsLink}
                      href={it.docs_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Docs ↗
                    </a>
                  )}
                </div>
              </article>
            ))}
          </div>
        </section>
      ))}

      {!loading && !error && items.length === 0 && (
        <div className={styles.empty}>
          <span className={styles.emptyIcon} aria-hidden="true">
            ⌁
          </span>
          <p className={styles.emptyTitle}>No integrations registered</p>
          <p className={styles.emptyDesc}>
            The backend may not have loaded any providers yet. Try refreshing.
          </p>
        </div>
      )}

      {apiKeyModal && (
        <div className={styles.modalBackdrop} onClick={() => setApiKeyModal(null)}>
          <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
            <h3>Connect {apiKeyModal.display_name}</h3>
            <p className={styles.modalDesc}>
              Paste your API key. It will be encrypted at rest with AES-GCM and only the
              first 6 characters shown back.
            </p>
            <input
              type="password"
              className={styles.modalInput}
              placeholder="API key"
              value={apiKeyDraft}
              onChange={(e) => setApiKeyDraft(e.target.value)}
              autoFocus
            />
            {apiKeyErr && <div className={styles.modalErr}>{apiKeyErr}</div>}
            <div className={styles.modalActions}>
              <button
                type="button"
                className={styles.secondary}
                onClick={() => setApiKeyModal(null)}
              >
                Cancel
              </button>
              <button
                type="button"
                className={styles.primary}
                onClick={submitApiKey}
                disabled={actioning === apiKeyModal.slug}
              >
                {actioning === apiKeyModal.slug ? 'Validating…' : 'Connect'}
              </button>
            </div>
          </div>
        </div>
      )}

      {shopConnectModal && (
        <div className={styles.modalBackdrop} onClick={() => setShopConnectModal(null)}>
          <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
            <h3>Connect {shopConnectModal.display_name}</h3>
            <p className={styles.modalDesc}>
              Enter your {shopConnectModal.connect_prompt?.label ?? 'store domain'}. You'll
              be redirected to Shopify to approve access.
            </p>
            <input
              type="text"
              className={styles.modalInput}
              placeholder={shopConnectModal.connect_prompt?.placeholder ?? ''}
              value={shopDomainDraft}
              onChange={(e) => setShopDomainDraft(e.target.value)}
              autoFocus
            />
            {shopDomainErr && <div className={styles.modalErr}>{shopDomainErr}</div>}
            <div className={styles.modalActions}>
              <button
                type="button"
                className={styles.secondary}
                onClick={() => setShopConnectModal(null)}
              >
                Cancel
              </button>
              <button
                type="button"
                className={styles.primary}
                onClick={submitShopConnect}
                disabled={actioning === shopConnectModal.slug}
              >
                {actioning === shopConnectModal.slug ? 'Connecting…' : 'Connect'}
              </button>
            </div>
          </div>
        </div>
      )}

      {ingestTokenModal && (
        <div
          className={styles.modalBackdrop}
          onClick={() => setIngestTokenModal(null)}
        >
          <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
            <h3>{ingestTokenModal.item.display_name} sync token</h3>
            <p className={styles.modalDesc}>
              This token is shown once. Save it now — it's required to configure the
              push (e.g. an iOS Shortcut) that sends data to Arshad.AI.
            </p>
            <div className={styles.modalInput} style={{ userSelect: 'all' }}>
              {ingestTokenModal.token}
            </div>
            <div className={styles.modalActions}>
              <button type="button" className={styles.secondary} onClick={copyIngestToken}>
                {tokenCopied ? 'Copied' : 'Copy'}
              </button>
              <button
                type="button"
                className={styles.primary}
                onClick={() => setIngestTokenModal(null)}
              >
                Done — I've saved it
              </button>
            </div>
          </div>
        </div>
      )}

      {toast && (
        <div className={styles.toast} role="status" aria-live="polite">
          {toast}
        </div>
      )}

      {disconnectTarget && (
        <DisconnectDialog
          displayName={disconnectTarget.display_name}
          revocationKind={disconnectTarget.revocation_kind}
          isSubmitting={actioning === disconnectTarget.slug}
          error={disconnectError}
          onConfirm={confirmDisconnect}
          onCancel={closeDisconnectDialog}
        />
      )}
    </div>
  );
}
