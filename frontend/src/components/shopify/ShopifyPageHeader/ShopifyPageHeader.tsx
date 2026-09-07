import { LiveBadge } from '../LiveBadge';
import styles from './ShopifyPageHeader.module.css';

export interface ShopifyPageHeaderProps {
  subtitle?: string | null;
  /** Show the pulsing Live pill — only true once real data is on screen. */
  live?: boolean;
}

/**
 * Title block shared by every state of the Shopify page, so the heading
 * never shifts position between loading, error, not-connected and content.
 */
export function ShopifyPageHeader({ subtitle, live = false }: ShopifyPageHeaderProps) {
  return (
    <div className={styles.header}>
      <div className={styles.headerText}>
        <h1 className={styles.title}>Shopify Store</h1>
        {subtitle && <p className={styles.subtitle}>{subtitle}</p>}
      </div>
      {live && <LiveBadge size="md" />}
    </div>
  );
}
