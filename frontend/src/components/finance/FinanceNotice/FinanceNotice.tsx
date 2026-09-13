import styles from './FinanceNotice.module.css';

export interface FinanceNoticeProps {
  icon: string;
  title: string;
  description: string;
  actionLabel: string;
  actionHref: string;
}

/**
 * A local, minimal notice panel for the finance/brokerage components.
 *
 * Deliberately not a relocation of ShopifyNoticePanel into a shared
 * components/common/NoticePanel: that move would touch ShopifyStore.tsx,
 * components/shopify/index.ts and Shopify's tests for zero functional gain
 * in this feature. Dedupe once a third consumer of this shape exists.
 */
export function FinanceNotice({
  icon,
  title,
  description,
  actionLabel,
  actionHref,
}: FinanceNoticeProps) {
  return (
    <div className={styles.panel}>
      <div className={styles.icon} aria-hidden="true">
        {icon}
      </div>
      <h3 className={styles.title}>{title}</h3>
      <p className={styles.description}>{description}</p>
      <a href={actionHref} className={styles.action}>
        {actionLabel}
      </a>
    </div>
  );
}
