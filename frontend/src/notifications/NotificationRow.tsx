import { type Notification, type Severity } from '../data/mockData';
import styles from './NotificationRow.module.css';

export interface NotificationRowProps {
  notification: Notification;
}

const sevClass: Record<Severity, string> = {
  critical: styles.sevCritical,
  warn: styles.sevWarn,
  info: styles.sevInfo,
  ok: styles.sevOk,
};

// Severity must never be colour-only — the pin is paired with a text label
// so the information also reaches users who can't perceive the colour.
const sevLabel: Record<Severity, string> = {
  critical: 'Critical',
  warn: 'Warning',
  info: 'Info',
  ok: 'OK',
};

export function NotificationRow({ notification }: NotificationRowProps) {
  return (
    <div className={styles.notif}>
      <span className={`${styles.pin} ${sevClass[notification.severity]}`} />
      <div className={styles.body}>
        <span className={styles.sevLabel}>{sevLabel[notification.severity]}</span>
        <span className={styles.title}>{notification.title}</span>
        <span className={styles.detail}>{notification.detail}</span>
      </div>
      <span className={styles.time}>{notification.time}</span>
    </div>
  );
}
