import styles from './ShopifyErrorPanel.module.css';

export interface ShopifyErrorPanelProps {
  message: string;
}

/** Full-page failure state, used only when there is no data to fall back on. */
export function ShopifyErrorPanel({ message }: ShopifyErrorPanelProps) {
  return (
    <div className={styles.panel} role="alert">
      <span className={styles.icon} aria-hidden="true">
        ⚠
      </span>
      <p>{message}</p>
    </div>
  );
}
