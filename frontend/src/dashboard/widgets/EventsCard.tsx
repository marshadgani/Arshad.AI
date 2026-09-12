import { type CalendarTag, type Event } from '../../data/mockData';
import { CardHeader } from '../CardHeader';
import styles from '../Dashboard.module.css';

export interface EventsCardProps {
  events: Event[] | null;
}

const calClass: Record<CalendarTag, string> = {
  work: styles.calWork,
  personal: styles.calPersonal,
  family: styles.calFamily,
  health: styles.calHealth,
};

export function EventsCard({ events }: EventsCardProps) {
  return (
    <section className={styles.card}>
      <CardHeader title="My events" meta="today · 3 calendars" />
      <div className={styles.list}>
        {(events ?? []).map((e) => (
          <div key={e.id} className={styles.eventRow}>
            <div className={styles.eventTime}>{e.start}</div>
            <div className={`${styles.eventBar} ${calClass[e.calendar]}`} />
            <div>
              <div className={styles.eventTitle}>{e.title}</div>
              <div className={styles.eventMeta}>{e.calendar} · {e.source} · {e.duration}</div>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
