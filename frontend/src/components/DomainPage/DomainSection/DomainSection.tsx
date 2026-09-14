import { type ReactNode } from 'react';

import styles from './DomainSection.module.css';

export interface DomainSectionProps {
  title: string;
  /** Right-aligned caption in the section head, e.g. "4 total". */
  meta: string;
  children: ReactNode;
}

/**
 * Panel chrome shared by every section of a domain page. Owning the
 * head/title/meta markup in one place is what lets Applications, Agents and
 * Recent activity stay visually identical when one of them changes.
 */
export function DomainSection({ title, meta, children }: DomainSectionProps) {
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
