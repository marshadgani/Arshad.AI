import type { AppleHealthSnapshot } from '../../types/appleHealth';
import { formatCount, formatMetric, timeAgo } from '../../utils/healthFormat';
import styles from './AppleHealthCard.module.css';

export interface AppleHealthMetricsProps {
  snapshot: AppleHealthSnapshot;
}

/**
 * The metric grid — the only part of the card that reads biometric values.
 *
 * Each tile is described by data rather than hand-written six times over,
 * so adding a metric is one row here instead of a copy-pasted block of
 * JSX that has to get the class names right again.
 */

interface Tile {
  label: string;
  value: (s: AppleHealthSnapshot) => string;
}

const TILES: Tile[] = [
  { label: 'Resting HR', value: (s) => formatMetric(s.resting_heart_rate, ' bpm') },
  { label: 'HRV', value: (s) => formatMetric(s.heart_rate_variability_ms, ' ms') },
  { label: 'Sleep', value: (s) => formatMetric(s.sleep_hours, 'h', 1) },
  { label: 'Active Energy', value: (s) => formatMetric(s.active_energy_kcal, ' kcal') },
  { label: 'Steps', value: (s) => formatCount(s.steps) },
  { label: 'VO2 Max', value: (s) => formatMetric(s.vo2_max, '', 1) },
];

export default function AppleHealthMetrics({ snapshot }: AppleHealthMetricsProps) {
  const freshness = timeAgo(snapshot.received_at);

  return (
    <>
      <div className={styles.metricsGrid}>
        {TILES.map((tile) => (
          <div key={tile.label} className={styles.metric}>
            <div className={styles.metricVal}>{tile.value(snapshot)}</div>
            <div className={styles.metricKey}>{tile.label}</div>
          </div>
        ))}
      </div>
      {freshness && <p className={styles.freshness}>Last push {freshness}</p>}
    </>
  );
}
