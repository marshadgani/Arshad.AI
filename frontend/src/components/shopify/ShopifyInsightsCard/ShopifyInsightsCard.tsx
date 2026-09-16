import styles from './ShopifyInsightsCard.module.css';
import type { ShopifyInsightPoint, ShopifyInsights } from '../../../types/shopify';
import { formatMoney, formatPercentChange, formatTrendDirection } from '../../../utils/shopifyFormat';

const DAY_OPTIONS: readonly (7 | 14 | 30)[] = [7, 14, 30];

export interface ShopifyInsightsCardProps {
  insights: ShopifyInsights | null;
  days: 7 | 14 | 30;
  onDaysChange: (days: 7 | 14 | 30) => void;
  isLoading: boolean;
  /** Non-null when the secondary /insights fetch failed. Rendered as a
   * distinct red banner rather than folded into the "no data" empty state
   * — the two are different facts for the user, same convention as
   * HRVTrendCard. */
  error?: Error | null;
  onRefresh?: () => void;
}

function fmtDate(iso: string): string {
  const d = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', timeZone: 'UTC' });
}

/**
 * Bar sparkline of daily Shopify revenue, mirroring HRVTrendCard's pattern:
 * heights relative to the window's own max (not a fixed scale), a minimum
 * height floor so a low day stays hoverable.
 *
 * Differs from HRVTrendCard in two ways the wire data forces: a point with
 * revenue_amount === null renders as a dotted "gap" bar (truncated window —
 * never a fabricated zero), and the final point (is_partial_day) renders
 * dimmed with a "today, so far" title.
 */
function InsightsSparkline({ points, currencyCode }: { points: ShopifyInsightPoint[]; currencyCode: string }) {
  const values = points.map((p) => (p.revenue_amount != null ? Number(p.revenue_amount) : 0));
  const maxVal = Math.max(...values, 1);

  return (
    <>
      <div className={styles.sparkline}>
        {points.map((p, i) => {
          const isGap = p.revenue_amount == null;
          const heightPct = isGap ? 6 : Math.max((values[i] / maxVal) * 100, 6);
          const classNames = [styles.sparkBar];
          if (isGap) classNames.push(styles.gapBar);
          if (p.is_partial_day) classNames.push(styles.partialBar);

          const title = isGap
            ? `${p.date}: no data — window truncated`
            : p.is_partial_day
              ? `${p.date}: today, so far (${formatMoney(p.revenue_amount, currencyCode)})`
              : `${p.date}: ${formatMoney(p.revenue_amount, currencyCode)}`;

          return (
            <div
              key={p.date}
              className={classNames.join(' ')}
              style={{ height: `${heightPct}%` }}
              title={title}
            />
          );
        })}
      </div>
      <div className={styles.sparkLabels}>
        <span>{fmtDate(points[0]?.date ?? '')}</span>
        <span>{fmtDate(points[points.length - 1]?.date ?? '')}</span>
      </div>
    </>
  );
}

export default function ShopifyInsightsCard({
  insights,
  days,
  onDaysChange,
  isLoading,
  error = null,
  onRefresh,
}: ShopifyInsightsCardProps) {
  const showLoading = isLoading && !insights;
  // Not `error && !insights`: after a `days` switch useFetch keeps the
  // PREVIOUS window's data while the new request runs, so gating on
  // !insights would swallow the failure and leave the old window's bars on
  // screen under the new window's label. An error always wins over data
  // that may describe a different window.
  const showError = !!error;
  const points = insights?.points ?? [];
  const hasData = points.length > 0;

  return (
    <div className={styles.card} aria-label={`Shopify revenue trend, ${days} days`}>
      <div className={styles.header}>
        <p className={styles.cardTitle}>Revenue Trend</p>
        <div className={styles.controls}>
          <div className={styles.daySelector} role="group" aria-label="Trend window">
            {DAY_OPTIONS.map((option) => (
              <button
                key={option}
                type="button"
                className={styles.dayButton}
                aria-pressed={option === days}
                onClick={() => onDaysChange(option)}
              >
                {option}d
              </button>
            ))}
          </div>
          {onRefresh && (
            <button type="button" className={styles.refreshButton} onClick={onRefresh}>
              Refresh
            </button>
          )}
        </div>
      </div>

      {showLoading && (
        <div className={styles.skeleton} role="status">
          <span className="sr-only">Loading Shopify revenue trend…</span>
        </div>
      )}

      {showError && (
        <p role="alert" className={styles.errorBanner}>
          Could not load trend — retry later
        </p>
      )}

      {!showLoading && !showError && !hasData && <p className={styles.empty}>No revenue data</p>}

      {!showLoading && !showError && hasData && insights && (
        <>
          <InsightsSparkline points={points} currencyCode={insights.currency_code} />

          {insights.truncated && (
            <p className={styles.notice} role="status">
              Trend data is incomplete for this window
              {insights.covered_through ? ` (covered through ${insights.covered_through})` : ''}.
            </p>
          )}

          {insights.summary && (
            <div className={styles.summaryRow}>
              <span>
                {formatMoney(insights.summary.window_revenue, insights.currency_code)} over last{' '}
                {insights.summary.completed_day_count} complete days
              </span>
              <span>
                {formatTrendDirection(insights.summary.direction)}{' '}
                {formatPercentChange(insights.summary.prior_period_change_pct)}
              </span>
              <span>{insights.summary.window_order_count} orders</span>
            </div>
          )}
        </>
      )}
    </div>
  );
}
