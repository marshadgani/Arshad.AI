import { type CommuteRes, type NewsRes } from '../useDashboardData';
import { CardHeader } from '../CardHeader';
import styles from '../Dashboard.module.css';

export interface CommuteNewsCardProps {
  commute: CommuteRes | null;
  news: NewsRes[] | null;
}

// Commute and news share one card because they share one visual treatment
// (the .wxRow label/value strip) — each arrives from its own endpoint and
// renders independently. Weather moved out to its own bold WeatherCard
// (FEAT-138) once it grew a live-vs-fallback state machine of its own.
export function CommuteNewsCard({ commute, news }: CommuteNewsCardProps) {
  return (
    <section className={styles.card}>
      <CardHeader title="Commute · news" meta="" />
      <div className={styles.wxRow}>
        <span className={styles.wxLabel}>Commute</span>
        <span className={styles.wxValue}>{commute ? `${commute.eta} · ${commute.dest}` : '—'}</span>
      </div>
      {(news ?? []).map((n) => (
        <div key={n.id} className={styles.wxRow}>
          <span className={styles.wxLabel}>{n.source}</span>
          <span className={styles.wxValue}>{n.title}</span>
        </div>
      ))}
    </section>
  );
}
