import styles from './health.module.css';
import type { WhoopWorkout } from '../../types/whoop';
import { fmt1, fmtDate } from '../../utils/healthFormat';

export interface WorkoutsCardProps {
  workouts: WhoopWorkout[];
}

export default function WorkoutsCard({ workouts }: WorkoutsCardProps) {
  return (
    <div className={styles.card} style={{ gridColumn: '1 / -1' }}>
      <p className={styles.cardTitle}>Recent Workouts</p>
      {workouts.length > 0 ? (
        workouts.map((w) => (
          <div key={w.id ?? w.start} className={styles.workout}>
            <div>
              <div className={styles.workoutName}>{w.sport_name ?? 'Activity'}</div>
              <div className={styles.workoutDate}>{fmtDate(w.start)}</div>
            </div>
            <div className={styles.workoutStrain}>{fmt1(w.strain)}</div>
          </div>
        ))
      ) : (
        <p className={styles.empty}>No recent workouts</p>
      )}
    </div>
  );
}
