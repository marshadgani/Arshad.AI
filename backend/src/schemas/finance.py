"""Pydantic v2 response schemas for GET /api/v1/finance/holdings.

BrokerStatus mirrors src.services.integrations.state.ACTIVE_STATUSES exactly
-- change both together. services/finance/holdings.py::resolve_status coerces
any unexpected Integration.status value to "error" rather than letting
Pydantic raise here, because the endpoint's contract is always-200. That
module derives its accepted set from this Literal via get_args(), so the
enum is defined here once and nowhere else.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel

BrokerStatus = Literal["connected", "expired", "error"]


class Holding(BaseModel):
    symbol: str
    qty: Optional[float] = None
    ltp: Optional[float] = None
    pnl: Optional[float] = None
    value: Optional[float] = None


class BrokerHoldings(BaseModel):
    broker: str
    display_name: str
    status: BrokerStatus
    needs_reauth: bool
    currency: str = "INR"
    holding_count: int
    truncated: bool
    holdings: list[Holding] = []
    last_synced_at: Optional[str] = None
    error: Optional[str] = None


class FinanceHoldingsResponse(BaseModel):
    connected: bool
    brokers: list[BrokerHoldings] = []
