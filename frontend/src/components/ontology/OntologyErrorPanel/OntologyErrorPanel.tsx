import styles from './OntologyErrorPanel.module.css';

export interface OntologyErrorPanelProps {
  message: string;
}

/** Full-panel failure state, used only when there is no cached data to fall back on. */
export function OntologyErrorPanel({ message }: OntologyErrorPanelProps) {
  return (
    <div className={styles.panel} role="alert">
      <span className={styles.icon} aria-hidden="true">
        ⚠
      </span>
      <p>{message}</p>
    </div>
  );
}
