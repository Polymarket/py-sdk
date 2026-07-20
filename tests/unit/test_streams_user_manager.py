import asyncio
import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import pytest
from websockets.asyncio.server import ServerConnection, serve

from polymarket._internal.streams.clob.user import ClobUserStreamManager
from polymarket.models import ApiKeyCreds
from polymarket.models.clob.user_events import UserOrderEvent

Handler = Callable[[ServerConnection], Awaitable[None]]


@asynccontextmanager
async def ws_server(handler: Handler) -> AsyncGenerator[str, None]:
    server = await serve(handler, host="127.0.0.1", port=0)
    try:
        port = next(iter(server.sockets)).getsockname()[1]
        yield f"ws://127.0.0.1:{port}"
    finally:
        server.close()
        await server.wait_closed()


_CREDS = ApiKeyCreds(key="test-key", secret="test-secret", passphrase="test-pass")


async def _resolve() -> ApiKeyCreds:
    return _CREDS


def _order_frame(market: str) -> dict[str, Any]:
    return {
        "event_type": "order",
        "id": "ord-1",
        "owner": "0xowner",
        "market": market,
        "asset_id": "tid",
        "side": "BUY",
        "original_size": "1",
        "size_matched": "0",
        "price": "0.5",
        "type": "PLACEMENT",
        "timestamp": "1710000000000",
    }


def test_initial_frame_contains_auth_and_markets() -> None:
    received: list[dict[str, Any]] = []

    async def handler(ws: ServerConnection) -> None:
        async for raw in ws:
            if raw == "PING":
                continue
            received.append(json.loads(raw))

    async def run() -> None:
        async with ws_server(handler) as url:
            mgr = ClobUserStreamManager(url=url, resolve_credentials=_resolve)
            try:
                handle = await mgr.subscribe(markets=["m1"])
                await asyncio.sleep(0.1)
                await handle.close()
            finally:
                await mgr.close()

    asyncio.run(run())
    assert received[0] == {
        "type": "user",
        "auth": {"apiKey": "test-key", "secret": "test-secret", "passphrase": "test-pass"},
        "markets": ["m1"],
    }


def test_initial_frame_for_all_markets_omits_market_filter() -> None:
    received: list[dict[str, Any]] = []

    async def handler(ws: ServerConnection) -> None:
        async for raw in ws:
            if raw == "PING":
                continue
            received.append(json.loads(raw))

    async def run() -> None:
        async with ws_server(handler) as url:
            mgr = ClobUserStreamManager(url=url, resolve_credentials=_resolve)
            try:
                handle = await mgr.subscribe()
                await asyncio.sleep(0.1)
                await handle.close()
            finally:
                await mgr.close()

    asyncio.run(run())
    assert "markets" not in received[0]


def test_credentials_resolved_fresh_per_connection() -> None:
    resolve_calls = 0

    async def counting_resolve() -> ApiKeyCreds:
        nonlocal resolve_calls
        resolve_calls += 1
        return _CREDS

    async def handler(ws: ServerConnection) -> None:
        async for _ in ws:
            pass

    async def run() -> None:
        async with ws_server(handler) as url:
            mgr = ClobUserStreamManager(url=url, resolve_credentials=counting_resolve)
            try:
                h1 = await mgr.subscribe(markets=["m1"])
                h2 = await mgr.subscribe(markets=["m2"])
                await asyncio.sleep(0.05)
                await h1.close()
                await h2.close()
            finally:
                await mgr.close()

    asyncio.run(run())
    assert resolve_calls == 1


def test_incremental_subscribe_for_added_market_omits_auth() -> None:
    received: list[dict[str, Any]] = []

    async def handler(ws: ServerConnection) -> None:
        async for raw in ws:
            if raw == "PING":
                continue
            received.append(json.loads(raw))

    async def run() -> None:
        async with ws_server(handler) as url:
            mgr = ClobUserStreamManager(url=url, resolve_credentials=_resolve)
            try:
                h1 = await mgr.subscribe(markets=["m1"])
                h2 = await mgr.subscribe(markets=["m2"])
                await asyncio.sleep(0.1)
                await h1.close()
                await h2.close()
            finally:
                await mgr.close()

    asyncio.run(run())
    assert received[0]["type"] == "user"
    assert received[1] == {"operation": "subscribe", "markets": ["m2"]}
    assert "auth" not in received[1]


def test_all_markets_promotion_unsubscribes_prior_narrows() -> None:
    received: list[dict[str, Any]] = []

    async def handler(ws: ServerConnection) -> None:
        async for raw in ws:
            if raw == "PING":
                continue
            received.append(json.loads(raw))

    async def run() -> None:
        async with ws_server(handler) as url:
            mgr = ClobUserStreamManager(url=url, resolve_credentials=_resolve)
            try:
                h_narrow = await mgr.subscribe(markets=["m1"])
                h_broad = await mgr.subscribe()
                await asyncio.sleep(0.1)
                await h_narrow.close()
                await h_broad.close()
            finally:
                await mgr.close()

    asyncio.run(run())
    assert received[0]["type"] == "user"
    assert received[0]["markets"] == ["m1"]
    assert received[1] == {"operation": "unsubscribe", "markets": ["m1"]}


