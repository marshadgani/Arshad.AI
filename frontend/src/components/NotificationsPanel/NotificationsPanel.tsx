import { RefObject, useRef } from 'react';

import { NotificationRow, useNotifications } from '../../notifications';
import { useDismissable } from '../../hooks/useDismissable';
import styles from './NotificationsPanel.module.css';

export interface NotificationsPanelProps {
  isOpen: boolean;
  onClose: () => void;
  triggerRef: RefObject<HTMLButtonElement>;
}

// The popover shell for the bell: dismiss choreography (useDismissable)
// plus the four render states. It names no endpoint and knows no fetch
// policy — useNotifications owns both, including the open-once latch that
// keeps this panel free of requests until the bell is first used.
export function NotificationsPanel({ isOpen, onClose, triggerRef }: NotificationsPanelProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  useDismissable(isOpen, onClose, containerRef, triggerRef);

  const { data, isLoading, error, refetch } = useNotifications(isOpen);

  if (!isOpen) return null;

  const rows = data ?? [];

  return (
    <div
      ref={containerRef}
      role="dialog"
      aria-label="Notifications"
      tabIndex={-1}
      className={styles.panel}
    >
      <div className={styles.header}>
        {rows.length > 0 ? `${rows.length} notification${rows.length === 1 ? '' : 's'}` : 'Notifications'}
      </div>

      {isLoading && (
        <p className={styles.status} role="status">Loading notifications…</p>
      )}

      {error && !isLoading && (
        <div className={styles.error} role="alert">
          <span>Couldn&apos;t load notifications.</span>
          <button type="button" className={styles.retry} onClick={refetch}>
            Retry
          </button>
        </div>
      )}

      {!isLoading && !error && rows.length === 0 && (
        <p className={styles.status}>No notifications</p>
      )}

      {!isLoading && !error && rows.length > 0 && (
        <ul className={styles.list}>
          {rows.map((n) => (
            <li key={n.id}>
              <NotificationRow notification={n} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
