import { type CommuteRes, type NewsRes, type WeatherRes } from '../useDashboardData';
import { CardHeader } from '../CardHeader';
import styles from '../Dashboard.module.css';

export interface WeatherCommuteNewsCardProps {
  weather: WeatherRes | null;
  commute: CommuteRes | null;
  news: NewsRes[] | null;
}

// Three ambient feeds share one card because they share one visual
// treatment (the .wxRow label/value strip), not because they share a
// source — each arrives from its own endpoint and renders independently.
export function WeatherCommuteNewsCard({ weather, commute, news }: WeatherCommuteNewsCardProps) {
  return (
    <section className={styles.card}>
      <CardHeader title="Weather · commute · news" meta={weather?.city ?? ''} />
      <div className={styles.wxBig}>
        <div className={styles.wxTemp}>{weather?.temp ?? '—'}</div>
        <div className={styles.wxDetail}>{weather?.condition ?? ''}</div>
      </div>
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
