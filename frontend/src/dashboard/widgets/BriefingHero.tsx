import { type BriefingRes } from '../useDashboardData';
import styles from '../Dashboard.module.css';

export interface BriefingHeroProps {
  briefing: BriefingRes | null;
}

export function BriefingHero({ briefing }: BriefingHeroProps) {
  return (
    <section className={styles.hero}>
      <div className={styles.heroLabel}>// SYSTEM BRIEFING — REAL-TIME</div>
      <h1 className={styles.heroGreeting}>{briefing?.greeting ?? 'Loading…'}</h1>
      <div className={styles.heroDate}>{briefing?.date ?? ''}</div>
      <p className={styles.heroSummary}>{briefing?.summary ?? ''}</p>
    </section>
  );
}
