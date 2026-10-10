import type { MatchConfidence, ServiceDebtResponse } from '../../../types/shopify';
import { ShopifyErrorPanel } from '../ShopifyErrorPanel';
import { ShopifyNoticePanel } from '../ShopifyNoticePanel';
import styles from './ShopifyServiceDebt.module.css';

export interface ShopifyServiceDebtProps {
  data: ServiceDebtResponse | null;
  isLoading: boolean;
  error: Error | null;
  onRetry: () => void;
}

const SKELETON_ROWS = 4;
const AGE_LABEL = 'Older than 24h';

function confidenceLabel(confidence: MatchConfidence | null): string {
  return confidence === null ? 'No match' : `${confidence === 'high' ? 'High' : 'Low'} confidence`;
}

function Banner({ tone, children }: { tone: 'warn' | 'info'; children: string }) {
  return (
    <p className={tone === 'warn' ? styles.bannerWarn : styles.bannerInfo} role="status">
      {children}
    </p>
  );
}

export function ShopifyServiceDebt({ data, isLoading, error, onRetry }: ShopifyServiceDebtProps) {
  if (isLoading && !data) {
    return (
      <section className={styles.card} aria-labelledby="svc-debt-title" aria-busy="true">
        <h2 id="svc-debt-title" className={styles.title}>Customer service debt</h2>
        <div role="status" className="sr-only">Loading customer service debt…</div>
        {Array.from({ length: SKELETON_ROWS }, (_, i) => (
          <div key={i} className={styles.skeletonBar} />
        ))}
      </section>
    );
  }

  if (error && !data) {
    return (
      <section className={styles.card} aria-labelledby="svc-debt-title">
        <h2 id="svc-debt-title" className={styles.title}>Customer service debt</h2>
        <ShopifyErrorPanel message="Failed to load customer service debt." />
        <button type="button" className={styles.retry} onClick={onRetry}>Retry</button>
      </section>
    );
  }

  if (!data) return null;

  const gmailReauth = data.partial_failures.includes('gmail') && data.needs_reauth;
  const gmailFailed = data.partial_failures.includes('gmail') && !data.needs_reauth;

  if (!data.gmail_connected || gmailReauth || gmailFailed) {
    const title = !data.gmail_connected
      ? 'Gmail not connected'
      : gmailReauth
        ? 'Reconnect Google'
        : 'Gmail unavailable';
    const description = !data.gmail_connected
      ? 'Connect Gmail to see customer emails that have waited more than 24 hours.'
      : gmailReauth
        ? 'Your Google session has expired. Reconnect to read your inbox.'
        : 'Gmail could not be read right now. Try again shortly.';
    return (
      <section className={styles.card} aria-labelledby="svc-debt-title">
        <h2 id="svc-debt-title" className={styles.title}>Customer service debt</h2>
        <ShopifyNoticePanel
          icon="✉️"
          title={title}
          description={description}
          actionLabel="Manage integrations"
          actionHref="/integrations"
        />
      </section>
    );
  }

  if (data.threads.length === 0) {
    return (
      <section className={styles.card} aria-labelledby="svc-debt-title">
        <h2 id="svc-debt-title" className={styles.title}>Customer service debt</h2>
        <ShopifyNoticePanel
          icon="✅"
          title="No old unanswered threads"
          description="No inbox threads older than 24 hours are waiting on a reply."
          actionLabel="Open integrations"
          actionHref="/integrations"
        />
      </section>
    );
  }

  const ordersFailed = data.partial_failures.some((f) => f === 'orders' || f === 'throttled');
  const shopifyReauth = data.partial_failures.includes('shopify');

  return (
    <section className={styles.card} aria-labelledby="svc-debt-title">
      <h2 id="svc-debt-title" className={styles.title}>Customer service debt</h2>
      {data.threads_truncated && (
        <Banner tone="warn">
          Showing the 100 most recent matching threads; older threads are not shown.
        </Banner>
      )}
      {!data.shopify_connected && (
        <Banner tone="info">Order context unavailable (Shopify not connected).</Banner>
      )}
      {shopifyReauth && (
        <Banner tone="info">Order context unavailable (reconnect Shopify).</Banner>
      )}
      {ordersFailed && (
        <Banner tone="warn">Order context could not be loaded; matches are missing.</Banner>
      )}
      {data.orders_truncated && (
        <Banner tone="info">Only part of your recent orders was searched for matches.</Banner>
      )}
      <table className={styles.table}>
        <thead>
          <tr>
            <th scope="col">Age</th>
            <th scope="col">Message</th>
            <th scope="col">Order</th>
            <th scope="col">Match</th>
          </tr>
        </thead>
        <tbody>
          {data.threads.map((thread) => (
            <tr key={thread.id}>
              <td className={styles.age}>{AGE_LABEL}</td>
              <td className={styles.snippet}>{thread.snippet}</td>
              <td className={styles.order}>{thread.matched_order_name ?? '—'}</td>
              <td>
                <span
                  className={
                    thread.match_confidence === 'high' ? styles.badgeHigh : styles.badge
                  }
                >
                  {confidenceLabel(thread.match_confidence)}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className={styles.footer}>
        Order matching is approximate: it uses the email preview text only, so it can miss an
        order or pick the wrong one.
      </p>
    </section>
  );
}
