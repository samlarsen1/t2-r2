# T2-R2 — Trade Ledger

Records every order and fill in the Trading212 account in one local SQLite file, and who placed
each one: `t2-d2`, `t2-k2`, the operator, or an automatic investment such as a pie. It's the
record that performance measurement builds on.

Read-only: its Trading212 client can only send GET requests.

## Part of the T2 system

This repo is one of the T2 droids, coordinated from the `t2-hq` repo, which holds the system
architecture (`ARCHITECTURE.md`) and plan (`PLAN.md`, Part 8). All the T2 repos live under the
same GitHub owner as this one.

| Repo | Role |
|---|---|
| `t2-d2` | buys dips; places buy orders on its own timers |
| `t2-k2` | harvests gains from overbought holdings; places sell orders |
| `t2-bb8` | harvests the Trading212 instrument list; metadata only |
| `t2-3po` | advisory council; reviews theses, strategy and configuration; read-only |
| **t2-r2** (this repo) | trade ledger; records orders, fills and who placed them; read-only |
| `t2-hq` | hub: plan, architecture, and the orchestrator and Telegram interface |
| `t2-core` | shared library: the price store |

The trading droids don't depend on T2-R2: they keep writing their run reports, and trading
continues if the ledger is down. It runs on its own timer.

---

## How it works

```
t2-d2 / t2-k2 run reports ──┐
  (order ids they placed)   ├──► t2r2 ingest ──► var/ledger.db ──► t2r2 export (CSV)
Trading212 order history ───┘                     source of truth
  (GET, read-only key)
```

1. **Run reports.** Reads every report in `<apps>/t2-d2/var/runs` and `<apps>/t2-k2/var/runs`
   and records the Trading212 order id of each order a droid says it placed (with the session,
   strategy and reason). Dry runs are ignored.
2. **Order history.** Reads `GET /api/v0/equity/history/orders`, newest first, 50 orders a page,
   11 seconds apart (the endpoint allows 6 requests a minute). It stops at the first page whose
   orders are all already stored as filled, cancelled or rejected, so a normal run reads one or
   two pages. `--full` reads everything; the first run does that anyway.
3. **Attribution.** Every order gets a `source`, recomputed on each run so a late run report
   corrects an earlier guess:

   | Trading212 says it came from | Matching run report | `source` | `source_inferred` |
   |---|---|---|---|
   | `API` | yes | the droid that named it | 0 |
   | `API` | no, and it's a buy | `t2-d2` | 1 |
   | `API` | no, and it's a sell | `t2-k2` | 1 |
   | `AUTOINVEST`, `SYSTEM` | — | `automatic` | 0 |
   | anything else (app, website) | — | `manual` | 0 |

   Inferred sources cover orders placed before `t2-d2` recorded order ids (its 0.3.0).

Every write is an upsert by Trading212 order id or run id, so re-running, or replaying all
history with `--full`, never duplicates anything. The raw history item is kept with each order,
so fields can be re-parsed later without fetching again.

### Tables

| Table | Holds |
|---|---|
| `orders` | every order: ticker, side, type, status, origin, quantities, limit and fill price, fill value and taxes in the account currency, times, `source`, `source_inferred`, `run_id` |
| `runs` | one row per trading-droid run report |
| `run_orders` | the orders each run report names, with strategy and reason |

```bash
sqlite3 var/ledger.db "SELECT source, COUNT(*), ROUND(SUM(fill_value), 2) FROM orders
                       WHERE status = 'FILLED' GROUP BY source"
```

> **Field names.** Trading212 has returned two shapes of order history over time; both are
> parsed. If a column you expect is empty, the raw item in `orders.raw` shows what Trading212
> sent.

---

## Quick Start

### Prerequisites
- Python 3.12+
- [uv](https://github.com/astral-sh/uv)
- A Trading212 API key and secret with **read-only** permissions (order history). Never give it
  "Orders execute".

### Local Setup

```bash
uv sync
cp .env.example .env          # then fill in the key

uv run t2r2 ingest --no-t212  # run reports only, no Trading212 call
uv run t2r2 ingest            # run reports + order history (the first run reads all of it)
uv run t2r2 sources           # orders per source
uv run t2r2 export exports/   # orders.csv, runs.csv, run_orders.csv (no raw payloads)
```

### Run reports, exit codes and locks

T2-R2 follows the T2 droid contract (t2-hq `CONTRACT.md`) for `ingest`:

- **Run report** in `var/runs/` (or `$T2_RUNS_DIR`), with counts per source in `result`.
- **Exit codes:** `0` ok, `1` failed (Trading212 history failed; run reports are still stored),
  `2` configuration error, `3` skipped (a lock is held).
- **Locks:** its own run lock, and the shared Trading212 account lock around history calls.

### Schedule

`deploy/systemd/` has a daily timer at 23:15 Europe/London, after the US close, with
`Persistent=true`. Deploy it with t2-hq's `bin/t2-deploy deploy t2-r2`.

### Environment variables

| Variable | Description |
|---|---|
| `T212_API_KEY`, `T212_API_SECRET` | Trading212 key with read-only permissions |
| `T212_BASE_URL` | `https://live.trading212.com` (default) or `https://demo.trading212.com` |
| `T2R2_LEDGER_DB` | Optional. The ledger file (default `var/ledger.db`) |
| `T2R2_APPS_DIR` | Optional. Folder holding the droids' app directories (default `..`) |
| `T2R2_HISTORY_PAGE_SECONDS` | Optional. Pause between history pages (default 11) |
| `T2_RUNS_DIR`, `T2_LOCK_DIR`, `T2_T212_LOCK_TIMEOUT` | Droid contract settings |
| `LOG_LEVEL` | Default `INFO` |

## Development

```bash
.venv/bin/pre-commit install --install-hooks
.venv/bin/pre-commit run --all-files   # detect-secrets, ruff, bandit, semgrep, pip-audit, mypy --strict, pytest
```

## Planned

- Google Sheets sink (optional, one-way, append-only) with a `sync_state` table.
- Per-lot performance against a shadow benchmark, using `t2-core`'s price store.

## License

MIT
