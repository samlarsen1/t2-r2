from pathlib import Path

from conftest import write_report
from t2r2.runs import read_runs


def test_reads_d2_and_k2_orders(tmp_path: Path) -> None:
    write_report(tmp_path, "t2-d2", "a.json", {"trades": [
        {"ticker": "RIO", "t212_ticker": "RIOl_EQ", "strategy": "mild", "reason": "dip",
         "order_id": 11},
        {"ticker": "NG.", "order_id": None},  # placed before order ids were recorded
    ]})
    write_report(tmp_path, "t2-k2", "b.json", {"decisions": [
        {"ticker": "NVDA_US_EQ", "reason": "overbought", "order": {"id": 22}},
        {"ticker": "AMD_US_EQ", "reason": "held"},
    ]})

    [(d2_run, d2_orders)] = read_runs("t2-d2", tmp_path / "t2-d2" / "var" / "runs")
    [(_, k2_orders)] = read_runs("t2-k2", tmp_path / "t2-k2" / "var" / "runs")

    assert d2_run.run_id == "t2-d2/a.json"
    assert [(o.order_id, o.ticker, o.strategy) for o in d2_orders] == [(11, "RIOl_EQ", "mild")]
    assert [(o.order_id, o.droid, o.strategy) for o in k2_orders] == [(22, "t2-k2", "harvest")]


def test_dry_runs_name_no_orders(tmp_path: Path) -> None:
    write_report(tmp_path, "t2-d2", "a.json", {"trades": [{"order_id": 11}]}, dry_run=True)
    [(run, orders)] = read_runs("t2-d2", tmp_path / "t2-d2" / "var" / "runs")
    assert run.dry_run is True and orders == []


def test_skips_unreadable_and_foreign_reports(tmp_path: Path) -> None:
    runs = tmp_path / "t2-d2" / "var" / "runs"
    runs.mkdir(parents=True)
    (runs / "broken.json").write_text("{not json")
    write_report(tmp_path, "t2-d2", "other.json", {})
    (runs / "other.json").write_text((runs / "other.json").read_text().replace("t2-d2", "t2-k2"))
    assert list(read_runs("t2-d2", runs)) == []
    assert list(read_runs("t2-d2", tmp_path / "missing")) == []
