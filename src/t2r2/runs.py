"""Read the trading droids' run reports for the orders they placed."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunRow:
    run_id: str  # the report's file name, unique per droid run
    droid: str
    command: str
    started_at: str
    status: str
    dry_run: bool | None
    summary: str


@dataclass(frozen=True)
class RunOrder:
    """An order a droid says it placed."""

    order_id: int
    droid: str
    run_id: str
    ticker: str | None
    strategy: str | None
    reason: str | None


def _orders(droid: str, run_id: str, result: dict[str, Any]) -> Iterator[RunOrder]:
    if droid == "t2-d2":
        for trade in result.get("trades") or []:
            if isinstance(trade, dict) and isinstance(trade.get("order_id"), int):
                yield RunOrder(trade["order_id"], droid, run_id,
                               trade.get("t212_ticker") or trade.get("ticker"),
                               trade.get("strategy"), trade.get("reason"))
    elif droid == "t2-k2":
        for decision in result.get("decisions") or []:
            order = decision.get("order") if isinstance(decision, dict) else None
            if isinstance(order, dict) and isinstance(order.get("id"), int):
                yield RunOrder(order["id"], droid, run_id, decision.get("ticker"),
                               "harvest", decision.get("reason"))


def read_runs(droid: str, runs_dir: Path) -> Iterator[tuple[RunRow, list[RunOrder]]]:
    """Every readable run report in ``runs_dir``, with the orders it names."""
    if not runs_dir.is_dir():
        logger.info("no run reports for %s at %s", droid, runs_dir)
        return
    for path in sorted(runs_dir.glob("*.json")):
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("unreadable run report %s (%s)", path.name, type(exc).__name__)
            continue
        if not isinstance(report, dict) or report.get("droid") != droid:
            continue
        run_id = f"{droid}/{path.name}"
        run = RunRow(
            run_id=run_id,
            droid=droid,
            command=str(report.get("command", "")),
            started_at=str(report.get("started_at", "")),
            status=str(report.get("status", "")),
            dry_run=report.get("dry_run") if isinstance(report.get("dry_run"), bool) else None,
            summary=str(report.get("summary", "")),
        )
        result = report.get("result")
        orders = list(_orders(droid, run_id, result)) if isinstance(result, dict) else []
        if run.dry_run:
            orders = []  # a dry run placed nothing, whatever it reports
        yield run, orders
