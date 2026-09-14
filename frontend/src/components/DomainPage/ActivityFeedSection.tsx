import { type DomainConfig } from '../../data/mockData';
import styles from './DomainPage.module.css';
import DomainSection from './DomainSection';

export interface ActivityFeedSectionProps {
  feed: DomainConfig['feed'];
}

export default function ActivityFeedSection({ feed }: ActivityFeedSectionProps) {
  return (
    <DomainSection title="Recent activity" meta="last 24 h">
      <div className={styles.feed}>
        {feed.map((row) => (
          <div key={row.id} className={styles.feedRow}>
            <span className={styles.feedTime}>{row.time}</span>
            <span className={styles.feedMsg}>{row.message}</span>
          </div>
        ))}
      </div>
    </DomainSection>
  );
}
