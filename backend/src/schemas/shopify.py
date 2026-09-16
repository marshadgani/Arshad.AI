"""Pydantic v2 response schemas for /api/v1/shopify/*."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel

ConversionRateStatus = Literal["ok", "unavailable", "error"]


class ShopifyOrder(BaseModel):
    id: str
    order_number: str
    customer_name: Optional[str] = None
    item_count: int
    total_amount: str
    currency_code: str
    created_at: str


class ShopifyDashboard(BaseModel):
    connected: bool
    needs_reauth: bool = False
    shop_name: Optional[str] = None
    currency_code: Optional[str] = None
    timezone: Optional[str] = None
    as_of: Optional[str] = None
    cached_at: Optional[str] = None
    revenue_amount: Optional[str] = None
    order_count: Optional[int] = None
    order_count_approximate: bool = False
    truncated: bool = False
    conversion_rate: Optional[float] = None
    conversion_rate_status: Optional[ConversionRateStatus] = None
    average_order_value: Optional[str] = None
    low_stock_sku_count: Optional[int] = None
    low_stock_threshold: int = 5
    recent_orders: list[ShopifyOrder] = []
    partial_failures: list[str] = []


TrendDirection = Literal["up", "down", "flat", "unknown"]


class ShopifyInsightPoint(BaseModel):
    """One shop-local calendar day in a revenue/order trend.

    revenue_amount and order_count are None ONLY for a date at or past
    the fetch's covered_through boundary on a truncated window — a
    no-data gap, never a fabricated zero. See parsers.parse_insights.
    """

    date: str
    revenue_amount: Optional[str] = None
    order_count: Optional[int] = None
    is_partial_day: bool = False


class ShopifyInsightSummary(BaseModel):
    """Aggregate stats over the window's completed (non-partial, non-gap)
    days only. Present only when the fetch was not truncated.
    """

    window_revenue: str
    window_order_count: int
    average_order_value: Optional[str] = None
    best_day: Optional[str] = None
    worst_day: Optional[str] = None
    completed_day_count: int
    prior_period_change_pct: Optional[float] = None
    direction: TrendDirection = "unknown"


class ShopifyInsights(BaseModel):
    days: int
    currency_code: str
    timezone: str
    start_date: str
    end_date: str
    points: list[ShopifyInsightPoint] = []
    summary: Optional[ShopifyInsightSummary] = None
    truncated: bool = False
    covered_through: Optional[str] = None
    cached_at: Optional[str] = None
    partial_failures: list[str] = []
