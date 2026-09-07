import styles from './health.module.css';

export interface WhoopNoticePanelProps {
  icon: string;
  title: string;
  description: string;
  actionLabel: string;
  actionHref: string;
}

/**
 * Full-width call to action shown in place of the Whoop cards.
 *
 * Covers the two states where there is nothing to plot: never connected,
 * and connected but the token needs re-approval. They differ only in
 * wording and destination, so they share one component rather than two
 * near-identical panels.
 */
export default function WhoopNoticePanel({
  icon,
  title,
  description,
  actionLabel,
  actionHref,
}: WhoopNoticePanelProps) {
  return (
    <div className={styles.connectPanel}>
      <div className={styles.connectIcon} aria-hidden="true">
        {icon}
      </div>
      <h2 className={styles.connectTitle}>{title}</h2>
      <p className={styles.connectDesc}>{description}</p>
      <a href={actionHref} className={styles.connectBtn}>
        {actionLabel}
      </a>
    </div>
  );
}
