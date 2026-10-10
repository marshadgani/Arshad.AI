import type { DaysCoverItem, InventoryCoverResponse, StockoutAlert } from '../../../types/shopify';
import { variantLabel } from '../../../utils/shopifyFormat';
import { ShopifyErrorPanel } from '../ShopifyErrorPanel';
import { ShopifyNoticePanel } from '../ShopifyNoticePanel';
import styles from './ShopifyInventoryCover.module.css';

export interface ShopifyInventoryCoverProps {
  data: InventoryCoverResponse | null;
  isLoading: boolean;
  error: Error | null;
  onRetry: () => void;
}

const SKELETON_ROWS = 4;
const DASH = '—';

function statusText(item: DaysCoverItem, alert: StockoutAlert | undefined): string {
  if (alert) return `Stockout ${alert.projected_stockout_date} during ${alert.travel_event_title}`;
  if (item.no_recent_sales) return 'No recent sales';
  if (item.days_of_cover === null) return 'Velocity unavailable';
  return 'OK';
}

function shopifyFailures(data: InventoryCoverResponse): string[] {
  return data.partial_failures.filter((f) => f !== 'calendar' && f !== 'calendar_truncated');
}

function Banner({ tone, children }: { tone: 'warn' | 'info'; children: string }) {
  return (
    <p className={tone === 'warn' ? styles.bannerWarn : styles.bannerInfo} role="status">
      {children}
    </p>
  );
}

function Caveats({ data, error }: { data: InventoryCoverResponse; error: Error | null }) {
  const failed = shopifyFailures(data);
  return (
    <>
      {error && (
        <Banner tone="warn">Could not refresh; showing the last loaded figures.</Banner>
      )}
      {data.variants_truncated && (
        <Banner tone="warn">Variant data incomplete; some variants are not shown.</Banner>
      )}
      {data.orders_truncated && (
        <Banner tone="warn">
          Velocity may be understated; the 30-day order sample is incomplete.
        </Banner>
      )}
      {failed.length > 0 && (
        <Banner tone="warn">
          Some Shopify data could not be loaded (rate limited or unavailable); figures are
          incomplete.
        </Banner>
      )}
      {!data.calendar_connected && (
        <Banner tone="info">Travel escalation unavailable (Calendar not connected).</Banner>
      )}
      {data.calendar_needs_reauth && (
        <Banner tone="info">
          Travel escalation unavailable (reconnect Google to read your Calendar).
        </Banner>
      )}
      {data.partial_failures.includes('calendar') && !data.calendar_needs_reauth && (
        <Banner tone="info">Travel escalation unavailable (Calendar could not be read).</Banner>
      )}
      {data.partial_failures.includes('calendar_truncated') && (
        <Banner tone="info">Only part of your Calendar was read; some trips may be missed.</Banner>
      )}
    </>
  );
}

export function ShopifyInventoryCover({ data, isLoading, error, onRetry }: ShopifyInventoryCoverProps) {
  if (isLoading && !data) {
    return (
      <section className={styles.card} aria-labelledby="inv-cover-title" aria-busy="true">
        <h2 id="inv-cover-title" className={styles.title}>Inventory cover</h2>
        <div role="status" className="sr-only">Loading inventory cover…</div>
        {Array.from({ length: SKELETON_ROWS }, (_, i) => (
          <div key={i} className={styles.skeletonBar} />
        ))}
      </section>
    );
  }

  if (error && !data) {
    return (
      <section className={styles.card} aria-labelledby="inv-cover-title">
        <h2 id="inv-cover-title" className={styles.title}>Inventory cover</h2>
        <ShopifyErrorPanel message="Failed to load inventory cover." />
        <button type="button" className={styles.retry} onClick={onRetry}>Retry</button>
      </section>
    );
  }

  if (!data) return null;

  if (!data.connected) {
    return (
      <section className={styles.card} aria-labelledby="inv-cover-title">
        <h2 id="inv-cover-title" className={styles.title}>Inventory cover</h2>
        <ShopifyNoticePanel
          icon="🛍️"
          title="Shopify not connected"
          description="Connect Shopify to see days-of-cover and stockout alerts."
          actionLabel="Manage integrations"
          actionHref="/integrations"
        />
      </section>
    );
  }

  if (data.needs_reauth) {
    return (
      <section className={styles.card} aria-labelledby="inv-cover-title">
        <h2 id="inv-cover-title" className={styles.title}>Inventory cover</h2>
        <ShopifyNoticePanel
          icon="🔗"
          title="Reconnect Shopify"
          description="Your Shopify session has expired. Reconnect to see inventory cover."
          actionLabel="Manage integrations"
          actionHref="/integrations"
        />
      </section>
    );
  }

  if (data.days_of_cover.length === 0) {
    const failed = shopifyFailures(data).length > 0;
    return (
      <section className={styles.card} aria-labelledby="inv-cover-title">
        <h2 id="inv-cover-title" className={styles.title}>Inventory cover</h2>
        <ShopifyNoticePanel
          icon={failed ? '⚠️' : '📦'}
          title={failed ? 'Inventory unavailable' : 'No tracked variants'}
          description={
            failed
              ? 'Shopify inventory could not be loaded right now. Try again shortly.'
              : 'No variants have inventory tracking enabled in Shopify.'
          }
          actionLabel="Manage Shopify"
          actionHref="/integrations"
        />
      </section>
    );
  }

  const alerts = new Map(data.alerts.map((a) => [a.variant_id, a]));

  return (
    <section className={styles.card} aria-labelledby="inv-cover-title">
      <h2 id="inv-cover-title" className={styles.title}>Inventory cover</h2>
      <Caveats data={data} error={error} />
      <table className={styles.table}>
        <thead>
          <tr>
            <th scope="col">Variant</th>
            <th scope="col" className={styles.num}>Available</th>
            <th scope="col" className={styles.num}>Units / day</th>
            <th scope="col" className={styles.num}>Days of cover</th>
            <th scope="col">Status</th>
          </tr>
        </thead>
        <tbody>
          {data.days_of_cover.map((item) => {
            const alert = alerts.get(item.variant_id);
            return (
              <tr key={item.variant_id} className={alert ? styles.alertRow : undefined}>
                <th scope="row" className={styles.variant}>{variantLabel(item.variant_id)}</th>
                <td className={styles.num}>{item.available_qty}</td>
                <td className={styles.num}>{item.velocity_30d ?? DASH}</td>
                <td className={styles.num}>{item.days_of_cover ?? DASH}</td>
                <td className={alert ? styles.badgeAlert : styles.badge}>
                  {statusText(item, alert)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}
