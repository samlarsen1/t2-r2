"""Settings loaded from environment variables (populated from ``.env`` by the CLI)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

LIVE_BASE_URL = "https://live.trading212.com"
DEMO_BASE_URL = "https://demo.trading212.com"
ALLOWED_BASE_URLS = frozenset({LIVE_BASE_URL, DEMO_BASE_URL})

# Droids whose run reports name the orders they placed
TRADING_DROIDS = ("t2-d2", "t2-k2")


class ConfigError(Exception):
    """Required settings are missing or invalid."""


@dataclass(frozen=True)
class Settings:
    """Runtime settings.

    Attributes:
        api_key: Trading212 API key (read-only permissions are enough).
        api_secret: Trading212 API secret.
        base_url: Trading212 live or demo base URL.
        ledger_db: The SQLite ledger file.
        apps_dir: Folder holding the droids' app directories side by side.
        history_page_seconds: Pause between order history pages (Trading212 allows 6 a minute).
    """

    api_key: str = field(repr=False)
    api_secret: str = field(repr=False)
    base_url: str = LIVE_BASE_URL
    ledger_db: Path = Path("var/ledger.db")
    apps_dir: Path = Path("..")
    history_page_seconds: float = 11.0

    def runs_dir(self, droid: str) -> Path:
        """Where ``droid`` writes its run reports."""
        return self.apps_dir / droid / "var" / "runs"


def load_settings(env: Mapping[str, str], *, need_key: bool = True) -> Settings:
    """Build settings from an environment mapping.

    Args:
        env: Environment variables, usually ``os.environ``.
        need_key: False for commands that never call Trading212.

    Raises:
        ConfigError: If credentials are missing or the base URL isn't a Trading212 host.
    """
    missing = [name for name in ("T212_API_KEY", "T212_API_SECRET") if not env.get(name)]
    if missing and need_key:
        raise ConfigError(f"Missing required environment variables: {', '.join(missing)}")

    base_url = env.get("T212_BASE_URL", LIVE_BASE_URL).rstrip("/")
    # Credentials are sent to this host, so only allow Trading212's own endpoints.
    if base_url not in ALLOWED_BASE_URLS:
        raise ConfigError(f"T212_BASE_URL must be one of: {', '.join(sorted(ALLOWED_BASE_URLS))}")

    try:
        page_seconds = float(env.get("T2R2_HISTORY_PAGE_SECONDS") or 11.0)
    except ValueError as exc:
        raise ConfigError("T2R2_HISTORY_PAGE_SECONDS must be a number") from exc

    return Settings(
        api_key=env.get("T212_API_KEY", ""),
        api_secret=env.get("T212_API_SECRET", ""),
        base_url=base_url,
        ledger_db=Path(env.get("T2R2_LEDGER_DB") or "var/ledger.db"),
        apps_dir=Path(env.get("T2R2_APPS_DIR") or ".."),
        history_page_seconds=max(0.0, page_seconds),
    )
