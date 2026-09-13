import { formatRelativeTime } from '../../utils/time';
import styles from '../Dashboard.module.css';
import { type GitHubActivityRes } from '../useDashboardData';

// Split from GitHubActivityCard at the item boundary so the meta-line rules
// below — the only real branching in this widget — are testable without
// rendering React.

// merged is the success outcome (ok/green); an unmerged closed PR/issue is
// a neutral-negative terminal state (warn/amber); open is in-flight
// (info/blue). sevCritical is reserved for genuine alerts and unused here.
const stateClass: Record<GitHubActivityRes['state'], string> = {
  open: styles.sevInfo,
  merged: styles.sevOk,
  closed: styles.sevWarn,
};

/**
 * The subtitle under an activity title, e.g.
 * `owner/repo #42 · PR · merged · draft · arshad`.
 *
 * The state word is always present so the coloured pin is never the sole
 * carrier of meaning (WCAG 1.4.1). Absent parts are dropped rather than
 * rendered blank, so a null author leaves no dangling separator.
 */
export function activityMetaLine(item: GitHubActivityRes): string {
  return [
    item.number !== null ? `${item.repository} #${item.number}` : item.repository,
    item.kind === 'pr' ? 'PR' : 'Issue',
    item.state,
    item.isDraft ? 'draft' : null,
    item.author,
  ]
    .filter(Boolean)
    .join(' · ');
}

export interface GitHubActivityRowProps {
  item: GitHubActivityRes;
}

export function GitHubActivityRow({ item }: GitHubActivityRowProps) {
  return (
    <div className={styles.notif}>
      <span className={`${styles.notifPin} ${stateClass[item.state]}`} />
      <div className={styles.notifBody}>
        {item.url ? (
          <a
            className={styles.notifTitle}
            href={item.url}
            target="_blank"
            rel="noreferrer"
          >
            {item.title}
          </a>
        ) : (
          <span className={styles.notifTitle}>{item.title}</span>
        )}
        <span className={styles.notifDetail}>{activityMetaLine(item)}</span>
      </div>
      <span className={styles.notifTime}>{formatRelativeTime(item.updatedAt)}</span>
    </div>
  );
}
