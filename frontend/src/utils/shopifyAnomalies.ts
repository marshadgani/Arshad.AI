/**
 * Client-side anomaly detection over an already-fetched ShopifyInsights
 * trend window.
 *
 * Deliberately frontend-only rather than a new backend endpoint: the
 * /api/v1/shopify/insights response already carries every day's revenue
 * and order count for the selected window (see
 * backend/src/services/shopify/insights.py, whose docstring names this
 * exact seam — "the seam a future anomaly-detection pass attaches to" —
 * for a server-side pass; this module is the first cut, built on data the
 * page already holds with zero extra network calls or Shopify rate-bucket
 * spend). Recomputing here also means the detector rescales itself
 * instantly whenever the user flips the 7/14/30-day segmented control,
 * with no cache-key fan-out on the backend.
 *
 * Pure, no I/O — mirrors the backend parsers.py convention of pure
 * functions operating on already-parsed data.
 */

import type { ShopifyInsightPoint } from '../types/shopify';

export type ShopifyAnomalyType = 'spike' | 'dip' | 'silent';

export interface ShopifyAnomaly {
  date: string;
  type: ShopifyAnomalyType;
  revenueAmount: string;
  orderCount: number | null;
  /** Percent deviation from the window's mean daily revenue. Null when the
   * mean is zero (division is meaningless — see `silent`, which does not
   * depend on this field). */
  deviationPct: number | null;
  zScore: number;
}

export type ShopifyAnomalyStatus = 'insufficient-data' | 'no-anomalies' | 'anomalies';

export interface ShopifyAnomalyResult {
  status: ShopifyAnomalyStatus;
  anomalies: ShopifyAnomaly[];
}

// A z-score comparison over fewer than this many completed days is mostly
// sampling noise — the window hasn't accumulated enough of a baseline to
// call any single day unusual. Matches the backend's _MIN_HALF_DAYS * 2
// rationale in parsers.py (a period comparison needs real width per side).
const MIN_COMPLETED_DAYS = 5;

// Chosen for a small-n (7-30 point) window where a stricter 2.0-2.5
// textbook threshold rarely fires at all: 1.5 surfaces genuinely unusual
// days without flooding the card on a naturally spiky small store.
const Z_SCORE_THRESHOLD = 1.5;

function mean(values: number[]): number {
  return values.reduce((sum, v) => sum + v, 0) / values.length;
}

function populationStdDev(values: number[], avg: number): number {
  const variance = mean(values.map((v) => (v - avg) ** 2));
  return Math.sqrt(variance);
}

/**
 * Detects revenue spikes, dips, and zero-revenue "silent" days across the
 * window's completed calendar days.
 *
 * Excludes the trailing partial day (still accumulating — see
 * ShopifyInsightPoint.is_partial_day) and any truncated-fetch gap day
 * (revenue_amount === null), the same completed-day definition
 * parsers.py's _build_summary uses for its own trend stats, so the two
 * cards never disagree about which days "count".
 */
export function detectShopifyAnomalies(points: ShopifyInsightPoint[]): ShopifyAnomalyResult {
  const completed = points.filter((p) => !p.is_partial_day && p.revenue_amount != null);

  if (completed.length < MIN_COMPLETED_DAYS) {
    return { status: 'insufficient-data', anomalies: [] };
  }

  const values = completed.map((p) => Number(p.revenue_amount));
  const avg = mean(values);
  const stdDev = populationStdDev(values, avg);

  const anomalies: ShopifyAnomaly[] = [];

  completed.forEach((point, i) => {
    const value = values[i];
    const zScore = stdDev > 0 ? (value - avg) / stdDev : 0;
    const deviationPct = avg > 0 ? Math.round(((value - avg) / avg) * 100) : null;

    // A zero-revenue day against a genuinely active baseline is inherently
    // notable regardless of z-score (a low stdDev from many quiet days
    // would otherwise mask it) — checked before the generic dip branch so
    // it never double-classifies.
    let type: ShopifyAnomalyType | null = null;
    if (value === 0 && avg > 0) {
      type = 'silent';
    } else if (zScore >= Z_SCORE_THRESHOLD) {
      type = 'spike';
    } else if (zScore <= -Z_SCORE_THRESHOLD) {
      type = 'dip';
    }

    if (type) {
      anomalies.push({
        date: point.date,
        type,
        revenueAmount: point.revenue_amount as string,
        orderCount: point.order_count,
        deviationPct,
        zScore: Math.round(zScore * 100) / 100,
      });
    }
  });

  // Most recent first — the alert most likely to still be actionable.
  anomalies.sort((a, b) => (a.date < b.date ? 1 : -1));

  return {
    status: anomalies.length > 0 ? 'anomalies' : 'no-anomalies',
    anomalies,
  };
}
