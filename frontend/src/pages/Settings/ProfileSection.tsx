import type { AuthUser } from '../../auth/AuthContext';
import styles from './ProfileSection.module.css';

export interface ProfileSectionProps {
  user: AuthUser | null;
}

// Presentational: it renders whatever user record it is handed, including the
// null case, and never reaches into the auth context itself. That keeps the
// "what does a missing profile look like" decision in one component rather
// than tangled into the page's layout.
export default function ProfileSection({ user }: ProfileSectionProps) {
  if (!user) {
    return (
      <p className={styles.loadError} role="alert">
        Couldn&rsquo;t load your profile. Your session is still active — sign out and back in
        to retry.
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
