# pyright: reportPrivateUsage=false
import asyncio
import dataclasses
from typing import Literal, assert_type

import httpx
import pytest

from polymarket import AsyncPublicClient, AsyncSecureClient, PublicClient, SecureClient
from polymarket.clients._transport import AsyncTransport, SyncTransport
from polymarket.models import Event, Market
from polymarket.pagination import AsyncPaginator, Paginator


def check_sync_types(client: PublicClient | SecureClient) -> None:
    assert_type(client.list_markets(closed="any", ids=42), Paginator[Market])
    assert_type(client.list_markets(closed="any", request_ids="request"), Paginator[Market])
    assert_type(client.list_markets(closed="any", onchain_event_ids="event"), Paginator[Market])
    assert_type(client.list_events(closed="any"), Paginator[Event])


def check_async_types(client: AsyncPublicClient | AsyncSecureClient) -> None:
    assert_type(client.list_markets(closed="any", slug="market"), AsyncPaginator[Market])
    assert_type(client.list_markets(closed="any", request_ids="request"), AsyncPaginator[Market])
    assert_type(
        client.list_markets(closed="any", onchain_event_ids="event"), AsyncPaginator[Market]
    )
    assert_type(client.list_events(closed="any"), AsyncPaginator[Event])


@pytest.mark.parametrize("selector", ["id", "request_ids", "onchain_event_ids"])
def test_closed_any_reaches_sync_and_async_keyset_requests(
    selector: Literal["id", "request_ids", "onchain_event_ids"],
) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        kind = "markets" if request.url.path == "/markets/keyset" else "events"
        return httpx.Response(200, json={kind: [], "next_cursor": None})

    with PublicClient() as client:
        client._ctx.gamma.close()
        client._ctx = dataclasses.replace(
            client._ctx,
            gamma=SyncTransport(
                base_url="https://example.test",
                client=httpx.Client(
                    base_url="https://example.test", transport=httpx.MockTransport(handler)
                ),
            ),
        )
        assert (
            client.list_markets(
                closed="any",
                ids=42 if selector == "id" else None,
                request_ids="request" if selector == "request_ids" else None,
                onchain_event_ids="event" if selector == "onchain_event_ids" else None,
            )
            .first_page()
            .items
            == ()
        )
        assert client.list_events(closed="any").first_page().items == ()

    async def run() -> None:
        async with AsyncPublicClient() as client:
            await client._ctx.gamma.close()
            client._ctx = dataclasses.replace(
                client._ctx,
                gamma=AsyncTransport(
                    base_url="https://example.test",
                    client=httpx.AsyncClient(
                        base_url="https://example.test", transport=httpx.MockTransport(handler)
                    ),
                ),
            )
            assert (
                await client.list_markets(
                    closed="any",
                    ids=42 if selector == "id" else None,
                    request_ids="request" if selector == "request_ids" else None,
                    onchain_event_ids="event" if selector == "onchain_event_ids" else None,
                ).first_page()
            ).items == ()
            assert (await client.list_events(closed="any").first_page()).items == ()

    asyncio.run(run())
    assert [request.url.path for request in captured] == [
        "/markets/keyset",
        "/events/keyset",
        "/markets/keyset",
        "/events/keyset",
    ]
    assert all(request.url.params["closed"] == "any" for request in captured)
    expected = {"id": "42", "request_ids": "request", "onchain_event_ids": "event"}[selector]
    assert captured[0].url.params[selector] == captured[2].url.params[selector] == expected
