import styles from './HealthFitness.module.css';
import { useFetch } from '../hooks/useFetch';

interface WhoopRecovery {
  recovery_score: number | null;
  hrv_rmssd_milli: number | null;
  resting_heart_rate: number | null;
  skin_temp_celsius: number | null;
  spo2_percentage: number | null;
  cycle_id: number | null;
  created_at: string | null;
}

interface WhoopSleep {
  id: number | null;
  start: string | null;
  end: string | null;
  total_in_bed_time_milli: number | null;
  total_awake_time_milli: number | null;
  total_light_sleep_time_milli: number | null;
  total_slow_wave_sleep_time_milli: number | null;
  total_rem_sleep_time_milli: number | null;
  sleep_performance_percentage: number | null;
  sleep_consistency_percentage: number | null;
  sleep_efficiency_percentage: number | null;
  respiratory_rate: number | null;
}

interface WhoopStrain {
  id: number | null;
  start: string | null;
  end: string | null;
  score: number | null;
  kilojoule: number | null;
  average_heart_rate: number | null;
  max_heart_rate: number | null;
}

interface WhoopDashboard {
  connected: boolean;
  recovery: WhoopRecovery | null;
  sleep: WhoopSleep | null;
  strain: WhoopStrain | null;
  user_first_name: string | null;
}

interface WhoopHRVPoint {
  date: string;
  hrv_rmssd_milli: number | null;
}

interface WhoopWorkout {
  id: number | null;
  sport_id: number | null;
  sport_name: string | null;
  start: string | null;
  end: string | null;
  strain: number | null;
  average_heart_rate: number | null;
  max_heart_rate: number | null;
  kilojoule: number | null;
}

// ── helpers ──────────────────────────────────────────────────────────────────

function millisToHM(ms: number | null): string {
  if (ms == null) return '—';
  const h = Math.floor(ms / 3_600_000);
  const m = Math.floor((ms % 3_600_000) / 60_000);
  return `${h}h ${m}m`;
}

function pct(v: number | null): string {
  return v != null ? `${Math.round(v)}%` : '—';
}

function fmt1(v: number | null): string {
  return v != null ? v.toFixed(1) : '—';
}

function fmtDate(iso: string | null): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString('en-GB', { month: 'short', day: 'numeric' });
}

function recoveryColor(score: number | null): string {
  if (score == null) return 'var(--text-muted)';
  if (score >= 67) return 'var(--status-ok)';
  if (score >= 34) return 'var(--status-warn)';
  return 'var(--status-danger)';
}

function recoveryPillClass(score: number | null) {
  if (score == null) return '';
  if (score >= 67) return styles.pillGreen;
  if (score >= 34) return styles.pillYellow;
  return styles.pillRed;
}

function recoveryLabel(score: number | null): string {
  if (score == null) return 'No data';
  if (score >= 67) return 'Optimal';
  if (score >= 34) return 'Moderate';
  return 'Low';
}

// ── Recovery ring ─────────────────────────────────────────────────────────────

const RING_R = 50;
const RING_CIRC = 2 * Math.PI * RING_R;

