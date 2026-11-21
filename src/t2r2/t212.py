"""Read-only Trading212 client: order history only.

It can only send GET requests: there is no method that places, changes or cancels anything.
GETs retry timeouts, network errors, 429 and 5xx, waiting at least as long as the rate-limit
headers ask.
"""

from __future__ import annotations

import base64
import logging
import time
from collections.abc import Callable, Iterator
from types import TracebackType
from typing import Any

import httpx

from .config import LIVE_BASE_URL

logger = logging.getLogger(__name__)

HISTORY_ORDERS_PATH = "/api/v0/equity/history/orders"
PAGE_LIMIT = 50  # the most Trading212 returns per page
MAX_WAIT_SECONDS = 120.0
RATE_LIMIT_MARGIN = 1.0


class Trading212Error(Exception):
    """A non-retryable or exhausted Trading212 API failure."""


def _retry_wait(response: httpx.Response, now: float) -> float | None:
    """Seconds to wait before retrying, from ``Retry-After`` or ``x-ratelimit-reset``."""
    for header, relative in (("Retry-After", True), ("x-ratelimit-reset", False)):
        value = response.headers.get(header)
        if value is None:
            continue
        try:
            seconds = float(value) if relative else float(value) - now
        except ValueError:
            continue
        return max(0.0, seconds)
    return None


class Trading212Reader:
    """GET-only Trading212 client. Use as a context manager.

    Args:
        api_key: Trading212 API key.
        api_secret: Trading212 API secret.
        base_url: Trading212 live or demo base URL.
        page_seconds: Pause between history pages, to stay inside the endpoint's rate limit.
        max_attempts: Total attempts per request, including the first.
        sleep: Sleep function, injectable for tests.
        transport: Optional httpx transport, injectable for tests.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        base_url: str = LIVE_BASE_URL,
        page_seconds: float = 11.0,
        max_attempts: int = 4,
        sleep: Callable[[float], None] = time.sleep,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        encoded = base64.b64encode(f"{api_key}:{api_secret}".encode()).decode()
        self._client = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Basic {encoded}", "Accept": "application/json"},
            timeout=30.0,
            transport=transport,
        )
        self._page_seconds = page_seconds
        self._max_attempts = max(1, max_attempts)
        self._sleep = sleep

    def __enter__(self) -> Trading212Reader:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._client.close()

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        for attempt in range(1, self._max_attempts + 1):
            wait: float | None = None
            try:
                response = self._client.get(path, params=params)
            except httpx.TransportError as exc:  # includes timeouts
                reason = type(exc).__name__
            else:
                if response.status_code == 429:
                    reason, wait = "rate_limited", _retry_wait(response, time.time())
                elif response.status_code >= 500:
                    reason = f"server_error_{response.status_code}"
                elif not response.is_success:
                    # Error bodies are short codes; never include the request (it has the key)
                    raise Trading212Error(
                        f"GET {path} returned {response.status_code}: {response.text[:200]}"
                    )
                else:
                    try:
                        return response.json()
                    except ValueError as exc:
                        raise Trading212Error(f"GET {path} did not return JSON") from exc
            if attempt == self._max_attempts:
                raise Trading212Error(f"GET {path} failed: {reason} after {attempt} attempts")
            backoff = 2.0**attempt
            delay = backoff if wait is None else max(wait + RATE_LIMIT_MARGIN, backoff)
            delay = min(delay, MAX_WAIT_SECONDS)
            logger.warning("t212_retry path=%s reason=%s attempt=%d wait=%.1f",
                           path, reason, attempt, delay)
            self._sleep(delay)
        raise AssertionError("unreachable")  # pragma: no cover

    def history_pages(self) -> Iterator[list[dict[str, Any]]]:
        """Pages of historical orders, newest first; stop iterating to stop fetching."""
        params: dict[str, Any] | None = {"limit": PAGE_LIMIT}
        path = HISTORY_ORDERS_PATH
        first = True
        while True:
            if not first:
                self._sleep(self._page_seconds)
            first = False
            data = self._get(path, params)
            if not isinstance(data, dict) or not isinstance(data.get("items"), list):
                raise Trading212Error(f"unexpected order history response from {path}")
            yield [item for item in data["items"] if isinstance(item, dict)]
            next_path = data.get("nextPagePath")
            if not next_path or not isinstance(next_path, str):
                return
            if not next_path.startswith(HISTORY_ORDERS_PATH):
                raise Trading212Error("order history pointed outside the history endpoint")
            path, params = next_path, None
