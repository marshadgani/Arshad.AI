import styles from './health.module.css';
import type { WhoopStrain } from '../../types/whoop';
import { EM_DASH, fmt1, kilojoulesToKcal } from '../../utils/healthFormat';

export interface StrainCardProps {
  strain: WhoopStrain | null;
}

export default function StrainCard({ strain }: StrainCardProps) {
  return (
    <div className={styles.card}>
      <p className={styles.cardTitle}>Day Strain</p>
      {strain ? (
        <div className={styles.recoveryMeta} style={{ justifyContent: 'flex-start' }}>
          <div className={styles.metaStat}>
            <div className={styles.metaVal} style={{ color: 'var(--status-warn)' }}>
              {fmt1(strain.score)}
            </div>
            <div className={styles.metaKey}>Strain</div>
          </div>
          <div className={styles.metaStat}>
            <div className={styles.metaVal}>
              {strain.average_heart_rate != null
                ? `${strain.average_heart_rate} bpm`
                : EM_DASH}
            </div>
            <div className={styles.metaKey}>Avg HR</div>
          </div>
          <div className={styles.metaStat}>
            <div className={styles.metaVal}>
              {strain.max_heart_rate != null ? `${strain.max_heart_rate} bpm` : EM_DASH}
            </div>
            <div className={styles.metaKey}>Max HR</div>
          </div>
          <div className={styles.metaStat}>
            <div className={styles.metaVal}>{kilojoulesToKcal(strain.kilojoule)}</div>
            <div className={styles.metaKey}>Calories</div>
          </div>
        </div>
      ) : (
        <p className={styles.empty}>No strain data</p>
      )}
    </div>
  );
}
