import { type Application } from '../../data/mockData';
import styles from './DomainPage.module.css';
import DomainSection from './DomainSection';

export interface ApplicationsSectionProps {
  applications: Application[];
}

const statusClass: Record<Application['status'], string> = {
  live: styles.live,
  beta: styles.beta,
  planned: styles.planned,
};

// Read-only catalogue: there is no per-application route or data-model field
// to derive a destination from, so the cards carry no action affordance. Do
// not re-add an "Open" button until that destination exists (FEAT-148).
export default function ApplicationsSection({ applications }: ApplicationsSectionProps) {
  return (
    <DomainSection title="Applications" meta={`${applications.length} total`}>
      <div className={styles.appGrid}>
        {applications.map((app) => (
          <article key={app.id} className={styles.app}>
            <div className={styles.appName}>{app.name}</div>
            <div className={styles.appDesc}>{app.description}</div>
            <div className={styles.appFoot}>
              <span className={`${styles.statusTag} ${statusClass[app.status]}`}>{app.status}</span>
            </div>
          </article>
        ))}
      </div>
    </DomainSection>
  );
}
