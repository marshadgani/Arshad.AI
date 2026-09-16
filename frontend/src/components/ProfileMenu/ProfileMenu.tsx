import { useAuth } from '../../auth/AuthContext';
import styles from './ProfileMenu.module.css';

export interface ProfileMenuProps {
  isOpen: boolean;
  onClose: () => void;
}

// Dropdown anchored to the TopBar profile avatar. Rendered unconditionally
// so the avatar's aria-controls target always exists in the DOM; visibility
// toggled with the native `hidden` attribute. Pure read of AuthContext — no
// fetch, no local state. The standalone sign-out button in TopBar stays;
// this menu is desktop convenience, not a replacement for it.
export function ProfileMenu({ isOpen }: ProfileMenuProps) {
  const { user, logout } = useAuth();
  const displayName = user?.name || user?.email || 'Account';

  return (
    <div id="profile-menu" className={styles.menu} role="region" aria-label="Account" hidden={!isOpen}>
      <div className={styles.identity}>
        <span className={styles.name}>{displayName}</span>
        {user?.email && <span className={styles.email}>{user.email}</span>}
      </div>
      <button type="button" className={styles.signOut} onClick={logout}>
        Sign out
      </button>
    </div>
  );
}
