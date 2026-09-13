import type { ReactNode } from 'react';
import styles from './OntologyEmptyState.module.css';

export interface OntologyEmptyStateProps {
  icon?: string;
  title: string;
  description: string;
  action?: ReactNode;
}

/**
 * Shared "nothing here yet" framing for both the status panel (no sync has
 * ever run) and the entity list (filters matched nothing). Not an error —
 * distinct icon/copy/colour treatment from OntologyErrorPanel so the two
 * are never visually confusable.
 */
export function OntologyEmptyState({ icon = '⟡', title, description, action }: OntologyEmptyStateProps) {
  return (
    <div className={styles.empty}>
      <div className={styles.icon} aria-hidden="true">
        {icon}
      </div>
      <h3 className={styles.title}>{title}</h3>
      <p className={styles.description}>{description}</p>
      {action}
    </div>
  );
}
