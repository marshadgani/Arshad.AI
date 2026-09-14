import { type Notification, type Severity } from '../../data/mockData';
import { CardHeader } from '../CardHeader';
import { CardSkeleton, EmptyState } from '../CardStatus';
import styles from '../Dashboard.module.css';

export interface NotificationsCardProps {
  notifications: Notification[] | null;
}

const sevClass: Record<Severity, string> = {
  critical: styles.sevCritical,
  warn: styles.sevWarn,
  info: styles.sevInfo,
  ok: styles.sevOk,
};

export function NotificationsCard({ notifications }: NotificationsCardProps) {
  return (
    <section className={styles.card}>
      <CardHeader
        title="Notifications"
        meta={notifications === null ? '···' : `${notifications.length} new`}
      />
      <div className={styles.list}>
        {notifications === null ? (
          <CardSkeleton />
        ) : notifications.length === 0 ? (
          <EmptyState message="No new notifications." />
        ) : (
          notifications.map((n) => (
            <div key={n.id} className={styles.notif}>
              <span className={`${styles.notifPin} ${sevClass[n.severity]}`} />
              <div className={styles.notifBody}>
                <span className={styles.notifTitle}>{n.title}</span>
                <span className={styles.notifDetail}>{n.detail}</span>
              </div>
              <span className={styles.notifTime}>{n.time}</span>
            </div>
          ))
        )}
      </div>
    </section>
  );
}
