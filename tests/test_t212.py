from __future__ import annotations

import httpx
import pytest

from t2r2.t212 import HISTORY_ORDERS_PATH, Trading212Error, Trading212Reader


def reader(handler: httpx.MockTransport, sleeps: list[float]) -> Trading212Reader:
    return Trading212Reader("key", "secret", page_seconds=11.0, sleep=sleeps.append,
                            transport=handler)


def test_follows_pages_and_paces_them() -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if "cursor" in request.url.params:
            return httpx.Response(200, json={"items": [{"id": 1}], "nextPagePath": None})
        return httpx.Response(200, json={
            "items": [{"id": 2}], "nextPagePath": f"{HISTORY_ORDERS_PATH}?limit=50&cursor=99"})

    sleeps: list[float] = []
    with reader(httpx.MockTransport(handle), sleeps) as client:
        pages = list(client.history_pages())

    assert pages == [[{"id": 2}], [{"id": 1}]]
    assert sleeps == [11.0]
    assert all(r.method == "GET" for r in seen)
    assert seen[0].headers["Authorization"].startswith("Basic ")


def test_retries_rate_limits_with_the_server_wait() -> None:
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "30"})
        return httpx.Response(200, json={"items": []})

    sleeps: list[float] = []
    with reader(httpx.MockTransport(handle), sleeps) as client:
        assert list(client.history_pages()) == [[]]
    assert sleeps == [31.0]


def test_client_errors_are_not_retried() -> None:
    sleeps: list[float] = []
    transport = httpx.MockTransport(lambda r: httpx.Response(401, text="BadCredentials"))
    with reader(transport, sleeps) as client, pytest.raises(Trading212Error, match="401"):
        list(client.history_pages())
    assert sleeps == []


def test_refuses_a_next_page_outside_the_endpoint() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(
        200, json={"items": [], "nextPagePath": "/api/v0/equity/orders/market"}))
    with reader(transport, []) as client, pytest.raises(Trading212Error, match="outside"):
        list(client.history_pages())


def test_gives_up_after_repeated_server_errors() -> None:
    sleeps: list[float] = []
    with reader(httpx.MockTransport(lambda r: httpx.Response(503)), sleeps) as client:
        with pytest.raises(Trading212Error, match="after 4 attempts"):
            list(client.history_pages())
    assert len(sleeps) == 3
