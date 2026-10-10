"""Discount-code break-even check. Pure: no I/O, no clock.

A code is valid only if the discounted unit price still covers the unit
cost Shopify holds for the variant. Unknown cost is its own outcome
(valid=None), never a guess.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from ...schemas.shopify import DiscountSimulatorResponse

_CENT = Decimal("0.01")
_HUNDRED = Decimal("100")


def _money(value: Decimal) -> str:
    return str(value.quantize(_CENT, rounding=ROUND_HALF_UP))


def _decimal(value: Any) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() and parsed >= 0 else None


def parse_variant_pricing(
    variant: dict[str, Any],
) -> tuple[Decimal | None, Decimal | None]:
    """(price, unit_cost) from a productVariant node; None where absent or
    malformed. A missing price means the variant cannot be evaluated at all.
    """
    unit_cost = (((variant.get("inventoryItem") or {}).get("unitCost")) or {}).get(
        "amount"
    )
    price = variant.get("price")
    return (
        _decimal(price) if price is not None else None,
        _decimal(unit_cost) if unit_cost is not None else None,
    )


def evaluate_discount(
    base_price: Decimal, unit_cost: Decimal | None, discount_percent: float
) -> DiscountSimulatorResponse:
    # str() first: Decimal(0.1) would carry the binary float error into money.
    rate = Decimal(str(discount_percent)) / _HUNDRED
    discounted = (base_price * (Decimal(1) - rate)).quantize(
        _CENT, rounding=ROUND_HALF_UP
    )

    common = {
        "base_price": _money(base_price),
        "discounted_price": _money(discounted),
    }

    if unit_cost is None:
        return DiscountSimulatorResponse(valid=None, cost_unavailable=True, **common)

    margin = discounted - unit_cost
    common["unit_cost"] = _money(unit_cost)
    if margin >= 0:
        return DiscountSimulatorResponse(
            valid=True, margin_remaining=_money(margin), **common
        )

    # Largest whole-cent-safe discount: price * (1 - d) >= cost. Rounded DOWN
    # so the suggestion itself never lands below cost.
    if base_price > 0:
        max_safe = max(
            Decimal(0), (Decimal(1) - unit_cost / base_price) * _HUNDRED
        ).quantize(_CENT, rounding=ROUND_DOWN)
    else:
        max_safe = Decimal(0).quantize(_CENT, rounding=ROUND_DOWN)
    return DiscountSimulatorResponse(
        valid=False,
        margin_remaining=_money(margin),
        reason=(
            f"Discounted price {_money(discounted)} is below unit cost "
            f"{_money(unit_cost)}; this code cannot break even."
        ),
        max_safe_discount_pct=str(max_safe),
        **common,
    )
