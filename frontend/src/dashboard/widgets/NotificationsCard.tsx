import { type Notification } from '../../data/mockData';
import { NotificationRow } from '../../notifications';
import { CardHeader } from '../CardHeader';
import styles from '../Dashboard.module.css';

export interface NotificationsCardProps {
  notifications: Notification[] | null;
}

export function NotificationsCard({ notifications }: NotificationsCardProps) {
  const rows = notifications ?? [];

  return (
    <section className={styles.card}>
      <CardHeader title="Notifications" meta={`${rows.length} new`} />
      <div className={styles.list}>
        {rows.map((n) => (
          <NotificationRow key={n.id} notification={n} />
        ))}
      </div>
    </section>
  );
}
