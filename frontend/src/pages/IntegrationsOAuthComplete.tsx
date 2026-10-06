import { useEffect, useRef } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';

import { getToken } from '../auth/tokenStorage';
import styles from './IntegrationsOAuthComplete.module.css';

function errorTarget(code: string, slug: string | null): string {
  const q = new URLSearchParams({ error: code });
  if (slug) q.set('slug', slug);
  return `/integrations?${q.toString()}`;
}

export default function IntegrationsOAuthComplete() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const started = useRef(false);

  useEffect(() => {
    // The pending key is single use; StrictMode's double effect must not POST twice.
    if (started.current) return;
    started.current = true;

    const pending = params.get('pending');
    const slug = params.get('slug');
    if (!pending || !slug) {
      navigate(errorTarget('missing_pending_params', slug), { replace: true });
      return;
    }

    (async () => {
      try {
        const token = getToken();
        const res = await fetch('/api/v1/integrations/oauth-complete', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify({ pending_key: pending, slug }),
        });
        if (res.ok) {
          navigate(`/integrations?connected=${encodeURIComponent(slug)}`, { replace: true });
          return;
        }
        let code = res.status === 401 ? 'session_expired' : 'internal_error';
        try {
          const body = (await res.json()) as { error?: { code?: string } };
          code = body?.error?.code ?? code;
        } catch {
          // non-JSON error body: keep the generic code
        }
        navigate(errorTarget(code, slug), { replace: true });
      } catch {
        navigate(errorTarget('internal_error', slug), { replace: true });
      }
    })();
  }, [params, navigate]);

  return (
    <div className={styles.wrap} role="status" aria-live="polite">
      <div className={styles.spinner} aria-hidden="true" />
      <p>Connecting…</p>
    </div>
  );
}
