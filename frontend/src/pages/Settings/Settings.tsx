import { useState } from 'react';
import { Link } from 'react-router-dom';

import { useAuth } from '../auth/AuthContext';
import { INTEGRATIONS_PATH } from '../routes';
import styles from './Settings.module.css';

export default function Settings() {
  const { user, logout } = useAuth();
  const [isSigningOut, setIsSigningOut] = useState(false);

  const handleSignOut = async () => {
    setIsSigningOut(true);
    try {
      // logout() never rejects — AuthContext swallows the server-side
      // logout failure and always clears the local session — but `finally`
      // still covers the case where this component stays mounted (e.g. the
      // redirect hasn't happened yet) so the button doesn't stay disabled.
      await logout();
    } finally {
      setIsSigningOut(false);
    }
  };

  return (
    <div className={styles.page}>
      <h1>Settings</h1>

      <section className={styles.section}>
        <h2>Profile</h2>
        {user ? (
          <>
            <div className={styles.field}>
              <span className={styles.fieldLabel}>Name</span>
              <span className={styles.fieldValue}>{user.name ?? '—'}</span>
            </div>
            <div className={styles.field}>
              <span className={styles.fieldLabel}>Email</span>
              <span className={styles.fieldValue}>{user.email}</span>
            </div>
          </>
        ) : (
          <p className={styles.loadError} role="alert">
            Couldn&rsquo;t load your profile. Your session is still active — sign out and
            back in to retry.
          </p>
        )}
      </section>

      <section className={styles.section}>
        <h2>Account</h2>
        <Link to={INTEGRATIONS_PATH}>Manage integrations</Link>
        <button
          type="button"
          className={styles.signOut}
          onClick={handleSignOut}
          disabled={isSigningOut}
        >
          {isSigningOut ? 'Signing out…' : 'Sign out'}
        </button>
      </section>
    </div>
  );
}
