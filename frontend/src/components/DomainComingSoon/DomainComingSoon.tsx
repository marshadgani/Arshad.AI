import { useId } from 'react';
import styles from './DomainComingSoon.module.css';

/** Display-only content for a domain that is on the roadmap but has no
 *  integration behind it yet. `readonly` because the entries come from a
 *  shared map (`data/comingSoonDomains.ts`) spread into props. */
export type DomainComingSoonProps = {
  readonly emoji: string;
  readonly title: string;
  readonly reason: string;
};

export default function DomainComingSoon({ emoji, title, reason }: DomainComingSoonProps) {
  // A fixed id would duplicate whenever two instances are mounted, making every
  // aria-labelledby resolve to the first h1 and mislabel the landmark.
  const titleId = useId();

  return (
    <section className={styles.panel} aria-labelledby={titleId}>
      <span className={styles.emojiWrap}>
        <span className={styles.emojiRing} aria-hidden="true" />
        <span className={styles.emoji} aria-hidden="true">{emoji}</span>
      </span>
      {/* Decoration (the "//" prefix, the pulsing dot) is aria-hidden; "Coming
          soon" stays in the accessible text — it is the only status marker a
          screen-reader user gets. */}
      <span className={styles.kicker}>
        <span className={styles.kickerDot} aria-hidden="true" />
        Coming soon
      </span>
      <h1 id={titleId} className={styles.title}>{title}</h1>
      <p className={styles.reason}>{reason}</p>
    </section>
  );
}
