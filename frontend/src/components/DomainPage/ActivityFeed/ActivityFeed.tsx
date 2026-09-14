import { type DomainFeedItem } from '../../../data/mockData';
import { DomainSection } from '../DomainSection';
import styles from './ActivityFeed.module.css';

export interface ActivityFeedProps {
  feed: DomainFeedItem[];
}

/** Recent activity section: timestamped one-line events for the domain. */
export function ActivityFeed({ feed }: ActivityFeedProps) {
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
