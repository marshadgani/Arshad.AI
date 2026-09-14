import { type Application } from '../../../data/mockData';
import { DomainSection } from '../DomainSection';
import styles from './ApplicationList.module.css';

export interface ApplicationListProps {
  applications: Application[];
}

const statusClass: Record<Application['status'], string> = {
  live: styles.live,
  beta: styles.beta,
  planned: styles.planned,
};

/** Applications section: the app catalogue for one domain. */
export function ApplicationList({ applications }: ApplicationListProps) {
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
