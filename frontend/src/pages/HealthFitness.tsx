import AppleHealthCard from '../components/AppleHealthCard';
import {
  HRVTrendCard,
  RecoveryCard,
  SleepCard,
  StrainCard,
  WhoopNoticePanel,
  WorkoutsCard,
} from '../components/health';
import { useWhoopDashboard } from '../hooks/useWhoopDashboard';
import styles from './HealthFitness.module.css';

/**
 * Health & Fitness dashboard.
 *
 * Composition only: data comes from useWhoopDashboard and useAppleHealth
 * (inside AppleHealthCard), and every tile owns its own rendering and
 * empty state. Formatting lives in utils/healthFormat.
 *
 * The two sources behave differently on purpose. Whoop is pulled live from
 * its API on each request. Apple Health has no cloud API, so AppleHealthCard
 * reads whatever the user's iOS Shortcut last pushed. Neither persists
 * biometric values.
 */

// Matches the backend default for /api/v1/whoop/hrv-trend.
const HRV_TREND_DAYS = 14;

function PageHeader({ subtitle }: { subtitle?: string | null }) {
  return (
    <div className={styles.header}>
      <h1 className={styles.title}>Health</h1>
      {subtitle && <p className={styles.subtitle}>{subtitle}</p>}
    </div>
  );
}

export default function HealthFitness() {
  const { dashboard, hrvPoints, workouts, isLoading, error } = useWhoopDashboard();

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

  // Apple Health is rendered in every branch below: it is an independent
  // source, so a missing or expired Whoop connection must not hide it.

  if (!dashboard?.connected) {
    return (
      <div className={styles.page}>
        <PageHeader />
        <WhoopNoticePanel
          icon="⚡"
          title="Connect your Whoop"
          description="Link your Whoop band to see recovery scores, sleep analysis, HRV trends, and workouts all in one place."
          actionLabel="Connect Whoop"
          actionHref="/integrations"
        />
        <div className={styles.grid}>
          <AppleHealthCard />
        </div>
      </div>
    );
  }

  if (dashboard.needs_reauth) {
    return (
      <div className={styles.page}>
        <PageHeader />
        <WhoopNoticePanel
          icon="⚠️"
          title="Reconnect Whoop"
          description="Your Whoop session has expired. Reconnect your account to keep seeing recovery, sleep, and strain data."
          actionLabel="Reconnect Whoop"
          actionHref="/integrations#whoop"
        />
        <div className={styles.grid}>
          <AppleHealthCard />
        </div>
      </div>
    );
  }

  const { recovery, sleep, strain, user_first_name } = dashboard;

  return (
    <div className={styles.page}>
      <PageHeader
        subtitle={user_first_name ? `${user_first_name}'s Whoop & Apple Health data` : null}
      />

      <div className={styles.grid}>
        <RecoveryCard recovery={recovery} />
        <SleepCard sleep={sleep} />
        <StrainCard strain={strain} />
        <HRVTrendCard points={hrvPoints} days={HRV_TREND_DAYS} />
        <AppleHealthCard />
        <WorkoutsCard workouts={workouts} />
      </div>
    </div>
  );
}
