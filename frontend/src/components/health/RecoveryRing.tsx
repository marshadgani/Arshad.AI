import { recoveryColor } from '../../utils/healthFormat';
import styles from './health.module.css';

export interface RecoveryRingProps {
  score: number | null;
}

const RING_RADIUS = 50;
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS;

/**
 * Circular recovery gauge.
 *
 * The arc is drawn by offsetting a full-circumference dash, so the ring
 * animates via CSS on stroke-dashoffset rather than re-rendering geometry.
 * A null score draws an empty ring (not a zero-score ring) and shows a
 * dash, keeping "no data" visually distinct from "recovery is 0".
 */
export default function RecoveryRing({ score }: RecoveryRingProps) {
  // Whoop can report marginally above 100; clamping keeps the arc closed.
  const fraction = score != null ? Math.min(score, 100) / 100 : 0;
  const color = recoveryColor(score);

  return (
    <div className={styles.ringWrap}>
      <svg className={styles.ring} viewBox="0 0 120 120">
        <circle className={styles.ringBg} cx="60" cy="60" r={RING_RADIUS} />
        <circle
          className={styles.ringFill}
          cx="60"
          cy="60"
          r={RING_RADIUS}
          stroke={color}
          strokeDasharray={RING_CIRCUMFERENCE}
          strokeDashoffset={RING_CIRCUMFERENCE - fraction * RING_CIRCUMFERENCE}
        />
      </svg>
      <div className={styles.ringScore}>
        <div className={styles.ringScoreNum} style={{ color }}>
          {score != null ? Math.round(score) : '—'}
        </div>
        <div className={styles.ringScoreLabel}>recovery</div>
      </div>
    </div>
  );
}
