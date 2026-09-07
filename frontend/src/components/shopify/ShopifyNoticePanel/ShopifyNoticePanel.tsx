import styles from './ShopifyNoticePanel.module.css';

export interface ShopifyNoticePanelProps {
  icon: string;
  title: string;
  description: string;
  actionLabel: string;
  actionHref: string;
}

export function ShopifyNoticePanel({
  icon,
  title,
  description,
  actionLabel,
  actionHref,
}: ShopifyNoticePanelProps) {
  return (
    <div className={styles.panel}>
      <div className={styles.icon} aria-hidden="true">
        {icon}
      </div>
      <h2 className={styles.title}>{title}</h2>
      <p className={styles.description}>{description}</p>
      <a href={actionHref} className={styles.action}>
        {actionLabel}
      </a>
    </div>
  );
}
