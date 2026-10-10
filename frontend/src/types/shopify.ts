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

// ── Intelligence layer (FEAT-125) ──────────────────────────────────────

export interface DaysCoverItem {
  variant_id: string;
  available_qty: number;
  velocity_30d: string | null;
  days_of_cover: string | null;
  no_recent_sales: boolean;
  is_alert: boolean;
  projected_stockout_date: string | null;
}

export interface StockoutAlert {
  variant_id: string;
  projected_stockout_date: string;
  travel_event_title: string;
}

export interface InventoryCoverResponse {
  connected: boolean;
  needs_reauth: boolean;
  days_of_cover: DaysCoverItem[];
  alerts: StockoutAlert[];
  variants_truncated: boolean;
  orders_truncated: boolean;
  calendar_connected: boolean;
  calendar_needs_reauth: boolean;
  partial_failures: string[];
  cached_at: string | null;
}

export interface DiscountSimulatorResult {
  connected: boolean;
  needs_reauth: boolean;
  /** true: margin holds. false: sells below cost. null: cannot tell. */
  valid: boolean | null;
  cost_unavailable: boolean;
  variant_found: boolean;
  base_price: string | null;
  discounted_price: string | null;
  unit_cost: string | null;
  margin_remaining: string | null;
  reason: string | null;
  max_safe_discount_pct: string | null;
  partial_failures: string[];
}

export type MatchConfidence = 'high' | 'low';

export interface ThreadMeta {
  id: string;
  snippet: string;
  matched_order_id: string | null;
  matched_order_name: string | null;
  match_confidence: MatchConfidence | null;
}

export interface ServiceDebtResponse {
  gmail_connected: boolean;
  shopify_connected: boolean;
  needs_reauth: boolean;
  threads: ThreadMeta[];
  threads_truncated: boolean;
  orders_truncated: boolean;
  partial_failures: string[];
  cached_at: string | null;
}
