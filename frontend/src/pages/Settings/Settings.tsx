import { useAuth } from '../../auth/AuthContext';
import Toggle from '../../components/Toggle';
import { usePreferences } from '../../hooks/usePreferences';
import styles from './Settings.module.css';

// Local-only page: account identity comes from AuthContext (already loaded
// by the time ProtectedRoutes mounts this route — see App.tsx) and
// preferences read/write localStorage synchronously via usePreferences.
// Neither is a network fetch, so there is no loading/error state to render
// here — same rationale as components/ComingSoonPage for pages with
// nothing to await. If a real settings API is added later, this page
// should switch to useFetch and grow those states then.
export default function Settings() {
  const { user, logout } = useAuth();
  const { preferences, setPreference } = usePreferences();

  const initial = (user?.name?.[0] ?? user?.email?.[0] ?? 'A').toUpperCase();

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <h1 className={styles.title}>Settings</h1>
        <p className={styles.sub}>Account and appearance preferences for Arshad.AI.</p>
      </header>

      <section className={styles.section} aria-labelledby="settings-account">
        <h2 id="settings-account" className={styles.sectionTitle}>
          Account
        </h2>
        <div className={styles.card}>
          <div className={styles.identity}>
            <div className={styles.avatar} aria-hidden="true">
              {initial}
            </div>
            <div className={styles.identityText}>
              <span className={styles.name}>{user?.name ?? 'Arshad'}</span>
              <span className={styles.email}>{user?.email ?? '—'}</span>
            </div>
          </div>
          <button type="button" className={styles.signOut} onClick={() => logout()}>
            Sign out
          </button>
        </div>
      </section>

      <section className={styles.section} aria-labelledby="settings-appearance">
        <h2 id="settings-appearance" className={styles.sectionTitle}>
          Appearance
        </h2>
        <div className={styles.card}>
          <Toggle
            id="reduced-motion"
            label="Reduce motion"
            description="Turns off animated transitions and shimmer effects across the app, independent of your OS setting."
            checked={preferences.reducedMotion}
            onChange={(value) => setPreference('reducedMotion', value)}
          />
        </div>
      </section>
    </div>
  );
}
