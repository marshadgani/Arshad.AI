"""Pydantic v2 response schemas for /api/v1/shopify/*."""

from __future__ import annotations

from datetime import date
from typing import Literal, Optional, Self

from pydantic import BaseModel, Field, model_validator

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


# ── Intelligence layer (FEAT-125) ────────────────────────────────────────
# All quantities and money are Decimal-formatted strings on the wire; no
# float ever leaves the service layer.


class DaysCoverItem(BaseModel):
    variant_id: str
    available_qty: int
    velocity_30d: Optional[str] = None
    days_of_cover: Optional[str] = None
    no_recent_sales: bool = False
    is_alert: bool = False
    projected_stockout_date: Optional[str] = None


class StockoutAlert(BaseModel):
    variant_id: str
    projected_stockout_date: str
    travel_event_title: str


class InventoryCoverResponse(BaseModel):
    connected: bool
    needs_reauth: bool = False
    days_of_cover: list[DaysCoverItem] = []
    alerts: list[StockoutAlert] = []
    variants_truncated: bool = False
    orders_truncated: bool = False
    calendar_connected: bool = True
    calendar_needs_reauth: bool = False
    partial_failures: list[str] = []
    cached_at: Optional[str] = None


class DiscountSimulatorRequest(BaseModel):
    # The pattern is the single guard against log injection: variant_id is
    # echoed into log lines and a GraphQL variable.
    variant_id: str = Field(pattern=r"^[a-zA-Z0-9_/:-]{1,100}$")
    discount_percent: float = Field(ge=0, le=100)


class DiscountSimulatorResponse(BaseModel):
    connected: bool = True
    needs_reauth: bool = False
    # Three states: True (margin holds), False (loses money), None (unit cost
    # unknown). A plain bool would report "unknown" as False.
    valid: Optional[bool] = None
    cost_unavailable: bool = False
    variant_found: bool = True
    base_price: Optional[str] = None
    discounted_price: Optional[str] = None
    unit_cost: Optional[str] = None
    margin_remaining: Optional[str] = None
    reason: Optional[str] = None
    max_safe_discount_pct: Optional[str] = None
    partial_failures: list[str] = []


class ThreadMeta(BaseModel):
    id: str
    snippet: str
    matched_order_id: Optional[str] = None
    matched_order_name: Optional[str] = None
    match_confidence: Optional[Literal["high", "low"]] = None


class ServiceDebtResponse(BaseModel):
    gmail_connected: bool
    shopify_connected: bool = True
    needs_reauth: bool = False
    threads: list[ThreadMeta] = []
    threads_truncated: bool = False
    orders_truncated: bool = False
    partial_failures: list[str] = []
    cached_at: Optional[str] = None


# ── Trip feasibility (FEAT-129) ──────────────────────────────────────────

TRIP_MAX_DAYS = 60


class TripFeasibilityRequest(BaseModel):
    """Inclusive travel window. `date` fields reject non-ISO strings (422)."""

    start_date: date
    end_date: date

    @model_validator(mode="after")
    def _check_window(self) -> Self:
        if self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date")
        if (self.end_date - self.start_date).days + 1 > TRIP_MAX_DAYS:
            raise ValueError(f"window must be at most {TRIP_MAX_DAYS} days")
        return self


class TripConflict(BaseModel):
    """Flat on the wire; the validator makes each `type` carry its own fields
    and none of the other type's."""

    type: Literal["stockout", "calendar_event"]
    variant_id: Optional[str] = None
    projected_stockout_date: Optional[str] = None
    event_title: Optional[str] = None
    event_start: Optional[str] = None
    event_end: Optional[str] = None

    @model_validator(mode="after")
    def _check_fields_match_type(self) -> Self:
        stockout = (self.variant_id, self.projected_stockout_date)
        event = (self.event_title, self.event_start, self.event_end)
        wanted, forbidden = (
            (stockout, event) if self.type == "stockout" else (event, stockout)
        )
        if any(v is None for v in wanted) or any(v is not None for v in forbidden):
            raise ValueError(f"fields do not match conflict type {self.type!r}")
        return self


class TripAllDayEvent(BaseModel):
    """Informational only: an all-day event overlapping the window is listed
    but is not a conflict."""

    title: str
    start_date: str


UnavailableSourceName = Literal[
    "booking_com_pricing", "calendly_availability", "deploy_windows"
]


class UnavailableSource(BaseModel):
    name: UnavailableSourceName
    reason: Literal["not_connected"] = "not_connected"


class TripFeasibilityResponse(BaseModel):
    verdict: Literal["go", "no-go", "unknown"]
    conflicts: list[TripConflict] = []
    all_day_events: list[TripAllDayEvent] = []
    unavailable_sources: list[UnavailableSource] = []
    shopify_connected: bool = False
    shopify_needs_reauth: bool = False
    calendar_connected: bool = False
    calendar_needs_reauth: bool = False
    variants_truncated: bool = False
    orders_truncated: bool = False
    calendar_truncated: bool = False
    partial_failures: list[str] = []

    @model_validator(mode="after")
    def _check_verdict_invariants(self) -> Self:
        """A "go" can never coexist with a conflict or a degraded source, and
        a "no-go" always carries the conflict that drove it."""
        if self.verdict == "no-go" and not self.conflicts:
            raise ValueError("no-go requires at least one conflict")
        if self.verdict == "go":
            degraded = (
                self.conflicts
                or not self.shopify_connected
                or self.shopify_needs_reauth
                or not self.calendar_connected
                or self.calendar_needs_reauth
                or self.variants_truncated
                or self.orders_truncated
                or self.calendar_truncated
                or self.partial_failures
            )
            if degraded:
                raise ValueError("go requires clean, fully connected sources")
        return self
