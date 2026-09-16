import StatusChip from '../StatusChip';

import styles from './ComingSoonPage.module.css';

export interface ComingSoonPageProps {
  title: string;
  emoji: string;
  reason: string;
}

// Pure presentation. No fetch, no state, no effects — this page has nothing
// real to load yet, so it never pretends otherwise.
export default function ComingSoonPage({ title, emoji, reason }: ComingSoonPageProps) {
  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div className={styles.emoji} aria-hidden="true">
          {emoji}
        </div>
        <div className={styles.text}>
          <h1 className={styles.title}>{title}</h1>
          <StatusChip label="Coming soon" />
        </div>
      </header>
      <p className={styles.reason}>{reason}</p>
    </div>
  );
}
