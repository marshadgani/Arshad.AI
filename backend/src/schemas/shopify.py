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
