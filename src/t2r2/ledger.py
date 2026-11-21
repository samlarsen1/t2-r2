"""The ledger: one SQLite file of runs, orders and fills, and who placed each order.

Every write is an upsert by a natural key (run id, Trading212 order id), so ingesting the same
run reports or history again never duplicates anything. Attribution is recomputed after every
ingest, so a run report that arrives late corrects an earlier guess.
"""

from __future__ import annotations

import csv
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path

from .history import AUTOMATIC_ORIGINS, OrderRow
from .runs import RunOrder, RunRow

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id     TEXT PRIMARY KEY,
    droid      TEXT NOT NULL,
    command    TEXT NOT NULL,
    started_at TEXT NOT NULL,
    status     TEXT NOT NULL,
    dry_run    INTEGER,
    summary    TEXT NOT NULL
);
-- Orders a droid's run report says it placed
CREATE TABLE IF NOT EXISTS run_orders (
    order_id INTEGER PRIMARY KEY,
    droid    TEXT NOT NULL,
    run_id   TEXT NOT NULL REFERENCES runs(run_id),
    ticker   TEXT,
    strategy TEXT,
    reason   TEXT
);
-- Every order in Trading212's history, with its fill
CREATE TABLE IF NOT EXISTS orders (
    order_id        INTEGER PRIMARY KEY,
    ticker          TEXT NOT NULL,
    side            TEXT,
    type            TEXT,
    status          TEXT,
    origin          TEXT,
    quantity        REAL,
    filled_quantity REAL,
    limit_price     REAL,
    fill_price      REAL,
    fill_value      REAL,
    fx_rate         REAL,
    taxes           REAL,
    currency        TEXT,
    created_at      TEXT,
    filled_at       TEXT,
    -- t2-d2 | t2-k2 | manual | automatic | unknown
    source          TEXT NOT NULL DEFAULT 'unknown',
    -- 1 when the source was guessed from the side, with no run report naming the order
    source_inferred INTEGER NOT NULL DEFAULT 0,
    run_id          TEXT,
    raw             TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS orders_ticker ON orders(ticker, filled_at);
CREATE INDEX IF NOT EXISTS orders_source ON orders(source, filled_at);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

ATTRIBUTE = f"""
UPDATE orders SET
    source = CASE
        WHEN origin = 'API'
            AND EXISTS (SELECT 1 FROM run_orders r WHERE r.order_id = orders.order_id)
            THEN (SELECT droid FROM run_orders r WHERE r.order_id = orders.order_id)
        WHEN origin = 'API' AND side = 'BUY' THEN 't2-d2'
        WHEN origin = 'API' AND side = 'SELL' THEN 't2-k2'
        WHEN origin IN ({", ".join(f"'{o}'" for o in sorted(AUTOMATIC_ORIGINS))}) THEN 'automatic'
        WHEN origin IS NULL THEN 'unknown'
        WHEN origin = 'API' THEN 'unknown'
        ELSE 'manual'
    END,
    source_inferred = CASE
        WHEN origin = 'API'
            AND NOT EXISTS (SELECT 1 FROM run_orders r WHERE r.order_id = orders.order_id)
            THEN 1
        ELSE 0
    END,
    run_id = (SELECT run_id FROM run_orders r WHERE r.order_id = orders.order_id)
"""  # nosec B608 - built from a constant set, not from input

EXPORT_TABLES = ("orders", "runs", "run_orders")


class Ledger:
    """The ledger file. Opens a connection per call, so it is safe to share between processes."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """A connection in one transaction, with the schema in place."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=30)) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.executescript(SCHEMA)
            conn.execute(
                "INSERT OR IGNORE INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),)
            )
            with conn:
                yield conn

    # ------------------------------------------------------------------ run reports

    def add_runs(self, runs: Iterable[tuple[RunRow, list[RunOrder]]]) -> tuple[int, int]:
        """Upsert runs and the orders they name. Returns (runs, orders) written."""
        run_count = order_count = 0
        with self.connect() as conn:
            for run, orders in runs:
                conn.execute(
                    "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(run_id) DO UPDATE"
                    " SET status = excluded.status, summary = excluded.summary",
                    (run.run_id, run.droid, run.command, run.started_at, run.status,
                     None if run.dry_run is None else int(run.dry_run), run.summary),
                )
                run_count += 1
                for order in orders:
                    conn.execute(
                        "INSERT OR REPLACE INTO run_orders VALUES (?, ?, ?, ?, ?, ?)",
                        (order.order_id, order.droid, order.run_id, order.ticker,
                         order.strategy, order.reason),
                    )
                    order_count += 1
        return run_count, order_count

    # ------------------------------------------------------------------ Trading212 history

    def known_final(self, order_ids: Iterable[int]) -> set[int]:
        """The ids among ``order_ids`` already stored with a final status."""
        ids = list(order_ids)
        if not ids:
            return set()
        placeholders = ", ".join("?" * len(ids))
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT order_id FROM orders WHERE order_id IN ({placeholders})"  # nosec B608
                " AND status IN ('FILLED', 'CANCELLED', 'REJECTED')",
                ids,
            ).fetchall()
        return {row[0] for row in rows}

    def add_orders(self, orders: Iterable[OrderRow]) -> int:
        """Upsert historical orders. Returns how many were written."""
        now = datetime.now(UTC).isoformat()
        count = 0
        with self.connect() as conn:
            for o in orders:
                conn.execute(
                    """
                    INSERT INTO orders (order_id, ticker, side, type, status, origin, quantity,
                        filled_quantity, limit_price, fill_price, fill_value, fx_rate, taxes,
                        currency, created_at, filled_at, raw, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(order_id) DO UPDATE SET
                        ticker = excluded.ticker, side = excluded.side, type = excluded.type,
                        status = excluded.status, origin = excluded.origin,
                        quantity = excluded.quantity, filled_quantity = excluded.filled_quantity,
                        limit_price = excluded.limit_price, fill_price = excluded.fill_price,
                        fill_value = excluded.fill_value, fx_rate = excluded.fx_rate,
                        taxes = excluded.taxes, currency = excluded.currency,
                        created_at = excluded.created_at, filled_at = excluded.filled_at,
                        raw = excluded.raw, updated_at = excluded.updated_at
                    """,
                    (o.order_id, o.ticker, o.side, o.type, o.status, o.origin, o.quantity,
                     o.filled_quantity, o.limit_price, o.fill_price, o.fill_value, o.fx_rate,
                     o.taxes, o.currency, o.created_at, o.filled_at, o.raw, now),
                )
                count += 1
        return count

    def attribute(self) -> dict[str, int]:
        """Recompute every order's source. Returns the number of orders per source."""
        with self.connect() as conn:
            conn.execute(ATTRIBUTE)
            rows = conn.execute(
                "SELECT source, COUNT(*) FROM orders GROUP BY source ORDER BY source"
            ).fetchall()
        return {source: count for source, count in rows}

    # ------------------------------------------------------------------ export

    def export_csv(self, folder: Path) -> list[Path]:
        """Write each table (without raw payloads) to ``folder/<table>.csv``."""
        folder.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        with self.connect() as conn:
            for table in EXPORT_TABLES:
                cursor = conn.execute(f"SELECT * FROM {table} ORDER BY 1")  # nosec B608
                columns = [d[0] for d in cursor.description if d[0] != "raw"]
                keep = [i for i, d in enumerate(cursor.description) if d[0] != "raw"]
                path = folder / f"{table}.csv"
                with path.open("w", newline="", encoding="utf-8") as handle:
                    writer = csv.writer(handle)
                    writer.writerow(columns)
                    for row in cursor:
                        writer.writerow([row[i] for i in keep])
                written.append(path)
        return written