def test_all_markets_demotion_resubscribes_remaining_narrow() -> None:
    received: list[dict[str, Any]] = []

    async def handler(ws: ServerConnection) -> None:
        async for raw in ws:
            if raw == "PING":
                continue
            received.append(json.loads(raw))

    async def run() -> None:
        async with ws_server(handler) as url:
            mgr = ClobUserStreamManager(url=url, resolve_credentials=_resolve)
            try:
                h_broad = await mgr.subscribe()
                h_narrow = await mgr.subscribe(markets=["m1"])
                await asyncio.sleep(0.05)
                await h_broad.close()
                await asyncio.sleep(0.05)
                await h_narrow.close()
            finally:
                await mgr.close()

    asyncio.run(run())
    assert received[0]["type"] == "user"
    assert "markets" not in received[0]
    assert {"operation": "subscribe", "markets": ["m1"]} in received


def test_event_filtered_by_market_per_subscriber() -> None:
    async def handler(ws: ServerConnection) -> None:
        await ws.recv()
        for _ in range(20):
            await ws.send(json.dumps(_order_frame("m1")))
            await ws.send(json.dumps(_order_frame("m2")))
            await asyncio.sleep(0.02)

    async def run() -> str:
        async with ws_server(handler) as url:
            mgr = ClobUserStreamManager(url=url, resolve_credentials=_resolve)
            try:
                handle = await mgr.subscribe(markets=["m1"])
                event = await asyncio.wait_for(handle.__aiter__().__anext__(), timeout=2.0)
                assert isinstance(event, UserOrderEvent)
                market = event.payload.market
                await handle.close()
                return market
            finally:
                await mgr.close()

    assert asyncio.run(run()) == "m1"


def test_malformed_event_dropped_and_counter_increments() -> None:
    async def handler(ws: ServerConnection) -> None:
        await ws.recv()
        await ws.send(json.dumps({"bogus": True}))
        await ws.send(json.dumps(_order_frame("m1")))
        async for _ in ws:
            pass

    async def run() -> int:
        async with ws_server(handler) as url:
            mgr = ClobUserStreamManager(url=url, resolve_credentials=_resolve)
            try:
                handle = await mgr.subscribe(markets=["m1"])
                event = await asyncio.wait_for(handle.__aiter__().__anext__(), timeout=2.0)
                assert isinstance(event, UserOrderEvent)
                await asyncio.sleep(0.05)
                dropped = mgr.dropped_events
                await handle.close()
                return dropped
            finally:
                await mgr.close()

    assert asyncio.run(run()) == 1


def test_reconnect_resolves_credentials_and_resends_initial_frame() -> None:
    connect_count = 0
    per_connection: list[list[dict[str, Any]]] = []

    async def handler(ws: ServerConnection) -> None:
        nonlocal connect_count
        connect_count += 1
        frames: list[dict[str, Any]] = []
        per_connection.append(frames)
        if connect_count == 1:
            raw = await ws.recv()
            if isinstance(raw, str) and raw != "PING":
                frames.append(json.loads(raw))
            await ws.close()
            return
        async for raw in ws:
            if raw == "PING":
                continue
            frames.append(json.loads(raw))

    async def run() -> None:
        async with ws_server(handler) as url:
            mgr = ClobUserStreamManager(url=url, resolve_credentials=_resolve)
            try:
                handle = await mgr.subscribe(markets=["m1"])
                await asyncio.sleep(1.5)
                await handle.close()
            finally:
                await mgr.close()

    asyncio.run(run())
    assert connect_count >= 2
    assert per_connection[0][0]["type"] == "user"
    assert per_connection[0][0]["markets"] == ["m1"]
    assert per_connection[1][0]["type"] == "user"
    assert per_connection[1][0]["markets"] == ["m1"]
    assert per_connection[1][0]["auth"]["apiKey"] == "test-key"


def test_last_handle_close_drops_socket() -> None:
    async def handler(ws: ServerConnection) -> None:
        async for _ in ws:
            pass

    async def run() -> bool:
        async with ws_server(handler) as url:
            mgr = ClobUserStreamManager(url=url, resolve_credentials=_resolve)
            try:
                handle = await mgr.subscribe(markets=["m1"])
                await asyncio.sleep(0.05)
                await handle.close()
                await asyncio.sleep(0.1)
                return mgr.is_open
            finally:
                await mgr.close()

    assert asyncio.run(run()) is False


def test_subscribe_after_close_raises() -> None:
    async def run() -> None:
        mgr = ClobUserStreamManager(url="ws://127.0.0.1:1", resolve_credentials=_resolve)
        await mgr.close()
        with pytest.raises(RuntimeError, match="closed"):
            await mgr.subscribe(markets=["m1"])

    asyncio.run(run())


def test_credential_failure_on_reconnect_reschedules_instead_of_hanging() -> None:
    connect_count = 0
    resolve_calls = 0

    async def resolve() -> ApiKeyCreds:
        nonlocal resolve_calls
        resolve_calls += 1
        if resolve_calls == 1:
            return _CREDS
        if resolve_calls == 2:
            raise RuntimeError("simulated credential lookup failure")
        return _CREDS

    async def handler(ws: ServerConnection) -> None:
        nonlocal connect_count
        connect_count += 1
        if connect_count == 1:
            await ws.recv()
            await ws.close()
            return
        async for _ in ws:
            pass

    async def run() -> int:
        async with ws_server(handler) as url:
            mgr = ClobUserStreamManager(url=url, resolve_credentials=resolve)
            try:
                handle = await mgr.subscribe(markets=["m1"])
                await asyncio.sleep(3.0)
                await handle.close()
            finally:
                await mgr.close()
        return resolve_calls

    final_calls = asyncio.run(run())
    assert final_calls >= 3, (
        "credential resolution should be re-attempted after a transient failure; "
        f"only got {final_calls} attempts"
    )
