import { useAuth } from '../auth/AuthContext';
import styles from './TopBar.module.css';

export interface TopBarProps {
  onMenuClick: () => void;
  isNavOpen: boolean;
}

export default function TopBar({ onMenuClick, isNavOpen }: TopBarProps) {
  const { user, logout } = useAuth();
  const initial = (user?.name?.[0] ?? user?.email?.[0] ?? 'A').toUpperCase();

  return (
    <header className={styles.topbar}>
      <button
        type="button"
        className={styles.menuBtn}
        onClick={onMenuClick}
        aria-label="Open navigation"
        aria-expanded={isNavOpen}
        aria-controls="app-sidebar"
      >
        ☰
      </button>

      <div className={styles.capture}>
        <span className={styles.captureIcon}>⌘</span>
        <input
          className={styles.captureInput}
          type="text"
          placeholder='Quick capture — type "log expense ₹420 lunch", "remind me 5 pm", or any thought…'
        />
        <span className={styles.kbd}>⌘ K</span>
      </div>

      <div className={styles.actions}>
        <button className={styles.iconBtn} aria-label="Notifications">
          🔔
          <span className={styles.dot} />
        </button>
        <button className={styles.iconBtn} aria-label="Settings">⚙</button>
        <button
          className={styles.iconBtn}
          aria-label={user?.name ?? user?.email ?? 'Profile'}
          title={user?.email ?? 'Profile'}
        >
          {initial}
        </button>
        <button
          className={styles.iconBtn}
          onClick={logout}
          aria-label="Sign out"
          title="Sign out"
        >
          ⏻
        </button>
      </div>
    </header>
  );
}
