import { CardSkeleton } from '../CardStatus';
import { type BriefingRes } from '../useDashboardData';
import styles from '../Dashboard.module.css';

export interface BriefingHeroProps {
  briefing: BriefingRes | null;
}

export function BriefingHero({ briefing }: BriefingHeroProps) {
  return (
    <section className={styles.hero}>
      <div className={styles.heroLabel}>// SYSTEM BRIEFING — REAL-TIME</div>
      {briefing ? (
        <>
          <h1 className={styles.heroGreeting}>{briefing.greeting}</h1>
          <div className={styles.heroDate}>{briefing.date}</div>
          <p className={styles.heroSummary}>{briefing.summary}</p>
        </>
      ) : (
        // The AI-generated briefing is the slowest of the dashboard's 13
        // endpoints (often several seconds) — rendering "Loading…" in the
        // exact same bold heading style as the real greeting reads as
        // broken/stuck content rather than a loading state, so this uses
        // the same shimmer every other widget uses instead.
        <div className={styles.heroSkeleton}>
          <CardSkeleton rows={3} />
        </div>
      )}
    </section>
  );
}
