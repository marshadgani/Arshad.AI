import { useState } from 'react';

import {
  ShopifyAnomalyRadar,
  ShopifyErrorPanel,
  ShopifyInsightsCard,
  ShopifyKpiGrid,
  ShopifyKpiGridSkeleton,
  ShopifyNoticePanel,
  ShopifyPageHeader,
} from '../components/shopify';
import { useShopifyDashboard } from '../hooks/useShopifyDashboard';
import { useShopifyInsights } from '../hooks/useShopifyInsights';
import { shopSubtitle, staleLabel } from '../utils/shopifyFormat';
import styles from './ShopifyStore.module.css';

/**
 * Shopify Store dashboard.
 *
 * Standalone page driven solely by useShopifyDashboard — NOT composed via
 * DomainPage, following the HealthFitness.tsx precedent. The Applications
 * and Agents catalogue sections that DomainPage would otherwise render are
 * deliberately omitted: they are domain-catalogue data, not live store
 * operations, and pulling them in would require a second fetch to
 * GET /api/v1/domains/shopify. A future enhancement can composite them.
 *
 * This component is a state router and nothing else — it decides WHICH of
 * the five states to show; each state's markup and styling belongs to a
 * component under components/shopify/:
 *   loading  — ShopifyKpiGridSkeleton (first fetch only)
 *   error    — ShopifyErrorPanel (first fetch only)
 *   empty    — ShopifyNoticePanel, for not-connected and needs-reauth
 *   content  — ShopifyKpiGrid
 *
 * Loading/error gate on `!dashboard` so a 120s poll never blanks an
 * already-rendered page — only the "Updated N min ago" label changes on
 * refetch.
 */
export default function ShopifyStore() {
  const { dashboard, isLoading, error } = useShopifyDashboard();
  const [insightsDays, setInsightsDays] = useState<7 | 14 | 30>(14);
  // Independent of the dashboard hook — an insights fetch failure must
  // never blank the KPI grid above it, and this secondary fetch must never
  // fire on the not-connected / needs-reauth branches (which return before
  // reaching the content branch below anyway; `skip` additionally covers
  // the transitional render while `dashboard` is still loading).
  const {
    insights,
    isLoading: insightsLoading,
    error: insightsError,
    refetch: refetchInsights,
  } = useShopifyInsights({
    days: insightsDays,
    skip: !dashboard?.connected || !!dashboard?.needs_reauth,
  });

  if (isLoading && !dashboard) {
    return (
      <div className={styles.page}>
        <ShopifyPageHeader />
        <ShopifyKpiGridSkeleton />
        <span className="sr-only" role="status">
          Loading Shopify dashboard…
        </span>
      </div>
    );
  }

  if (error && !dashboard) {
    return (
      <div className={styles.page}>
        <ShopifyPageHeader />
        <ShopifyErrorPanel message="Failed to load Shopify data. Check backend logs." />
      </div>
    );
  }

  if (!dashboard?.connected) {
    return (
      <div className={styles.page}>
        <ShopifyPageHeader />
        <ShopifyNoticePanel
          icon="🛒"
          title="Connect Shopify"
          description="Link your Shopify store to see today's revenue, orders, and inventory alerts."
          actionLabel="Connect Shopify"
          actionHref="/integrations"
        />
      </div>
    );
  }

  if (dashboard.needs_reauth) {
    return (
      <div className={styles.page}>
        <ShopifyPageHeader />
        <ShopifyNoticePanel
          icon="⚠️"
          title="Reconnect Shopify"
          description="Your Shopify session has expired. Reconnect your store to keep seeing live order data."
          actionLabel="Reconnect Shopify"
          actionHref="/integrations"
        />
      </div>
    );
  }

  const stale = staleLabel(dashboard.cached_at);

  return (
    <div className={styles.page}>
      <ShopifyPageHeader
        subtitle={shopSubtitle(dashboard.shop_name, dashboard.timezone)}
        live
      />
      {stale && (
        <p className={styles.stale} role="status">
          {stale}
        </p>
      )}
      <ShopifyKpiGrid dashboard={dashboard} />
      <ShopifyInsightsCard
        insights={insights}
        days={insightsDays}
        onDaysChange={setInsightsDays}
        isLoading={insightsLoading}
        error={insightsError}
        onRefresh={refetchInsights}
      />
      <ShopifyAnomalyRadar insights={insights} isLoading={insightsLoading} error={insightsError} />
    </div>
  );
}
