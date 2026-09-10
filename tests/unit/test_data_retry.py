# pyright: reportPrivateUsage=false
import asyncio
import dataclasses

import httpx
import pytest

from polymarket import AsyncPublicClient, PublicClient
from polymarket._internal import retry
from polymarket.clients._transport import AsyncTransport, SyncTransport
from polymarket.errors import RateLimitError, RequestRejectedError


@pytest.mark.parametrize(
    "status,header,failures,attempts,delays",
    [
        (429, "2", 1, 2, [2]),
        (429, None, 1, 2, [1]),
        (429, "120", 1, 1, []),
        (429, "0", 4, 3, [0, 0]),
        (400, None, 1, 1, []),
    ],
)
@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("method", ["get_open_interests", "list_trades"])
def test_retry_at_dispatch_boundary(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    header: str | None,
    failures: int,
    attempts: int,
    delays: list[int],
    mode: str,
    method: str,
) -> None:
    calls = 0
    slept: list[float] = []
    monkeypatch.setattr(retry, "sleep", slept.append)

    async def record(delay: float) -> None:
        slept.append(delay)

    monkeypatch.setattr(retry, "async_sleep", record)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls <= failures:
            return httpx.Response(
                status,
                headers={} if header is None else {"Retry-After": header},
                json={"error": "test rejection"},
            )
        return httpx.Response(
            200, json={"data": [], "pagination": {"has_more": False, "next_cursor": None}}
        )

    def sync_run() -> None:
        with (
            PublicClient() as client,
            httpx.Client(
                base_url="https://example.test", transport=httpx.MockTransport(handler)
            ) as http,
        ):
            client._ctx.data.close()
            client._ctx = dataclasses.replace(
                client._ctx, data=SyncTransport(base_url="https://example.test", client=http)
            )
            if method == "list_trades":
                client.list_trades().first_page()
            else:
                client.get_open_interests()

    async def async_run() -> None:
        async with (
            AsyncPublicClient() as client,
            httpx.AsyncClient(
                base_url="https://example.test", transport=httpx.MockTransport(handler)
            ) as http,
        ):
            await client._ctx.data.close()
            client._ctx = dataclasses.replace(
                client._ctx, data=AsyncTransport(base_url="https://example.test", client=http)
            )
            if method == "list_trades":
                await client.list_trades().first_page()
            else:
                await client.get_open_interests()

    if failures >= attempts:
        with pytest.raises(RateLimitError if status == 429 else RequestRejectedError):
            sync_run() if mode == "sync" else asyncio.run(async_run())
    else:
        sync_run() if mode == "sync" else asyncio.run(async_run())
    assert calls == attempts
    assert slept == delays
