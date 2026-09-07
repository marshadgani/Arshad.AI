import styles from './health.module.css';
import type { WhoopSleep } from '../../types/whoop';
import { fmt1, millisToHM, pct } from '../../utils/healthFormat';

export interface SleepCardProps {
  sleep: WhoopSleep | null;
}

function SleepRow({ label, value }: { label: string; value: string }) {
  return (
    <div className={styles.sleepRow}>
      <span className={styles.sleepKey}>{label}</span>
      <span className={styles.sleepVal}>{value}</span>
    </div>
  );
}

export default function SleepCard({ sleep }: SleepCardProps) {
  return (
    <div className={styles.card}>
      <p className={styles.cardTitle}>Last Sleep</p>
      {sleep ? (
        <>
          <SleepRow label="Performance" value={pct(sleep.sleep_performance_percentage)} />
          <SleepRow label="Efficiency" value={pct(sleep.sleep_efficiency_percentage)} />
          <SleepRow label="REM" value={millisToHM(sleep.total_rem_sleep_time_milli)} />
          <SleepRow
            label="Deep"
            value={millisToHM(sleep.total_slow_wave_sleep_time_milli)}
          />
          <SleepRow label="Light" value={millisToHM(sleep.total_light_sleep_time_milli)} />
          {/* Respiratory rate is absent on shorter naps; the row is
              dropped rather than shown blank. */}
          {sleep.respiratory_rate != null && (
            <SleepRow label="Resp. Rate" value={`${fmt1(sleep.respiratory_rate)} rpm`} />
          )}
        </>
      ) : (
        <p className={styles.empty}>No sleep data</p>
      )}
    </div>
  );
}
