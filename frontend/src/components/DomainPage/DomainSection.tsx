import { type ReactNode } from 'react';

import styles from './DomainPage.module.css';

export interface DomainSectionProps {
  title: string;
  /** Right-aligned counter/caption, e.g. "4 total" or "last 24 h". */
  meta: string;
  children: ReactNode;
}

// Panel chrome shared by the Applications, Agents and Activity sections —
// owned here so a change to it cannot land in two of the three and fork.
export default function DomainSection({ title, meta, children }: DomainSectionProps) {
  return (
    <section className={styles.section}>
      <div className={styles.sectionHead}>
        <div className={styles.sectionTitle}>{title}</div>
        <div className={styles.sectionMeta}>{meta}</div>
      </div>
      {children}
    </section>
  );
}
