import { RefObject, useRef } from 'react';

import { useAuth } from '../../auth/AuthContext';
import { useDismissable } from '../../hooks/useDismissable';
import styles from './AccountMenu.module.css';

export interface AccountMenuProps {
  isOpen: boolean;
  onClose: () => void;
  triggerRef: RefObject<HTMLButtonElement>;
}

export function AccountMenu({ isOpen, onClose, triggerRef }: AccountMenuProps) {
  const { user, logout } = useAuth();
  const containerRef = useRef<HTMLDivElement>(null);
  const firstItemRef = useRef<HTMLButtonElement>(null);

  useDismissable(isOpen, onClose, containerRef, triggerRef, firstItemRef);

  if (!isOpen) return null;

  const handleSignOut = () => {
    onClose();
    void logout();
  };

  return (
    <div ref={containerRef} role="menu" aria-label="Account" tabIndex={-1} className={styles.menu}>
      {/* role="menu" may only own menuitem/group/separator children;
          without this the identity block is an aria-required-children
          violation. Presentational here is correct — the name and email
          are announced as part of the menu, not as a choosable item. */}
      <div role="presentation" className={styles.identity}>
        {user?.name && <span className={styles.name}>{user.name}</span>}
        <span className={styles.email}>{user?.email ?? 'Not signed in'}</span>
      </div>
      <button
        ref={firstItemRef}
        type="button"
        role="menuitem"
        className={styles.signOut}
        onClick={handleSignOut}
      >
        Sign out
      </button>
    </div>
  );
}
