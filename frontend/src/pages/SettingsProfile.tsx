import type { AuthUser } from '../auth/AuthContext';
import styles from './SettingsProfile.module.css';

export interface SettingsProfileProps {
  user: AuthUser | null;
}

// Presentational: renders whatever user record it is handed, including the
// null case, and never reaches into the auth context itself. That keeps
// "what does a missing profile look like" one decision in one place instead
// of a branch tangled through the page's layout.
export default function SettingsProfile({ user }: SettingsProfileProps) {
  if (!user) {
    return (
      <p className={styles.loadError} role="alert">
        Couldn&rsquo;t load your profile. Your session is still active &mdash; sign out and
        back in to retry.
      </p>
    );
  }

  return (
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
  );
}
