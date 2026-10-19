import { Link } from 'react-router-dom';

import { useRenderDeployVerdict } from '../../hooks/useRenderDeployVerdict';
import type { RenderVerdict, VerdictResponse } from '../../types/render';
import styles from './RenderDeployVerdict.module.css';

export interface RenderDeployVerdictProps {
  serviceId: string | null;
  deployId: string | null;
}

const BADGE_CLASS: Record<RenderVerdict, string> = {
  regression: styles.verdictRegression,
  neutral: styles.verdictNeutral,
  improvement: styles.verdictImprovement,
  unknown: styles.verdictUnknown,
};

function fmt(value: number | null, digits = 2): string {
  return value === null ? 'n/a' : value.toFixed(digits);
}

function rateDelta(before: number, after: number): string {
  const delta = after - before;
  const sign = delta > 0 ? '+' : '';
  return `${before.toFixed(2)} → ${after.toFixed(2)} errors/min (${sign}${delta.toFixed(2)})`;
}

interface MetricRow {
  label: string;
  before: number | null;
  after: number | null;
}

function metricRows(d: VerdictResponse): MetricRow[] {
  return [
    { label: 'CPU', before: d.cpu_before_mean, after: d.cpu_after_mean },
    { label: 'Memory', before: d.memory_before_mean, after: d.memory_after_mean },
    { label: 'Latency', before: d.latency_before_mean, after: d.latency_after_mean },
  ].filter((r) => r.before !== null || r.after !== null);
}

export default function RenderDeployVerdict({ serviceId, deployId }: RenderDeployVerdictProps) {
  const { data, isLoading, error } = useRenderDeployVerdict(serviceId, deployId);

  if (!serviceId || !deployId) {
    return <p className={styles.empty}>Select a service with a deploy to see its verdict.</p>;
  }
  if (isLoading) {
    return (
      <p className={styles.status} role="status">
        Checking the deploy...
      </p>
    );
  }
  if (error) {
    return (
      <p className={styles.error} role="alert">
        {error.message}
      </p>
    );
  }
  if (!data) return null;

  const rows = metricRows(data);
  return (
    <section className={styles.root} aria-label="Deploy verdict">
      {data.needs_reauth && (
        <div className={styles.reauthBanner} role="alert">
          Render rejected the stored key. <Link to="/integrations">Reconnect Render</Link>
        </div>
      )}
      {!data.connected && (
        <p className={styles.empty}>
          Render is not connected. <Link to="/integrations">Connect it on Integrations</Link>
        </p>
      )}
      <span className={`${styles.verdictBadge} ${BADGE_CLASS[data.verdict]}`}>
        Verdict: {data.verdict}
      </span>

      <table className={styles.metricsTable}>
        <caption className={styles.caption}>Error-level logs, before vs after the deploy</caption>
        <thead>
          <tr>
            <th scope="col">Window</th>
            <th scope="col">Before</th>
            <th scope="col">After</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <th scope="row">Errors</th>
            <td>{data.before_error_count}</td>
            <td>{data.after_error_count}</td>
          </tr>
          {rows.map((r) => (
            <tr key={r.label}>
              <th scope="row">{r.label}</th>
              <td>{fmt(r.before)}</td>
              <td>{fmt(r.after)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className={styles.delta}>{rateDelta(data.before_error_rate, data.after_error_rate)}</p>

      {data.partial_failures.length > 0 && (
        <ul className={styles.chips} aria-label="Degraded sources">
          {data.partial_failures.map((f) => (
            <li key={f} className={styles.warningChip}>
              {f}
            </li>
          ))}
        </ul>
      )}
      {data.log_truncated && (
        <p className={styles.footnote}>Log results were capped; counts may be understated.</p>
      )}
    </section>
  );
}
