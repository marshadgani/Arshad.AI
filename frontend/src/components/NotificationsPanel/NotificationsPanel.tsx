import { type Notification, type Severity } from '../../data/mockData';
import { useFetch } from '../../hooks/useFetch';
import styles from './NotificationsPanel.module.css';

export interface NotificationsPanelProps {
  isOpen: boolean;
  onClose: () => void;
}

const NOTIFICATIONS_URL = '/api/v1/dashboard/notifications';

// The backend endpoint is unbounded (no limit/offset — see system design
// notes). This is a client-side containment measure, not a fix; a separate
// backend ticket covers adding real pagination.
const MAX_NOTIFICATIONS = 20;

const sevClass: Record<Severity, string> = {
  critical: styles.sevCritical,
  warn: styles.sevWarn,
  info: styles.sevInfo,
  ok: styles.sevOk,
};

// Dropdown anchored to the TopBar bell. Rendered unconditionally (never
// unmounted) so the bell's aria-controls target always exists in the DOM;
// visibility is toggled with the native `hidden` attribute. Fetches lazily
// — only while open — via useFetch's `skip` option, and re-fetches fresh
// every time it opens rather than caching, so a dropdown left open for a
// while never shows a stale list.
export function NotificationsPanel({ isOpen }: NotificationsPanelProps) {
  const { data, isLoading, error, refetch } = useFetch<Notification[]>(NOTIFICATIONS_URL, {
    skip: !isOpen,
  });

  const rows = (data ?? []).slice(0, MAX_NOTIFICATIONS);

  return (
    <div
      id="notifications-panel"
      className={styles.panel}
      role="region"
      aria-label="Notifications"
      hidden={!isOpen}
    >
      <div className={styles.header}>Notifications</div>

      {isLoading && (
        <div className={styles.status} role="status">
          Loading…
        </div>
      )}

      {!isLoading && error && (
        <div className={styles.error} role="alert">
          <span>Couldn&apos;t load notifications.</span>
          <button type="button" className={styles.retry} onClick={refetch}>
            Retry
          </button>
        </div>
      )}

      {!isLoading && !error && rows.length === 0 && (
        <div className={styles.status}>No notifications</div>
      )}

      {!isLoading && !error && rows.length > 0 && (
        <ul className={styles.list}>
          {rows.map((n) => (
            <li key={n.id} className={styles.row}>
              <span className={`${styles.pin} ${sevClass[n.severity]}`} aria-hidden="true" />
              <div className={styles.body}>
                <span className={styles.title}>{n.title}</span>
                <span className={styles.detail}>{n.detail}</span>
              </div>
              <span className={styles.time}>{n.time}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
