import { useMemo } from 'react';

import styles from './ShopifyAnomalyRadar.module.css';
import { detectShopifyAnomalies, type ShopifyAnomaly } from '../../../utils/shopifyAnomalies';
import type { ShopifyInsights } from '../../../types/shopify';
import { formatMoney } from '../../../utils/shopifyFormat';

export interface ShopifyAnomalyRadarProps {
  insights: ShopifyInsights | null;
  /** Shares the insights fetch's own loading/error signal — the radar is
   * derived data, not a second network call, so it mirrors whatever state
   * ShopifyInsightsCard is already in rather than tracking its own. */
  isLoading: boolean;
  error?: Error | null;
}

const TYPE_COPY: Record<ShopifyAnomaly['type'], { label: string; icon: string; sentence: (a: ShopifyAnomaly) => string }> = {
  spike: {
    label: 'Spike',
    icon: '▲',
    sentence: (a) =>
      `${a.deviationPct != null ? `${a.deviationPct > 0 ? '+' : ''}${a.deviationPct}%` : 'Unusually high'} vs. the window average${
        a.orderCount != null ? ` · ${a.orderCount} orders` : ''
      }`,
  },
  dip: {
    label: 'Dip',
    icon: '▼',
    sentence: (a) =>
      `${a.deviationPct != null ? `${a.deviationPct}%` : 'Unusually low'} vs. the window average${
        a.orderCount != null ? ` · ${a.orderCount} orders` : ''
      }`,
  },
  silent: {
    label: 'Silent day',
    icon: '●',
    sentence: () => 'Zero revenue against an otherwise active window',
  },
};

function fmtDate(iso: string): string {
  const d = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric', timeZone: 'UTC' });
}

/**
 * Anomaly Radar — flags revenue spikes, dips, and silent (zero-revenue)
 * days within the currently-selected insights window.
 *
 * Purely derived from the ShopifyInsightsCard's own `insights` payload
 * (see utils/shopifyAnomalies.ts for why this needs no new endpoint), so
 * it shares that card's loading/error signal instead of issuing a second
 * fetch. Four states: loading (skeleton), error (banner), empty
 * ("All clear" — a real, distinct positive state, not a blank box), and
 * content (the alert list).
 */
export default function ShopifyAnomalyRadar({ insights, isLoading, error = null }: ShopifyAnomalyRadarProps) {
  const result = useMemo(
    () => detectShopifyAnomalies(insights?.points ?? []),
    [insights],
  );

  const showLoading = isLoading && !insights;
  const showError = !!error;

  return (
    <div className={styles.card} aria-label="Shopify anomaly radar">
      <div className={styles.header}>
        <p className={styles.cardTitle}>
          <span className={styles.radarDot} aria-hidden="true" />
          Anomaly Radar
        </p>
        {result.status === 'anomalies' && (
          <span className={styles.countBadge}>{result.anomalies.length}</span>
        )}
      </div>

      {showLoading && (
        <div className={styles.skeleton} role="status">
          <span className="sr-only">Scanning revenue trend for anomalies…</span>
        </div>
      )}

      {!showLoading && showError && (
        <p role="alert" className={styles.errorBanner}>
          Could not scan for anomalies — retry later
        </p>
      )}

      {!showLoading && !showError && result.status === 'insufficient-data' && (
        <p className={styles.empty}>Not enough completed days yet to detect anomalies.</p>
      )}

      {!showLoading && !showError && result.status === 'no-anomalies' && (
        <div className={styles.allClear} role="status">
          <span className={styles.allClearIcon} aria-hidden="true">
            ✓
          </span>
          <span>All clear — no unusual days in this window.</span>
        </div>
      )}

      {!showLoading && !showError && result.status === 'anomalies' && (
        <ul className={styles.list} aria-label="Detected anomalies">
          {result.anomalies.map((a) => {
            const copy = TYPE_COPY[a.type];
            return (
              <li key={a.date} className={`${styles.item} ${styles[a.type]}`}>
                <span className={styles.itemIcon} aria-hidden="true">
                  {copy.icon}
                </span>
                <div className={styles.itemBody}>
                  <div className={styles.itemHeadline}>
                    <span className={styles.itemBadge}>{copy.label}</span>
                    <span className={styles.itemDate}>{fmtDate(a.date)}</span>
                    <span className={styles.itemAmount}>
                      {formatMoney(a.revenueAmount, insights?.currency_code)}
                    </span>
                  </div>
                  <p className={styles.itemDetail}>{copy.sentence(a)}</p>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
