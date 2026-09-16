import { type FormEvent, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { useAuth } from '../auth/AuthContext';
import { useMenuDismiss } from '../hooks/useMenuDismiss';
import { CHAT_PATH, SETTINGS_PATH } from '../routes/paths';
import { NotificationsPanel } from './NotificationsPanel';
import { ProfileMenu } from './ProfileMenu';
import styles from './TopBar.module.css';

export interface TopBarProps {
  onMenuClick: () => void;
  isNavOpen: boolean;
}

type OpenMenu = 'notifications' | 'profile' | null;

export default function TopBar({ onMenuClick, isNavOpen }: TopBarProps) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const initial = (user?.name?.[0] ?? user?.email?.[0] ?? 'A').toUpperCase();

  const [menu, setMenu] = useState<OpenMenu>(null);
  const [capture, setCapture] = useState('');
  const actionsRef = useRef<HTMLDivElement>(null);

  const closeMenu = () => setMenu(null);
  useMenuDismiss(menu !== null, closeMenu, actionsRef);

  const toggleMenu = (name: Exclude<OpenMenu, null>) => {
    // A union of one instead of two independent disclosures makes mutual
    // exclusion structural — opening one always replaces (never joins) the
    // other, so no effect has to enforce "only one open at a time".
    setMenu((current) => (current === name ? null : name));
  };

  const handleCapture = (e: FormEvent) => {
    e.preventDefault();
    const text = capture.trim();
    if (!text) return;
    setCapture('');
    // TopBar's involvement ends at navigation — Chat.tsx owns session
    // creation (and its error surface), then hands the draft down to
    // ChatComposer once a session exists.
    navigate(CHAT_PATH, { state: { draft: text } });
  };

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

      <form className={styles.capture} onSubmit={handleCapture}>
        <label htmlFor="topbar-capture" className="sr-only">
          Quick capture
        </label>
        <input
          id="topbar-capture"
          className={styles.captureInput}
          type="text"
          value={capture}
          onChange={(e) => setCapture(e.target.value)}
          placeholder="Quick capture — start a chat…"
        />
      </form>

      <div className={styles.actions} ref={actionsRef}>
        <button
          type="button"
          className={styles.iconBtn}
          aria-label="Notifications"
          aria-haspopup="true"
          aria-expanded={menu === 'notifications'}
          aria-controls="notifications-panel"
          onClick={() => toggleMenu('notifications')}
        >
          🔔
        </button>
        <button
          type="button"
          className={styles.iconBtn}
          aria-label="Settings"
          onClick={() => navigate(SETTINGS_PATH)}
        >
          ⚙
        </button>
        <button
          type="button"
          className={styles.iconBtn}
          aria-label={user?.name ?? user?.email ?? 'Profile'}
          aria-haspopup="true"
          aria-expanded={menu === 'profile'}
          aria-controls="profile-menu"
          title={user?.email ?? 'Profile'}
          onClick={() => toggleMenu('profile')}
        >
          {initial}
        </button>
        <button
          type="button"
          className={styles.iconBtn}
          onClick={logout}
          aria-label="Sign out"
          title="Sign out"
        >
          ⏻
        </button>

        <NotificationsPanel isOpen={menu === 'notifications'} onClose={closeMenu} />
        <ProfileMenu isOpen={menu === 'profile'} onClose={closeMenu} />
      </div>
    </header>
  );
}
