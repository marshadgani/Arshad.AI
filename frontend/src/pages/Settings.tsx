import { Link } from 'react-router-dom';

import SettingsProfile from './SettingsProfile';
import { useAuth } from '../auth/AuthContext';
import { useSignOut } from '../hooks/useSignOut';
import { INTEGRATIONS_PATH } from '../routes/paths';
import styles from './Settings.module.css';

// Composition only: this page decides which sections exist and in what order.
// Profile rendering lives in SettingsProfile, sign-out behaviour in
// useSignOut — so neither concern has to be re-read to change the other.
export default function Settings() {
  const { user } = useAuth();
  const { isSigningOut, signOut } = useSignOut();

  return (
    <div className={styles.page}>
      <h1>Settings</h1>

      <section className={styles.section}>
        <h2>Profile</h2>
        <SettingsProfile user={user} />
      </section>

      <section className={styles.section}>
        <h2>Account</h2>
        <Link to={INTEGRATIONS_PATH}>Manage integrations</Link>
        <button
          type="button"
          className={styles.signOut}
          onClick={signOut}
          disabled={isSigningOut}
        >
          {isSigningOut ? 'Signing out…' : 'Sign out'}
        </button>
      </section>
    </div>
  );
}
