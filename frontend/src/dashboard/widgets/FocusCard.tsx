import { CardSkeleton } from '../CardSkeleton';
import { type FocusRes } from '../useDashboardData';
import styles from '../Dashboard.module.css';

export interface FocusCardProps {
  focus: FocusRes | null;
}

// The backend only sends github.com links; checking again here means a
// regression there can never put a javascript: URL into an href.
function safeGithubUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const parsed = new URL(url);
    return parsed.protocol === 'https:' && parsed.hostname === 'github.com' ? parsed.href : null;
  } catch {
    return null;
  }
}

// Does not use CardHeader: the focus panel is a .focusBig surface whose
// title is a bare .cardTitle with no .cardHead row or meta slot.
export function FocusCard({ focus }: FocusCardProps) {
  const link = safeGithubUrl(focus?.url);
  return (
    <section className={styles.focusBig}>
      <div className={styles.cardTitle}><span className={styles.dot} />Focus now</div>
      {focus ? (
        <>
          <h2 className={styles.focusTitle}>{focus.title}</h2>
          <div className={styles.focusSubtitle}>{focus.subtitle}</div>
          <p className={styles.focusContext}>{focus.context}</p>
          <a
            className={styles.focusBtn}
            href={link ?? '/integrations'}
            {...(link ? { target: '_blank', rel: 'noopener noreferrer' } : {})}
          >
            {focus.action}
          </a>
        </>
      ) : (
        <div className={styles.cardSkeletonWrap}>
          <CardSkeleton rows={3} />
        </div>
      )}
    </section>
  );
}
