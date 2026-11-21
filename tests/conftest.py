from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def contract_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep run reports and locks inside the test's folder."""
    monkeypatch.setenv("T2_RUNS_DIR", str(tmp_path / "own-runs"))
    monkeypatch.setenv("T2_LOCK_DIR", str(tmp_path / "locks"))
    return tmp_path


def write_report(apps: Path, droid: str, name: str, result: dict[str, Any],
                 dry_run: bool = False) -> None:
    runs = apps / droid / "var" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    report = {"schema": "t2.run-report/1", "droid": droid, "command": "session eu_morning",
              "started_at": "2026-11-19T08:30:00+00:00", "status": "ok", "dry_run": dry_run,
              "summary": "test", "result": result}
    (runs / name).write_text(json.dumps(report))


def item(order_id: int, ticker: str = "RIOl_EQ", side: str = "BUY", origin: str = "API",
         status: str = "FILLED") -> dict[str, Any]:
    """A history item in Trading212's order + fill shape."""
    return {
        "order": {"id": order_id, "ticker": ticker, "side": side, "type": "LIMIT",
                  "status": status, "initiatedFrom": origin, "quantity": 2.5,
                  "filledQuantity": 2.5, "limitPrice": 48.1,
                  "createdAt": "2026-11-19T08:30:05Z"},
        "fill": {"id": order_id * 10, "price": 48.0, "quantity": 2.5,
                 "filledAt": "2026-11-19T09:01:00Z",
                 "walletImpact": {"currency": "GBP", "netValue": 120.6, "fxRate": 1.0,
                                  "taxes": [{"name": "STAMP_DUTY", "quantity": 0.6}]}},
    }
