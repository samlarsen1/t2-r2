from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import write_report
from t2r2 import cli


def test_ingest_without_trading212_writes_a_contract_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("T2R2_APPS_DIR", str(tmp_path / "apps"))
    monkeypatch.setenv("T2R2_LEDGER_DB", str(tmp_path / "ledger.db"))
    write_report(tmp_path / "apps", "t2-d2", "a.json", {"trades": [{"order_id": 1}]})

    assert cli.main(["ingest", "--no-t212"]) == 0

    [path] = (tmp_path / "own-runs").glob("*.json")
    report = json.loads(path.read_text())
    assert (report["droid"], report["status"]) == ("t2-r2", "ok")
    assert report["result"]["run_orders"] == 1


def test_ingest_without_a_key_is_a_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("T212_API_KEY", raising=False)
    monkeypatch.delenv("T212_API_SECRET", raising=False)
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    monkeypatch.setenv("T2R2_LEDGER_DB", str(tmp_path / "ledger.db"))
    assert cli.main(["ingest"]) == 2
    [path] = (tmp_path / "own-runs").glob("*.json")
    assert json.loads(path.read_text())["status"] == "config_error"
