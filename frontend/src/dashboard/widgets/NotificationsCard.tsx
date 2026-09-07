import { type Notification, type Severity } from '../../data/mockData';
import { CardHeader } from '../CardHeader';
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
  const rows = notifications ?? [];

  return (
    <section className={styles.card}>
      <CardHeader title="Notifications" meta={`${rows.length} new`} />
      <div className={styles.list}>
        {rows.map((n) => (
          <div key={n.id} className={styles.notif}>
            <span className={`${styles.notifPin} ${sevClass[n.severity]}`} />
            <div className={styles.notifBody}>
              <span className={styles.notifTitle}>{n.title}</span>
              <span className={styles.notifDetail}>{n.detail}</span>
            </div>
            <span className={styles.notifTime}>{n.time}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
