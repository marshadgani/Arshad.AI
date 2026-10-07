import { FormEvent, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { useAuth } from '../auth/AuthContext';
import { CHAT_PATH } from '../routes/paths';
import styles from './TopBar.module.css';

export interface TopBarProps {
  onMenuClick: () => void;
  isNavOpen: boolean;
}

export default function TopBar({ onMenuClick, isNavOpen }: TopBarProps) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [capture, setCapture] = useState('');
  const captureRef = useRef<HTMLInputElement>(null);
  const initial = (user?.name?.[0] ?? user?.email?.[0] ?? 'A').toUpperCase();

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        captureRef.current?.focus();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  // Quick capture hands the text to a new chat, prefilled, so you review it
  // and press Send. It never sends on its own.
  const handleCapture = (e: FormEvent) => {
    e.preventDefault();
    const text = capture.trim();
    if (!text) return;
    setCapture('');
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
        <span className={styles.captureIcon}>⌘</span>
        <input
          ref={captureRef}
          className={styles.captureInput}
          type="text"
          value={capture}
          onChange={(e) => setCapture(e.target.value)}
          aria-label="Quick capture"
          placeholder="Quick capture: type a thought or question and press Enter to open it in chat"
        />
        <span className={styles.kbd}>⌘ K</span>
      </form>

      <div className={styles.actions}>
        <button
          type="button"
          className={styles.iconBtn}
          aria-label="Notifications"
          title="Notifications are on the dashboard"
          onClick={() => navigate('/')}
        >
          🔔
        </button>
        <button
          type="button"
          className={styles.iconBtn}
          aria-label="Integrations and settings"
          title="Integrations and settings"
          onClick={() => navigate('/integrations')}
        >
          ⚙
        </button>
        <span
          className={styles.avatar}
          role="img"
          aria-label={user?.name ?? user?.email ?? 'Profile'}
          title={user?.email ?? 'Profile'}
        >
          {initial}
        </span>
        <button
          type="button"
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