function RecoveryRing({ score }: { score: number | null }) {
  const pctVal = score != null ? Math.min(score, 100) / 100 : 0;
  const dash = pctVal * RING_CIRC;
  const color = recoveryColor(score);

  return (
    <div className={styles.ringWrap}>
      <svg className={styles.ring} viewBox="0 0 120 120">
        <circle className={styles.ringBg} cx="60" cy="60" r={RING_R} />
        <circle
          className={styles.ringFill}
          cx="60"
          cy="60"
          r={RING_R}
          stroke={color}
          strokeDasharray={RING_CIRC}
          strokeDashoffset={RING_CIRC - dash}
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

// ── HRV Sparkline ─────────────────────────────────────────────────────────────

function HRVSparkline({ points }: { points: WhoopHRVPoint[] }) {
  if (!points.length) return <p className={styles.empty}>No HRV data</p>;

  const values = points.map((p) => p.hrv_rmssd_milli ?? 0);
  const maxVal = Math.max(...values, 1);

  return (
    <>
      <div className={styles.sparkline}>
        {values.map((v, i) => (
          <div
            key={i}
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

// ── Main component ────────────────────────────────────────────────────────────

export default function HealthFitness() {
  const {
    data: dashboard,
    isLoading,
    error,
  } = useFetch<WhoopDashboard>('/api/v1/whoop/dashboard', 120_000);

  const { data: hrvPoints } = useFetch<WhoopHRVPoint[]>('/api/v1/whoop/hrv-trend');
  const { data: workouts } = useFetch<WhoopWorkout[]>('/api/v1/whoop/workouts');

  if (isLoading) {
    return (
      <div className={styles.page}>
        <p className={styles.loading}>Loading health data…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className={styles.page}>
        <p className={styles.error}>Failed to load health data. Check backend logs.</p>
      </div>
    );
  }

  // Not connected
  if (!dashboard?.connected) {
    return (
      <div className={styles.page}>
        <div className={styles.header}>
          <h1 className={styles.title}>Health</h1>
        </div>
        <div className={styles.connectPanel}>
          <div className={styles.connectIcon}>⚡</div>
          <h2 className={styles.connectTitle}>Connect your Whoop</h2>
          <p className={styles.connectDesc}>
            Link your Whoop band to see recovery scores, sleep analysis, HRV trends, and
            workouts all in one place.
          </p>
          <a href="/integrations" className={styles.connectBtn}>
            Connect Whoop
          </a>
        </div>
      </div>
    );
  }

  const { recovery, sleep, strain, user_first_name } = dashboard;

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <h1 className={styles.title}>Health</h1>
        {user_first_name && (
          <p className={styles.subtitle}>{user_first_name}'s Whoop data</p>
        )}
      </div>

      <div className={styles.grid}>
        {/* Recovery */}
        <div className={styles.card}>
          <p className={styles.cardTitle}>Recovery</p>
          <div className={styles.recoveryCard}>
            <RecoveryRing score={recovery?.recovery_score ?? null} />

            {recovery?.recovery_score != null && (
              <span
                className={`${styles.pill} ${recoveryPillClass(recovery.recovery_score)}`}
              >
                {recoveryLabel(recovery.recovery_score)}
              </span>
            )}

            <div className={styles.recoveryMeta}>
              <div className={styles.metaStat}>
                <div className={styles.metaVal}>
                  {recovery?.hrv_rmssd_milli != null
                    ? `${recovery.hrv_rmssd_milli.toFixed(0)} ms`
                    : '—'}
                </div>
                <div className={styles.metaKey}>HRV</div>
              </div>
              <div className={styles.metaStat}>
                <div className={styles.metaVal}>
                  {recovery?.resting_heart_rate != null
                    ? `${recovery.resting_heart_rate} bpm`
                    : '—'}
                </div>
                <div className={styles.metaKey}>Resting HR</div>
              </div>
              {recovery?.spo2_percentage != null && (
                <div className={styles.metaStat}>
                  <div className={styles.metaVal}>{pct(recovery.spo2_percentage)}</div>
                  <div className={styles.metaKey}>SpO₂</div>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Sleep */}
        <div className={styles.card}>
          <p className={styles.cardTitle}>Last Sleep</p>
          {sleep ? (
            <>
              <div className={styles.sleepRow}>
                <span className={styles.sleepKey}>Performance</span>
                <span className={styles.sleepVal}>
                  {pct(sleep.sleep_performance_percentage)}
                </span>
              </div>
              <div className={styles.sleepRow}>
                <span className={styles.sleepKey}>Efficiency</span>
                <span className={styles.sleepVal}>
                  {pct(sleep.sleep_efficiency_percentage)}
                </span>
              </div>
              <div className={styles.sleepRow}>
                <span className={styles.sleepKey}>REM</span>
                <span className={styles.sleepVal}>
                  {millisToHM(sleep.total_rem_sleep_time_milli)}
                </span>
              </div>
              <div className={styles.sleepRow}>
                <span className={styles.sleepKey}>Deep</span>
                <span className={styles.sleepVal}>
                  {millisToHM(sleep.total_slow_wave_sleep_time_milli)}
                </span>
              </div>
              <div className={styles.sleepRow}>
                <span className={styles.sleepKey}>Light</span>
                <span className={styles.sleepVal}>
                  {millisToHM(sleep.total_light_sleep_time_milli)}
                </span>
              </div>
              {sleep.respiratory_rate != null && (
                <div className={styles.sleepRow}>
                  <span className={styles.sleepKey}>Resp. Rate</span>
                  <span className={styles.sleepVal}>
                    {fmt1(sleep.respiratory_rate)} rpm
                  </span>
                </div>
              )}
            </>
          ) : (
            <p className={styles.empty}>No sleep data</p>
          )}
        </div>

        {/* Strain */}
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
                    : '—'}
                </div>
                <div className={styles.metaKey}>Avg HR</div>
              </div>
              <div className={styles.metaStat}>
                <div className={styles.metaVal}>
                  {strain.max_heart_rate != null ? `${strain.max_heart_rate} bpm` : '—'}
                </div>
                <div className={styles.metaKey}>Max HR</div>
              </div>
              <div className={styles.metaStat}>
                <div className={styles.metaVal}>
                  {strain.kilojoule != null
                    ? `${Math.round(strain.kilojoule / 4.184)} kcal`
                    : '—'}
                </div>
                <div className={styles.metaKey}>Calories</div>
              </div>
            </div>
          ) : (
            <p className={styles.empty}>No strain data</p>
          )}
        </div>

        {/* HRV Trend */}
        <div className={styles.card}>
          <p className={styles.cardTitle}>HRV Trend (14 days)</p>
          <HRVSparkline points={hrvPoints ?? []} />
        </div>

        {/* Workouts */}
        <div className={styles.card} style={{ gridColumn: '1 / -1' }}>
          <p className={styles.cardTitle}>Recent Workouts</p>
          {workouts && workouts.length > 0 ? (
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
      </div>
    </div>
  );
}
