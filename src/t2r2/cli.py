"""``t2r2``: the trade ledger droid.

    t2r2 ingest [--full] [--no-t212]   run reports + Trading212 order history -> ledger
    t2r2 export DIR                    each ledger table as CSV
    t2r2 sources                       orders per source (no Trading212 call)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from . import __version__
from .config import ConfigError, Settings, load_settings
from .ingest import IngestResult, ingest_history, ingest_runs
from .ledger import Ledger
from .t2contract import Exit, RunReport, Skipped, run_lock, t212_lock
from .t212 import Trading212Error, Trading212Reader

DROID = "t2-r2"
logger = logging.getLogger("t2r2")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="t2r2", description="T2 trade ledger")
    sub = parser.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser("ingest", help="fill the ledger")
    ingest.add_argument("--full", action="store_true",
                        help="read all of Trading212's order history, not just what's new")
    ingest.add_argument("--no-t212", action="store_true",
                        help="read run reports only; don't call Trading212")
    ingest.add_argument("--report", type=Path, help="write the run report here")
    export = sub.add_parser("export", help="write each table to CSV")
    export.add_argument("folder", type=Path)
    sub.add_parser("sources", help="orders per source")
    return parser


def _ingest(args: argparse.Namespace, settings: Settings, report: RunReport) -> Exit:
    ledger = Ledger(settings.ledger_db)
    result = IngestResult()
    try:
        with run_lock(DROID):
            ingest_runs(ledger, settings, result)
            if not args.no_t212:
                with t212_lock(), Trading212Reader(
                    settings.api_key, settings.api_secret, settings.base_url,
                    page_seconds=settings.history_page_seconds,
                ) as reader:
                    ingest_history(ledger, reader, result, full=args.full)
            result.by_source = ledger.attribute()
    except Skipped as exc:
        return report.finish(Exit.SKIPPED, exc.reason)
    except Trading212Error as exc:
        result.by_source = ledger.attribute()
        return report.finish(Exit.FAILED, "Trading212 history failed", result.to_dict(),
                             [str(exc)])
    print(result.summary())
    return report.finish(Exit.OK, result.summary(), result.to_dict())


def main(argv: list[str] | None = None) -> int:
    """Run a command; exit codes follow the droid contract (0 ok, 1 failed, 2 config, 3 skip)."""
    load_dotenv()
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper(),
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    args = _parser().parse_args(argv)

    if args.command != "ingest":
        try:
            settings = load_settings(os.environ, need_key=False)
        except ConfigError as exc:
            print(exc, file=sys.stderr)
            return int(Exit.CONFIG)
        ledger = Ledger(settings.ledger_db)
        if args.command == "export":
            for path in ledger.export_csv(args.folder):
                print(path)
        else:
            for source, count in ledger.attribute().items():
                print(f"{source:<10}{count:>6}")
        return int(Exit.OK)

    report = RunReport(droid=DROID, version=__version__, command="ingest", dry_run=None)
    try:
        try:
            settings = load_settings(os.environ, need_key=not args.no_t212)
        except ConfigError as exc:
            code = report.finish(Exit.CONFIG, "configuration error", errors=[str(exc)])
        else:
            code = _ingest(args, settings, report)
    except Exception as exc:
        report.finish(Exit.FAILED, f"crashed: {type(exc).__name__}", errors=[type(exc).__name__])
        report.write(args.report)
        raise
    report.write(args.report)
    return int(code)


if __name__ == "__main__":
    sys.exit(main())
