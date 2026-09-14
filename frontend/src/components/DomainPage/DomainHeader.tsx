import { type DomainConfig } from '../../data/mockData';
import styles from './DomainPage.module.css';

export interface DomainHeaderProps {
  domain: DomainConfig;
}

export default function DomainHeader({ domain }: DomainHeaderProps) {
  return (
    <header className={styles.header}>
      <div className={styles.headerEmoji}>{domain.emoji}</div>
      <div className={styles.headerText}>
        <span className={styles.headerKicker}>// DOMAIN · {domain.slug.toUpperCase()}</span>
        <h1 className={styles.headerTitle}>{domain.title}</h1>
        <p className={styles.headerTagline}>{domain.tagline}</p>
      </div>
      <div className={styles.kpis}>
        {domain.kpis.map((kpi) => (
          <div key={kpi.label} className={styles.kpi}>
            <div className={styles.kpiLabel}>{kpi.label}</div>
            <div className={styles.kpiValue}>{kpi.value}</div>
            {kpi.delta && <div className={styles.kpiDelta}>{kpi.delta}</div>}
          </div>
        ))}
      </div>
    </header>
  );
}
