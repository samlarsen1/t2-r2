"""Turn Trading212 order history items into ledger rows.

Trading212 has returned two shapes over time: a flat order with ``executor``, ``fillPrice`` and
``dateExecuted``, and an ``{"order": ..., "fill": ...}`` pair with ``initiatedFrom``. Both are
read, and the raw item is kept so new fields can be parsed later without fetching again.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

# Where an order was placed, as Trading212 reports it, mapped to who decided it
API_ORIGINS = frozenset({"API"})
AUTOMATIC_ORIGINS = frozenset({"AUTOINVEST", "SYSTEM"})
FINAL_STATUSES = frozenset({"FILLED", "CANCELLED", "REJECTED"})


@dataclass(frozen=True)
class OrderRow:
    """One historical order and its fill, if it had one."""

    order_id: int
    ticker: str
    side: str | None
    type: str | None
    status: str | None
    origin: str | None
    quantity: float | None
    filled_quantity: float | None
    limit_price: float | None
    fill_price: float | None
    fill_value: float | None  # in the account currency, fees and FX included, when known
    fx_rate: float | None
    taxes: float | None  # fees and stamp duty, in the account currency, when known
    currency: str | None
    created_at: str | None
    filled_at: str | None
    raw: str

    @property
    def is_final(self) -> bool:
        return self.status in FINAL_STATUSES

    @property
    def is_api(self) -> bool:
        return self.origin in API_ORIGINS


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _str(value: Any) -> str | None:
    return str(value) if value not in (None, "") else None


def _taxes(items: Any) -> float | None:
    if not isinstance(items, list):
        return None
    total = 0.0
    for item in items:
        if isinstance(item, dict) and (amount := _num(item.get("quantity"))) is not None:
            total += abs(amount)
    return total


def parse_item(item: dict[str, Any]) -> OrderRow | None:
    """Parse one history item; ``None`` if it has no order id or ticker."""
    order = item.get("order") if isinstance(item.get("order"), dict) else item
    fill = item.get("fill") if isinstance(item.get("fill"), dict) else {}
    assert isinstance(order, dict) and isinstance(fill, dict)  # nosec B101 - narrowed above
    order_id = order.get("id")
    ticker = _str(order.get("ticker"))
    if not isinstance(order_id, int) or ticker is None:
        return None

    quantity = _num(order.get("quantity", order.get("orderedQuantity")))
    side = _str(order.get("side"))
    if side is None and quantity is not None and quantity != 0:
        side = "SELL" if quantity < 0 else "BUY"  # the flat shape signs sell quantities
    filled_quantity = _num(fill.get("quantity", order.get("filledQuantity")))

    impact = fill.get("walletImpact") if isinstance(fill.get("walletImpact"), dict) else {}
    assert isinstance(impact, dict)  # nosec B101 - narrowed above
    fill_value = _num(impact.get("netValue", order.get("fillCost", order.get("filledValue"))))
    taxes = _taxes(impact.get("taxes", order.get("taxes")))

    return OrderRow(
        order_id=order_id,
        ticker=ticker,
        side=side.upper() if side else None,
        type=_str(order.get("type")),
        status=_str(order.get("status")),
        origin=_str(order.get("initiatedFrom", order.get("executor"))),
        quantity=abs(quantity) if quantity is not None else None,
        filled_quantity=abs(filled_quantity) if filled_quantity is not None else None,
        limit_price=_num(order.get("limitPrice")),
        fill_price=_num(fill.get("price", order.get("fillPrice", order.get("filledPrice")))),
        fill_value=abs(fill_value) if fill_value is not None else None,
        fx_rate=_num(impact.get("fxRate")),
        taxes=taxes,
        currency=_str(impact.get("currency", order.get("currency"))),
        created_at=_str(order.get("createdAt", order.get("dateCreated"))),
        filled_at=_str(fill.get("filledAt", order.get("dateExecuted"))),
        raw=json.dumps(item, sort_keys=True, separators=(",", ":")),
    )
