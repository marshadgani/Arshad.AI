import { useRef } from 'react';
import { Link } from 'react-router-dom';

import { AccountMenu } from './AccountMenu';
import { NotificationsPanel } from './NotificationsPanel';
import { QuickCapture } from './QuickCapture';
import { useAuth } from '../auth/AuthContext';
import { useExclusiveDisclosure } from '../hooks/useExclusiveDisclosure';
import { INTEGRATIONS_PATH } from '../routes';
import styles from './TopBar.module.css';

export interface TopBarProps {
  onMenuClick: () => void;
  isNavOpen: boolean;
}

type Surface = 'notifications' | 'account';

// Layout and wiring only. Each control in the bar delegates to a component
// that owns its own state and behaviour — capture to QuickCapture, the
// bell to NotificationsPanel, the avatar to AccountMenu — so TopBar holds
// no transient input state, no transport and no global listeners of its
// own. What it does own is the one thing that is genuinely shared between
// its children: which single popover is open.
export default function TopBar({ onMenuClick, isNavOpen }: TopBarProps) {
  const { user } = useAuth();
  const initial = (user?.name?.[0] ?? user?.email?.[0] ?? 'A').toUpperCase();

  const surface = useExclusiveDisclosure<Surface>();
  const isNotificationsOpen = surface.isOpen('notifications');
  const isAccountOpen = surface.isOpen('account');

  const bellRef = useRef<HTMLButtonElement>(null);
  const avatarRef = useRef<HTMLButtonElement>(null);

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

      <QuickCapture hotkeyPaused={surface.openId !== null} />

      <div className={styles.actions}>
        <button
          ref={bellRef}
          type="button"
          className={styles.iconBtn}
          aria-label="Notifications"
          aria-haspopup="dialog"
          aria-expanded={isNotificationsOpen}
          onClick={() => surface.toggle('notifications')}
        >
          🔔
        </button>
        <NotificationsPanel
          isOpen={isNotificationsOpen}
          onClose={surface.close}
          triggerRef={bellRef}
        />

        <Link
          to={INTEGRATIONS_PATH}
          className={styles.iconBtn}
          aria-label="Settings and integrations"
          title="Settings and integrations"
        >
          ⚙
        </Link>

        <button
          ref={avatarRef}
          type="button"
          className={styles.iconBtn}
          aria-label={user?.name ?? user?.email ?? 'Profile'}
          aria-haspopup="menu"
          aria-expanded={isAccountOpen}
          title={user?.email ?? 'Profile'}
          onClick={() => surface.toggle('account')}
        >
          {initial}
        </button>
        <AccountMenu isOpen={isAccountOpen} onClose={surface.close} triggerRef={avatarRef} />
      </div>
    </header>
  );
}
