import { NavLink } from 'react-router-dom';

import { useFetch } from '../../hooks/useFetch';
import { formatRelativeTime } from '../../utils/relativeTime';
import styles from './ActivityLog.module.css';

// Shape of GET /api/v1/chat/sessions — the real, already-shipped session
// list backing the chat sidebar's history. Activity Log reuses it rather
// than a bespoke audit-log endpoint that doesn't exist yet, so the page
// has genuine content on day one instead of being a dead end.
export interface ChatSessionActivity {
  id: string;
  title: string | null;
  created_at: string | null;
  updated_at: string | null;
}

const SKELETON_ROW_COUNT = 5;

export default function ActivityLog() {
  const { data, isLoading, error, refetch } = useFetch<ChatSessionActivity[]>(
    '/api/v1/chat/sessions',
  );
  const sessions = data ?? [];

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <h1 className={styles.title}>Activity Log</h1>
          <p className={styles.sub}>Every chat session with Arshad.AI, most recent first.</p>
        </div>
        <button
          type="button"
          className={styles.refresh}
          onClick={refetch}
          disabled={isLoading}
          aria-busy={isLoading}
        >
          {isLoading ? 'Refreshing…' : 'Refresh'}
        </button>
      </header>

      {error && (
        <div className={styles.banner} role="alert">
          <span>Failed to load activity: {error.message}</span>
          <button type="button" className={styles.bannerRetry} onClick={refetch}>
            Retry
          </button>
        </div>
      )}

      {isLoading && sessions.length === 0 && !error && (
        <ol className={styles.list} aria-hidden="true">
          {Array.from({ length: SKELETON_ROW_COUNT }).map((_, i) => (
            <li key={i} className={styles.skeletonEntry}>
              <span className={styles.skeletonDot} />
              <div className={styles.skeletonBody}>
                <div className={styles.skeletonBar} />
                <div className={styles.skeletonBarShort} />
              </div>
            </li>
          ))}
        </ol>
      )}

      {!isLoading && !error && sessions.length === 0 && (
        <div className={styles.empty} role="status">
          <p>No activity yet.</p>
          <NavLink to="/chat" className={styles.emptyCta}>
            Start a conversation →
          </NavLink>
        </div>
      )}

      {sessions.length > 0 && (
        <ol className={styles.list}>
          {sessions.map((s) => (
            <li key={s.id} className={styles.entry}>
              <NavLink to={`/chat/${s.id}`} className={styles.entryLink}>
                <span className={styles.dot} aria-hidden="true" />
                <div className={styles.entryBody}>
                  <span className={styles.entryTitle}>{s.title || 'Untitled session'}</span>
                  <span className={styles.entryMeta}>
                    Started {formatRelativeTime(s.created_at)}
                    {s.updated_at && s.updated_at !== s.created_at && (
                      <> · Updated {formatRelativeTime(s.updated_at)}</>
                    )}
                  </span>
                </div>
              </NavLink>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
