import { useEffect, useMemo, useState } from 'react';

import { ConnectError, connectIntegration } from '../api/integrations';
import { getToken } from '../auth/tokenStorage';
import styles from './Integrations.module.css';

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
}

const STATUS_DOT: Record<IntegrationStatus, string> = {
  connected: '#3fb950',
  disconnected: '#6e7681',
  error: '#f85149',
  expired: '#d29922',
  coming_soon: '#8957e5',
};

const STATUS_LABEL: Record<IntegrationStatus, string> = {
  connected: 'Connected',
  disconnected: 'Not connected',
  error: 'Error',
  expired: 'Re-auth required',
  coming_soon: 'Coming soon',
};

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
      flashToast(body?.data?.summary ?? 'Synced');
      await fetchAll();
    } catch (e: unknown) {
      flashToast(`Sync failed: ${(e as Error).message}`);
    } finally {
      setActioning(null);
    }
  };

  const onDisconnect = async (item: IntegrationItem) => {
    if (!confirm(`Disconnect ${item.display_name}? Stored credentials will be removed.`)) return;
    setActioning(item.slug);
    try {
      const token = getToken();
      const res = await fetch(`/api/v1/integrations/${item.slug}/disconnect`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      flashToast(`${item.display_name} disconnected`);
      await fetchAll();
    } catch (e: unknown) {
      flashToast(`Disconnect failed: ${(e as Error).message}`);
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

      {error && <div className={styles.banner}>Failed to load integrations: {error}</div>}

      {grouped.map(([category, list]) => (
        <section key={category} className={styles.section}>
          <h2 className={styles.sectionTitle}>{category}</h2>
          <div className={styles.grid}>
            {list.map((it) => (
              <article key={it.slug} className={styles.card}>
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
                          onClick={() => onSync(it)}
                          disabled={actioning === it.slug}
                        >
                          {actioning === it.slug ? '…' : 'Sync now'}
                        </button>
                      )}
                      <button
                        type="button"
                        className={styles.secondary}
                        onClick={() => onDisconnect(it)}
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

      {!loading && items.length === 0 && (
        <div className={styles.empty}>
          No integrations registered. Backend may not have loaded providers.
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

      {toast && <div className={styles.toast}>{toast}</div>}
    </div>
  );
}
