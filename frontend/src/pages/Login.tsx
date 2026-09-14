import { useState, type FormEvent } from 'react';

import { AuthRequestError } from '../api/auth';
import { useAuth } from '../auth/AuthContext';
import type { OAuthProvider } from '../auth/types';
import styles from './Login.module.css';

const PROVIDERS: ReadonlyArray<{ id: OAuthProvider; label: string }> = [
  { id: 'google', label: 'Continue with Google' },
  { id: 'github', label: 'Continue with GitHub' },
];

// One busy source of truth for the whole card: password submission and
// each OAuth redirect all set this to a distinct value so every button
// can derive its own disabled/busy state from a single piece of state.
// Two independent busy flags would let the UI reach "password submitting
// AND a Google redirect in flight" — not a state the backend can serve.
type PendingAction = OAuthProvider | 'password' | null;

export default function Login() {
  const { loginWith, loginWithPassword } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<PendingAction>(null);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');

  const handleOAuthLogin = (provider: OAuthProvider) => {
    setError(null);
    setPending(provider);
    try {
      // loginWith throws synchronously from an event handler when the
      // backend origin is unset in production — no error boundary catches
      // that, so without this try/catch the button would silently do
      // nothing.
      loginWith(provider);
    } catch (err) {
      setPending(null);
      setError(err instanceof Error ? err.message : 'Unable to start sign-in.');
    }
  };

  const handlePasswordSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    setPending('password');
    try {
      await loginWithPassword(email, password);
      // Success navigates away via the router once the token/user land in
      // context; nothing further to do here.
    } catch (err) {
      const message =
        err instanceof AuthRequestError
          ? err.message
          : err instanceof Error
            ? err.message
            : 'Unable to sign in.';
      setError(message);
    } finally {
      setPending(null);
    }
  };

  const isBusy = pending !== null;
  const isPasswordSubmitting = pending === 'password';

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

        <form className={styles.passwordForm} onSubmit={handlePasswordSubmit}>
          <label className={styles.fieldLabel} htmlFor="login-email">
            Email
          </label>
          <input
            id="login-email"
            name="email"
            type="email"
            autoComplete="username"
            required
            className={styles.input}
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            disabled={isBusy}
          />

          <label className={styles.fieldLabel} htmlFor="login-password">
            Password
          </label>
          <input
            id="login-password"
            name="password"
            type="password"
            autoComplete="current-password"
            required
            className={styles.input}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            disabled={isBusy}
          />

          <button
            type="submit"
            className={styles.button}
            disabled={isBusy}
            aria-busy={isPasswordSubmitting}
          >
            <span className={styles.buttonLabel}>
              {isPasswordSubmitting ? 'Signing in…' : 'Sign in'}
            </span>
            {isPasswordSubmitting ? <span className={styles.spinner} aria-hidden="true" /> : null}
          </button>
        </form>

        <div className={styles.divider} role="separator" aria-label="or">
          <span className={styles.dividerLabel}>OR</span>
        </div>

        <div className={styles.actions}>
          {PROVIDERS.map(({ id, label }) => {
            const isProviderBusy = pending === id;
            return (
              <button
                key={id}
                type="button"
                className={styles.button}
                onClick={() => handleOAuthLogin(id)}
                disabled={isBusy}
                aria-busy={isProviderBusy}
              >
                <span className={styles.buttonLabel}>
                  {isProviderBusy ? 'Redirecting…' : label}
                </span>
                {isProviderBusy ? <span className={styles.spinner} aria-hidden="true" /> : null}
              </button>
            );
          })}
        </div>

        <p className={styles.footnote}>Session secured via JWT.</p>
      </div>
    </div>
  );
}
