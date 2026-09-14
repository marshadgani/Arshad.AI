import { type DomainKPI } from '../../../data/mockData';
import styles from './DomainHeader.module.css';

export interface DomainHeaderProps {
  slug: string;
  title: string;
  emoji: string;
  tagline: string;
  kpis: DomainKPI[];
}

/**
 * Identity block (emoji, kicker, title, tagline) plus the KPI tile row.
 * Takes the five fields it renders rather than a whole DomainConfig, so it
 * can head any page that has those, not only a fetched domain.
 */
export function DomainHeader({ slug, title, emoji, tagline, kpis }: DomainHeaderProps) {
  return (
    <header className={styles.header}>
      <div className={styles.headerEmoji}>{emoji}</div>
      <div className={styles.headerText}>
        <span className={styles.headerKicker}>// DOMAIN · {slug.toUpperCase()}</span>
        <h1 className={styles.headerTitle}>{title}</h1>
        <p className={styles.headerTagline}>{tagline}</p>
      </div>
      <div className={styles.kpis}>
        {kpis.map((k) => (
          <div key={k.label} className={styles.kpi}>
            <div className={styles.kpiLabel}>{k.label}</div>
            <div className={styles.kpiValue}>{k.value}</div>
            {k.delta && <div className={styles.kpiDelta}>{k.delta}</div>}
          </div>
        ))}
      </div>
    </header>
  );
}
