import RecoveryRing from './RecoveryRing';
import styles from './health.module.css';
import type { WhoopRecovery } from '../../types/whoop';
import {
  EM_DASH,
  formatMetric,
  pct,
  recoveryBand,
  recoveryLabel,
} from '../../utils/healthFormat';

export interface RecoveryCardProps {
  recovery: WhoopRecovery | null;
}

const BAND_PILL_CLASS: Record<string, string> = {
  optimal: styles.pillGreen,
  moderate: styles.pillYellow,
  low: styles.pillRed,
};

export default function RecoveryCard({ recovery }: RecoveryCardProps) {
  const score = recovery?.recovery_score ?? null;
  const pillClass = BAND_PILL_CLASS[recoveryBand(score)] ?? '';

  return (
    <div className={styles.card}>
      <p className={styles.cardTitle}>Recovery</p>
      <div className={styles.recoveryCard}>
        <RecoveryRing score={score} />

        {score != null && (
          <span className={`${styles.pill} ${pillClass}`}>{recoveryLabel(score)}</span>
        )}

        <div className={styles.recoveryMeta}>
          <div className={styles.metaStat}>
            <div className={styles.metaVal}>
              {formatMetric(recovery?.hrv_rmssd_milli ?? null, ' ms')}
            </div>
            <div className={styles.metaKey}>HRV</div>
          </div>
          <div className={styles.metaStat}>
            <div className={styles.metaVal}>
              {recovery?.resting_heart_rate != null
                ? `${recovery.resting_heart_rate} bpm`
                : EM_DASH}
            </div>
            <div className={styles.metaKey}>Resting HR</div>
          </div>
          {/* SpO2 only appears on some Whoop hardware, so the tile is
              omitted entirely rather than shown permanently empty. */}
          {recovery?.spo2_percentage != null && (
            <div className={styles.metaStat}>
              <div className={styles.metaVal}>{pct(recovery.spo2_percentage)}</div>
              <div className={styles.metaKey}>SpO₂</div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
