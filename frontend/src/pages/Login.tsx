import { useState } from 'react';

import { useAuth } from '../auth/AuthContext';
import type { OAuthProvider } from '../auth/types';
import styles from './Login.module.css';

const PROVIDERS: ReadonlyArray<{ id: OAuthProvider; label: string }> = [
  { id: 'google', label: 'Continue with Google' },
  { id: 'github', label: 'Continue with GitHub' },
];

export default function Login() {
  const { loginWith } = useAuth();
  const [error, setError] = useState<string | null>(null);
  // Which button triggered the redirect, so only that one shows the busy
  // state during the brief window before the browser navigates away.
  const [pendingProvider, setPendingProvider] = useState<OAuthProvider | null>(null);

  // loginWith throws synchronously from an event handler when the backend
  // origin is unset in production — no error boundary catches that, so
  // without this try/catch the button would silently do nothing.
  const handleLogin = (provider: OAuthProvider) => {
    setError(null);
    setPendingProvider(provider);
    try {
      loginWith(provider);
    } catch (err) {
      setPendingProvider(null);
      setError(err instanceof Error ? err.message : 'Unable to start sign-in.');
    }
  };

  return (
    <div className={styles.wrapper}>
      <div className={styles.card}>
        <p className={styles.eyebrow}>ARSHAD.AI</p>
        <h1 className={styles.title}>Identity Check</h1>
        <p className={styles.subtitle}>Authenticate to unlock the console.</p>

        {error ? (
          <p role="alert" className={styles.error}>
            {error}
          </p>
        ) : null}

        <div className={styles.actions}>
          {PROVIDERS.map(({ id, label }) => {
            const isBusy = pendingProvider === id;
            return (
              <button
                key={id}
                type="button"
                className={styles.button}
                onClick={() => handleLogin(id)}
                disabled={pendingProvider !== null}
                aria-busy={isBusy}
              >
                <span className={styles.buttonLabel}>{isBusy ? 'Redirecting…' : label}</span>
                {isBusy ? <span className={styles.spinner} aria-hidden="true" /> : null}
              </button>
            );
          })}
        </div>

        <p className={styles.footnote}>Session secured via OAuth. No password stored.</p>
      </div>
    </div>
  );
}
