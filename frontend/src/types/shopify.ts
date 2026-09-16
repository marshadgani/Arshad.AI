/**
 * Wire types for the /api/v1/shopify/* responses.
 *
 * Mirrors backend/src/schemas/shopify.py. Kept out of the page component so
 * the cards, the hook, and any future consumer share one definition.
 */

export type ConversionRateStatus = 'ok' | 'unavailable' | 'error';

export interface ShopifyOrder {
  id: string;
  order_number: string;
  customer_name: string | null;
  item_count: number;
  total_amount: string;
  currency_code: string;
  created_at: string;
}

export interface ShopifyDashboard {
  connected: boolean;
  needs_reauth: boolean;
  shop_name?: string | null;
  currency_code?: string | null;
  timezone?: string | null;
  as_of?: string | null;
  cached_at?: string | null;
  revenue_amount?: string | null;
  order_count?: number | null;
  order_count_approximate?: boolean;
  truncated?: boolean;
  conversion_rate?: number | null;
  conversion_rate_status?: ConversionRateStatus | null;
  average_order_value?: string | null;
  low_stock_sku_count?: number | null;
  low_stock_threshold?: number | null;
  recent_orders: ShopifyOrder[];
  partial_failures: string[];
}

export type TrendDirection = 'up' | 'down' | 'flat' | 'unknown';

export interface ShopifyInsightPoint {
  date: string;
  /** null ONLY for a date at or past the fetch's covered_through boundary
   * on a truncated window — a no-data gap, never a fabricated zero. */
  revenue_amount: string | null;
  order_count: number | null;
  is_partial_day: boolean;
}

export interface ShopifyInsightSummary {
  window_revenue: string;
  window_order_count: number;
  average_order_value: string | null;
  best_day: string | null;
  worst_day: string | null;
  completed_day_count: number;
  prior_period_change_pct: number | null;
  direction: TrendDirection;
}

export interface ShopifyInsights {
  days: number;
  currency_code: string;
  timezone: string;
  start_date: string;
  end_date: string;
  points: ShopifyInsightPoint[];
  summary: ShopifyInsightSummary | null;
  truncated: boolean;
  covered_through?: string | null;
  cached_at?: string | null;
  partial_failures: string[];
}
