import { useEffect, useMemo, useState } from 'react';

import { getToken } from '../auth/tokenStorage';
import styles from './Integrations.module.css';

interface IntegrationItem {
  slug: string;
  kind: 'personal_oauth' | 'project_apikey';
  display_name: string;
  category: string;
  description: string;
  docs_url: string | null;
  icon: string;
  status: 'connected' | 'disconnected' | 'error' | 'expired';
  last_synced_at: string | null;
  last_error: string | null;
  extra: Record<string, unknown>;
}

const STATUS_DOT: Record<IntegrationItem['status'], string> = {
  connected: '#3fb950',
  disconnected: '#6e7681',
  error: '#f85149',
  expired: '#d29922',
};

const STATUS_LABEL: Record<IntegrationItem['status'], string> = {
  connected: 'Connected',
  disconnected: 'Not connected',
  error: 'Error',
  expired: 'Re-auth required',
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
  const [toast, setToast] = useState<string | null>(null);

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
    // personal_oauth — POST connect; if it returns a redirect_url, navigate there
    setActioning(item.slug);
    try {
      const token = getToken();
      const res = await fetch(`/api/v1/integrations/${item.slug}/connect`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({}),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body?.error?.message ?? `HTTP ${res.status}`);
      const url = body?.data?.redirect_url as string | null;
      if (url) {
        window.location.href = url;
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

  const submitApiKey = async () => {
    if (!apiKeyModal) return;
    if (!apiKeyDraft.trim()) {
      setApiKeyErr('API key required');
      return;
    }
    setActioning(apiKeyModal.slug);
    try {
      const token = getToken();
      const res = await fetch(`/api/v1/integrations/${apiKeyModal.slug}/connect`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ api_key: apiKeyDraft.trim() }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body?.error?.message ?? `HTTP ${res.status}`);
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
                    {it.kind === 'personal_oauth' ? 'OAuth' : 'API key'}
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

                <div className={styles.actions}>
                  {it.status === 'connected' ? (
                    <>
                      <button
                        type="button"
                        onClick={() => onSync(it)}
                        disabled={actioning === it.slug}
                      >
                        {actioning === it.slug ? '…' : 'Sync now'}
                      </button>
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

      {toast && <div className={styles.toast}>{toast}</div>}
    </div>
  );
}
