import { useEffect, useMemo, useState } from 'react';

import { useAuth } from '../auth/AuthContext';
import { loginErrorMessage, readLoginErrorCode } from '../auth/loginErrors';
import type { OAuthProvider } from '../auth/providers';
import { useNavigationHandoff } from '../hooks/useNavigationHandoff';
import styles from './Login.module.css';

const STUCK_RESET_MS = 10_000;

type ProviderDef = {
  id: OAuthProvider;
  label: string;
  glyph: string;
};

// Presentation only — the provider *identities* are owned by
// `auth/providers.ts` (and ultimately the backend registry); this list adds
// the label and glyph for each. Data-driven so a provider is added/removed
// here, never by hand-editing JSX. An empty list falls through to the empty
// state below instead of silently rendering a blank card.
const PROVIDERS: ProviderDef[] = [
  { id: 'google', label: 'Continue with Google', glyph: 'G' },
  { id: 'github', label: 'Continue with GitHub', glyph: '⌘' },
];

export default function Login() {
  const { loginWith } = useAuth();
  const { isHandingOff, start } = useNavigationHandoff(STUCK_RESET_MS);
  const [errorCode, setErrorCode] = useState<string | null>(() => readLoginErrorCode());

  const errorMessage = useMemo(() => loginErrorMessage(errorCode), [errorCode]);

  useEffect(() => {
    if (!errorCode) return;
    // Strip ?error=... immediately so a refresh or share of the URL never
    // re-surfaces a stale failure — same technique AuthCallback.tsx uses
    // to scrub the one-time token fragment.
    window.history.replaceState(null, '', '/login');
  }, [errorCode]);

  const handleClick = (provider: OAuthProvider) => {
    start(() => {
      setErrorCode(null);
      loginWith(provider);
    });
  };

  return (
    <div className={styles.page}>
      <div className={styles.card} data-state={isHandingOff ? 'loading' : 'content'}>
        <span className={styles.eyebrow}>Secure Access</span>
        <h1 className={styles.title}>Arshad.AI</h1>
        <p className={styles.subtitle}>Sign in to continue</p>
        <div className={styles.divider} aria-hidden="true" />

        {errorMessage && (
          <div className={styles.errorBanner} role="alert">
            <span className={styles.errorIcon} aria-hidden="true">
              !
            </span>
            <p>{errorMessage}</p>
          </div>
        )}

        {PROVIDERS.length === 0 ? (
          <p className={styles.emptyState}>
            No sign-in providers are configured. Contact the administrator.
          </p>
        ) : (
          <div className={styles.providers}>
            {PROVIDERS.map((provider) => (
              <button
                key={provider.id}
                type="button"
                className={`${styles.button} ${styles[provider.id]}`}
                onClick={() => handleClick(provider.id)}
                disabled={isHandingOff}
                aria-busy={isHandingOff}
              >
                <span className={styles.glyph} aria-hidden="true">
                  {provider.glyph}
                </span>
                <span>{isHandingOff ? 'Redirecting…' : provider.label}</span>
              </button>
            ))}
          </div>
        )}

        {isHandingOff && (
          <p className={styles.statusLine} role="status" aria-live="polite">
            <span className={styles.pulseDot} aria-hidden="true" />
            Handing off to your provider…
          </p>
        )}
      </div>
    </div>
  );
}
