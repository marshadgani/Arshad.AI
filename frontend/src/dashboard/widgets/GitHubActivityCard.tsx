import { Link } from 'react-router-dom';

import { CardHeader } from '../CardHeader';
import { WidgetStatus } from '../WidgetStatus';
import styles from '../Dashboard.module.css';
import { type GitHubActivityRes } from '../useDashboardData';
import { GitHubActivityRow } from './GitHubActivityRow';

export interface GitHubActivityCardProps {
  items: GitHubActivityRes[] | null;
  isLoading?: boolean;
  error?: Error | null;
}

// Card-level concerns only: the header, the four-state contract, and the
// list. How a single item looks belongs to GitHubActivityRow.
export function GitHubActivityCard({
  items,
  isLoading = false,
  error = null,
}: GitHubActivityCardProps) {
  const rows = items ?? [];

  return (
    <section className={styles.card}>
      <CardHeader title="GitHub Activity" meta={`${rows.length} tracked`} />
      <WidgetStatus
        isLoading={isLoading}
        error={error}
        isEmpty={!isLoading && !error && rows.length === 0}
        emptyMessage={
          <>
            No GitHub activity synced yet. Ask in <Link to="/chat">Chat</Link> to sync a
            repo.
          </>
        }
      >
        <div className={styles.list}>
          {rows.map((item) => (
            <GitHubActivityRow key={item.id} item={item} />
          ))}
        </div>
      </WidgetStatus>
    </section>
  );
}
