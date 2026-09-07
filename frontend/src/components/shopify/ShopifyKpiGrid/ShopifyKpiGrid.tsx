import { KpiCard } from '../KpiCard';
import type { KpiCardProps } from '../KpiCard';
import { RecentOrdersCard } from '../RecentOrdersCard';
import { formatMoney } from '../../../utils/shopifyFormat';
import type { ShopifyDashboard } from '../../../types/shopify';
import styles from './ShopifyKpiGrid.module.css';

export interface ShopifyKpiGridProps {
  dashboard: ShopifyDashboard;
}

/**
 * A KPI is `unavailable` when the backend told us it could not be computed,
 * `empty` when it simply has no value, and `ok` otherwise.
 */
function kpiState(
  unavailable: boolean,
  value: string | number | null | undefined,
): KpiCardProps['state'] {
  if (unavailable) return 'unavailable';
  return value != null ? 'ok' : 'empty';
}

/**
 * The dashboard body: four KPI tiles plus the recent-orders feed.
 *
 * Owns the mapping from wire fields to card props — which value is
 * missing, which is plan-gated, which needs a caveat — so the page above
 * stays a pure state router and this file is the only place that has to
 * change when a KPI's semantics change.
 */
export function ShopifyKpiGrid({ dashboard }: ShopifyKpiGridProps) {
  const {
    revenue_amount,
    truncated,
    order_count,
    order_count_approximate,
    conversion_rate_status,
    average_order_value,
    low_stock_sku_count,
    recent_orders,
    currency_code,
    partial_failures,
  } = dashboard;

  return (
    <div className={styles.grid}>
      <KpiCard
        icon="💰"
        label="Today's Revenue"
        value={truncated ? null : formatMoney(revenue_amount, currency_code)}
        // A full first page means the day's total cannot be summed from it,
        // so we say so rather than showing a confident under-count.
        hint={truncated ? 'More than 250 orders today — revenue unavailable' : null}
        state={kpiState(Boolean(truncated), revenue_amount)}
      />
      <KpiCard
        icon="📦"
        label="Orders Today"
        value={order_count ?? '—'}
        hint={order_count_approximate ? '(approximate)' : null}
        state={kpiState(false, order_count)}
      />
      <KpiCard
        icon="🎯"
        label="Conversion Rate"
        value={average_order_value ? formatMoney(average_order_value, currency_code) : null}
        hint={
          average_order_value
            ? 'Average order value (conversion rate unavailable on this plan)'
            : null
        }
        state={conversion_rate_status === 'unavailable' ? 'unavailable' : 'ok'}
        docsHref="https://help.shopify.com/en/manual/reports-and-analytics"
      />
      <KpiCard
        icon="⚠️"
        label="Low Stock SKUs"
        value={low_stock_sku_count ?? '—'}
        state={kpiState(false, low_stock_sku_count)}
      />
      <RecentOrdersCard
        orders={recent_orders}
        isLoading={false}
        error={partial_failures.length > 0 ? 'Partial data' : null}
      />
    </div>
  );
}

const SKELETON_KPI_LABELS = [
  "Today's Revenue",
  'Orders Today',
  'Conversion Rate',
  'Low Stock SKUs',
];

/**
 * First-paint placeholder. Lives beside the real grid so the two can never
 * drift into different shapes — a skeleton that does not match the content
 * it stands in for causes exactly the layout shift it exists to prevent.
 */
export function ShopifyKpiGridSkeleton() {
  return (
    <div className={styles.grid} aria-busy="true" aria-label="Loading Shopify data">
      {SKELETON_KPI_LABELS.map((label) => (
        <KpiCard key={label} label={label} value={null} state="loading" />
      ))}
      <RecentOrdersCard orders={[]} isLoading />
    </div>
  );
}
