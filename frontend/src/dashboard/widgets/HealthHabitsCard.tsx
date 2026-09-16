import { type HabitRes } from '../useDashboardData';
import { CardHeader } from '../CardHeader';
import styles from '../Dashboard.module.css';

export interface HealthHabitsCardProps {
  healthHabits: HabitRes[] | null;
}

export function HealthHabitsCard({ healthHabits }: HealthHabitsCardProps) {
  return (
    <section className={styles.card}>
      <CardHeader title="Health & habits" meta="last 24 h" />
      <div className={styles.healthGrid}>
        {(healthHabits ?? []).map((h) => (
          <div key={h.name} className={styles.healthCell}>
            <div className={styles.healthLabel}>{h.name}</div>
            <div className={styles.healthValue}>{h.value}</div>
            <div className={styles.healthDelta}>{h.delta}</div>
          </div>
        ))}
      </div>
    </section>
  );
}
