# T2-R2

uv project (Python 3.12), `src/t2r2`: the trade ledger. Ingests the trading droids' run reports
and Trading212's order history into one SQLite file, and attributes every order to `t2-d2`,
`t2-k2`, `manual` or `automatic`.

## System context

Part of the T2 droid system. The hub repo is `../t2-hq`:
read its `ARCHITECTURE.md` and `PLAN.md` (Part 8) before changing how this repo interacts with
the others. Repos sit side by side in one development directory (`$T2_SRC`) and one apps
directory (`$T2_APPS`).

- `../t2-d2`: buys dips; places buy orders on its own timers
- `../t2-k2`: harvests gains from overbought holdings; places sell orders
- `../t2-bb8`: harvests the Trading212 instrument list; metadata only
- `../t2-3po`: advisory council; reviews theses, strategy and configuration; read-only
- `../t2-hq`: hub; plan, architecture, orchestrator and Telegram interface
- `../t2-core`: shared library; the price store

## Commands

```bash
.venv/bin/pytest                         # tests (tests/)
.venv/bin/pre-commit run --all-files     # detect-secrets, ruff, bandit, semgrep, pip-audit, mypy --strict, pytest
uv sync                                  # install/update deps (uv.lock)
uv run t2r2 ingest [--full] [--no-t212]  # always writes a run report (var/runs)
uv run t2r2 export DIR | sources
```

## Rules

- **Read-only.** `t212.py` sends GET requests only. Never add a method that places, changes or
  cancels an order, and never document a key with "Orders execute".
- **The droids never depend on the ledger.** It reads their run reports; it never writes to
  their folders or changes what they do.
- **Idempotent.** Every write is an upsert by a natural key; attribution is recomputed in SQL
  after each ingest. Keep the raw history item in `orders.raw`.
- **A sink never changes the ledger.** Sinks (CSV now, Google Sheets later) are one-way.
- **Follow the T2 droid contract** (t2-hq `CONTRACT.md`): run report, exit codes 0/1/2/3, the
  run lock and the shared `t212_lock()`. `t2contract.py` is vendored from t2-hq: never edit it
  here; change it in t2-hq and run `bin/t2-contract sync`.
- **Never log the API key or request headers.** Trading212 errors carry only the status and
  the short error body.
- **Never create, read, edit, copy or link `.env` files.** Only write `.env.example` with placeholders.
- **Keep the documents generic.** No personal names, machine names or home-directory paths.
- Tests mock Trading212 with `httpx.MockTransport` and never touch the network.
- Git: commit only on `feature/<name>`, `bug/<name>`, `task/<name>` or `hotfix/<name>` branches;
  never directly on `main`.
