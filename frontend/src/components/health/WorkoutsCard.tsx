import styles from './health.module.css';
import type { WhoopWorkout } from '../../types/whoop';
import { fmt1, fmtDate } from '../../utils/healthFormat';

export interface WorkoutsCardProps {
  workouts: WhoopWorkout[];
  /** Non-null when the secondary /workouts fetch failed. Rendered as a
   * distinct red banner rather than folded into the "no data" empty state
   * — the two are different facts for the user. */
  error?: Error | null;
}

export default function WorkoutsCard({ workouts, error = null }: WorkoutsCardProps) {
  const hasData = workouts.length > 0;

  return (
    <div className={styles.card} style={{ gridColumn: '1 / -1' }}>
      <p className={styles.cardTitle}>Recent Workouts</p>
      {hasData && (
        <div role="list">
          {workouts.map((w) => (
            <div key={w.id ?? w.start} role="listitem" className={styles.workout}>
              <div>
                <div className={styles.workoutName}>{w.sport_name ?? 'Activity'}</div>
                <div className={styles.workoutDate}>{fmtDate(w.start)}</div>
              </div>
              <div className={styles.workoutStrain}>{fmt1(w.strain)}</div>
            </div>
          ))}
        </div>
      )}
      {error ? (
        <p role="alert" className={styles.errorBanner}>
          Could not load workouts — retry later
        </p>
      ) : (
        !hasData && <p className={styles.empty}>No recent workouts</p>
      )}
    </div>
  );
}
