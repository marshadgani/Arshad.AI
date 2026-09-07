import styles from './health.module.css';
import type { WhoopHRVPoint } from '../../types/whoop';
import { fmtDate } from '../../utils/healthFormat';

export interface HRVTrendCardProps {
  points: WhoopHRVPoint[];
  days: number;
}

/**
 * Bar sparkline of recent HRV readings.
 *
 * Heights are relative to the window's own maximum rather than an absolute
 * scale: healthy HRV varies by an order of magnitude between people, so a
 * fixed axis would flatten the trend for most users. Bars carry a minimum
 * height so a near-zero reading stays visible and hoverable.
 */
function HRVSparkline({ points }: { points: WhoopHRVPoint[] }) {
  if (!points.length) return <p className={styles.empty}>No HRV data</p>;

  const values = points.map((p) => p.hrv_rmssd_milli ?? 0);
  const maxVal = Math.max(...values, 1);

  return (
    <>
      <div className={styles.sparkline}>
        {values.map((v, i) => (
          <div
            key={points[i].date || i}
            className={styles.sparkBar}
            style={{ height: `${Math.max((v / maxVal) * 100, 6)}%` }}
            title={`${points[i].date}: ${v.toFixed(1)} ms`}
          />
        ))}
      </div>
      <div className={styles.sparkLabels}>
        <span>{fmtDate(points[0]?.date ?? null)}</span>
        <span>{fmtDate(points[points.length - 1]?.date ?? null)}</span>
      </div>
    </>
  );
}

export default function HRVTrendCard({ points, days }: HRVTrendCardProps) {
  return (
    <div className={styles.card}>
      <p className={styles.cardTitle}>HRV Trend ({days} days)</p>
      <HRVSparkline points={points} />
    </div>
  );
}
