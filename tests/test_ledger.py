from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from conftest import item, write_report
from t2r2.config import load_settings
from t2r2.ingest import IngestResult, ingest_history, ingest_runs
from t2r2.ledger import Ledger


class Pages:
    def __init__(self, *pages: list[dict[str, Any]]) -> None:
        self.pages = list(pages)
        self.served = 0

    def history_pages(self) -> Any:
        for page in self.pages:
            self.served += 1
            yield page


def _setup(tmp_path: Path) -> tuple[Ledger, Any]:
    settings = load_settings({"T2R2_APPS_DIR": str(tmp_path / "apps"),
                              "T2R2_LEDGER_DB": str(tmp_path / "ledger.db")}, need_key=False)
    return Ledger(settings.ledger_db), settings


def test_attributes_every_source(tmp_path: Path) -> None:
    ledger, settings = _setup(tmp_path)
    write_report(tmp_path / "apps", "t2-d2", "a.json", {"trades": [{"order_id": 1}]})
    result = IngestResult()
    ingest_runs(ledger, settings, result)
    ingest_history(ledger, Pages([
        item(1),                                   # named by t2-d2's run report
        item(2, side="SELL"),                      # API sell, no report: t2-k2, inferred
        item(3, origin="IOS"),                     # placed in the app
        item(4, origin="AUTOINVEST"),              # a pie
    ]), result)

    assert ledger.attribute() == {"automatic": 1, "manual": 1, "t2-d2": 1, "t2-k2": 1}
    with ledger.connect() as conn:
        rows = dict((r[0], r[1:]) for r in conn.execute(
            "SELECT order_id, source, source_inferred, run_id FROM orders"))
    assert rows[1] == ("t2-d2", 0, "t2-d2/a.json")
    assert rows[2] == ("t2-k2", 1, None)
    assert rows[3] == ("manual", 0, None)


def test_reingesting_never_duplicates(tmp_path: Path) -> None:
    ledger, settings = _setup(tmp_path)
    for _ in range(2):
        ingest_runs(ledger, settings, IngestResult())
        ingest_history(ledger, Pages([item(1), item(2)]), IngestResult(), full=True)
    with ledger.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM orders").fetchone() == (2,)


def test_stops_once_a_page_holds_nothing_new(tmp_path: Path) -> None:
    ledger, _ = _setup(tmp_path)
    ingest_history(ledger, Pages([item(5), item(4)], [item(3)]), IngestResult())

    pages = Pages([item(6), item(5)], [item(4), item(3)], [item(2)])
    result = IngestResult()
    ingest_history(ledger, pages, result)

    assert pages.served == 2  # the second page was all known and final
    assert result.orders == 4


def test_pending_orders_are_read_again(tmp_path: Path) -> None:
    ledger, _ = _setup(tmp_path)
    ingest_history(ledger, Pages([item(5, status="NEW")]), IngestResult())
    pages = Pages([item(5)], [item(4)])
    ingest_history(ledger, pages, IngestResult())
    assert pages.served == 2
    with ledger.connect() as conn:
        assert conn.execute("SELECT status FROM orders WHERE order_id = 5").fetchone() == (
            "FILLED",)


def test_late_run_report_corrects_a_guess(tmp_path: Path) -> None:
    ledger, settings = _setup(tmp_path)
    ingest_history(ledger, Pages([item(8)]), IngestResult())
    ledger.attribute()
    write_report(tmp_path / "apps", "t2-d2", "late.json", {"trades": [{"order_id": 8}]})
    ingest_runs(ledger, settings, IngestResult())
    ledger.attribute()
    with ledger.connect() as conn:
        assert conn.execute(
            "SELECT source, source_inferred FROM orders WHERE order_id = 8").fetchone() == (
            "t2-d2", 0)


def test_export_leaves_out_raw_payloads(tmp_path: Path) -> None:
    ledger, _ = _setup(tmp_path)
    ingest_history(ledger, Pages([item(1)]), IngestResult())
    ledger.attribute()
    paths = ledger.export_csv(tmp_path / "out")
    assert [p.name for p in paths] == ["orders.csv", "runs.csv", "run_orders.csv"]
    with paths[0].open() as handle:
        rows = list(csv.DictReader(handle))
    assert "raw" not in rows[0] and rows[0]["source"] == "t2-d2"
