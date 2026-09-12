import { LiveBadge } from '../LiveBadge';
import { formatMoney, formatRelativeTime } from '../../../utils/shopifyFormat';
import type { ShopifyOrder } from '../../../types/shopify';
import styles from './RecentOrdersCard.module.css';

export interface RecentOrdersCardProps {
  orders: ShopifyOrder[];
  isLoading: boolean;
  error?: string | null;
}

const SKELETON_ROWS = 4;

export function RecentOrdersCard({ orders, isLoading, error }: RecentOrdersCardProps) {
  return (
    <div className={styles.card}>
      <div className={styles.head}>
        <h3 className={styles.title}>Recent Orders</h3>
        {!isLoading && !error && orders.length > 0 && <LiveBadge size="sm" />}
      </div>

      {isLoading && (
        <ul className={styles.list} aria-hidden="true">
          {Array.from({ length: SKELETON_ROWS }).map((_, i) => (
            <li key={i} className={styles.skeletonRow}>
              <span className={styles.skeletonBar} style={{ width: '35%' }} />
              <span className={styles.skeletonBar} style={{ width: '20%' }} />
            </li>
          ))}
        </ul>
      )}

      {!isLoading && error && (
        <div className={styles.errorState} role="alert">
          <span aria-hidden="true">⚠</span>
          Unable to load recent orders
        </div>
      )}

      {!isLoading && !error && orders.length === 0 && (
        <div className={styles.emptyState}>
          <span className={styles.emptyIcon} aria-hidden="true">
            🧾
          </span>
          <p className={styles.muted}>No orders yet today</p>
        </div>
      )}

      {!isLoading && !error && orders.length > 0 && (
        <ul className={styles.list}>
          {orders.map((order, i) => (
            <li
              key={order.id}
              className={styles.row}
              style={{ animationDelay: `${Math.min(i, 8) * 35}ms` }}
            >
              <div className={styles.orderInfo}>
                <span className={styles.orderNumber}>{order.order_number}</span>
                <span className={styles.customer}>{order.customer_name ?? 'Guest'}</span>
              </div>
              <div className={styles.orderMeta}>
                <span className={styles.items}>
                  {order.item_count} item{order.item_count === 1 ? '' : 's'}
                </span>
                <span className={styles.amount}>
                  {formatMoney(order.total_amount, order.currency_code)}
                </span>
                <time className={styles.time} dateTime={order.created_at}>
                  {formatRelativeTime(order.created_at)}
                </time>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
