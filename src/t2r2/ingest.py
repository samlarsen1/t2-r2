"""Fill the ledger from run reports and Trading212's order history."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol

from .config import TRADING_DROIDS, Settings
from .history import parse_item
from .ledger import Ledger
from .runs import read_runs

logger = logging.getLogger(__name__)


class HistorySource(Protocol):
    def history_pages(self) -> Iterable[list[dict[str, Any]]]: ...


@dataclass
class IngestResult:
    runs: int = 0
    run_orders: int = 0
    pages: int = 0
    orders: int = 0
    skipped_items: int = 0
    by_source: dict[str, int] = field(default_factory=dict)

    def summary(self) -> str:
        sources = ", ".join(f"{k} {v}" for k, v in self.by_source.items()) or "none"
        return (f"{self.runs} run reports ({self.run_orders} orders named), "
                f"{self.orders} orders from {self.pages} history pages; by source: {sources}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "runs": self.runs,
            "run_orders": self.run_orders,
            "history_pages": self.pages,
            "orders": self.orders,
            "skipped_items": self.skipped_items,
            "by_source": self.by_source,
        }


def ingest_runs(ledger: Ledger, settings: Settings, result: IngestResult) -> None:
    for droid in TRADING_DROIDS:
        runs, orders = ledger.add_runs(read_runs(droid, settings.runs_dir(droid)))
        result.runs += runs
        result.run_orders += orders


def ingest_history(
    ledger: Ledger, source: HistorySource, result: IngestResult, *, full: bool = False
) -> None:
    """Store history pages, newest first, until a page holds nothing new.

    A page is "nothing new" when every order on it is already stored with a final status
    (filled, cancelled or rejected). ``full`` reads every page.
    """
    for page in source.history_pages():
        result.pages += 1
        rows = []
        for item in page:
            row = parse_item(item)
            if row is None:
                result.skipped_items += 1
            else:
                rows.append(row)
        already_final = ledger.known_final(r.order_id for r in rows)
        result.orders += ledger.add_orders(rows)
        if not full and rows and all(r.order_id in already_final for r in rows):
            logger.info("history caught up after %d pages", result.pages)
            return
