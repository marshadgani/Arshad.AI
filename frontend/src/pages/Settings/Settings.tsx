import { Link } from 'react-router-dom';

import ProfileSection from './ProfileSection';
import { useAuth } from '../../auth/AuthContext';
import { useSignOut } from '../../hooks/useSignOut';
import { INTEGRATIONS_PATH } from '../../routes';
import styles from './Settings.module.css';

export default function Settings() {
  const { user } = useAuth();
  const { isSigningOut, signOut } = useSignOut();

  return (
    <div className={styles.page}>
      <h1>Settings</h1>

      <section className={styles.section}>
        <h2>Profile</h2>
        <ProfileSection user={user} />
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
