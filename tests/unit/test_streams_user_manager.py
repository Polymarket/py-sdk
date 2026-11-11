import asyncio
import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import pytest
from _bearer import async_test_session
from websockets.asyncio.server import ServerConnection, serve

from polymarket._internal.auth_session import AsyncAuthSession
from polymarket._internal.streams.clob.user import ClobUserStreamManager
from polymarket.errors import RequestRejectedError, TransportError
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

    async def run() -> str:
        session = async_test_session()
        async with ws_server(handler) as url:
            mgr = ClobUserStreamManager(url=url, session=session)
            try:
                handle = await mgr.subscribe(markets=["m1"])
                await asyncio.sleep(0.1)
                await handle.close()
            finally:
                await mgr.close()
        return session.credentials.access_token

    access_token = asyncio.run(run())
    assert received[0] == {
        "type": "user",
        "auth": {"accessToken": access_token},
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
            mgr = ClobUserStreamManager(url=url, session=async_test_session())
            try:
                handle = await mgr.subscribe()
                await asyncio.sleep(0.1)
                await handle.close()
            finally:
                await mgr.close()

    asyncio.run(run())
    assert "markets" not in received[0]


def test_shared_connection_authenticates_once() -> None:
    received: list[dict[str, Any]] = []

    async def handler(ws: ServerConnection) -> None:
        async for raw in ws:
            if raw != "PING":
                received.append(json.loads(raw))

    async def run() -> None:
        async with ws_server(handler) as url:
            mgr = ClobUserStreamManager(url=url, session=async_test_session())
            try:
                h1 = await mgr.subscribe(markets=["m1"])
                h2 = await mgr.subscribe(markets=["m2"])
                await asyncio.sleep(0.05)
                await h1.close()
                await h2.close()
            finally:
                await mgr.close()

    asyncio.run(run())
    assert [frame for frame in received if "auth" in frame] == received[:1]


def test_renewed_token_is_sent_on_the_open_connection() -> None:
    received: list[dict[str, Any]] = []

    async def handler(ws: ServerConnection) -> None:
        async for raw in ws:
            if raw == "PING":
                continue
            frame = json.loads(raw)
            received.append(frame)
            if frame.get("type") == "auth":
                await ws.send(json.dumps({"type": "auth", "success": True}))

    async def run() -> tuple[str, str]:
        session = async_test_session()
        async with ws_server(handler) as url:
            mgr = ClobUserStreamManager(url=url, session=session)
            try:
                handle = await mgr.subscribe(markets=["m1"])
                first = session.credentials.access_token
                renewed = await session.refresh()
                await asyncio.sleep(0.2)
                await handle.close()
            finally:
                await mgr.close()
        return first, renewed.access_token

    first, renewed = asyncio.run(run())
    assert first != renewed
    assert received[0]["auth"] == {"accessToken": first}
    assert received[1] == {"type": "auth", "auth": {"accessToken": renewed}}


def test_policy_close_ends_subscriptions_as_rejected_authentication() -> None:
    async def handler(ws: ServerConnection) -> None:
        await ws.recv()
        await ws.close(code=1008, reason="invalid token")

    async def run() -> BaseException | None:
        async with ws_server(handler) as url:
            mgr = ClobUserStreamManager(url=url, session=async_test_session())
            try:
                handle = await mgr.subscribe(markets=["m1"])
                try:
                    async for _ in handle:
                        pass
                except RequestRejectedError as error:
                    return error
                return None
            finally:
                await mgr.close()

    error = asyncio.run(run())
    assert isinstance(error, RequestRejectedError)
    assert error.status == 401


def test_incremental_subscribe_for_added_market_omits_auth() -> None:
    received: list[dict[str, Any]] = []

    async def handler(ws: ServerConnection) -> None:
        async for raw in ws:
            if raw == "PING":
                continue
            received.append(json.loads(raw))

    async def run() -> None:
        async with ws_server(handler) as url:
            mgr = ClobUserStreamManager(url=url, session=async_test_session())
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
            mgr = ClobUserStreamManager(url=url, session=async_test_session())
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
            mgr = ClobUserStreamManager(url=url, session=async_test_session())
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
            mgr = ClobUserStreamManager(url=url, session=async_test_session())
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
            mgr = ClobUserStreamManager(url=url, session=async_test_session())
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


def test_reconnect_reauthenticates_and_resends_initial_frame() -> None:
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
            mgr = ClobUserStreamManager(url=url, session=async_test_session())
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
    assert set(per_connection[1][0]["auth"]) == {"accessToken"}


def test_last_handle_close_drops_socket() -> None:
    async def handler(ws: ServerConnection) -> None:
        async for _ in ws:
            pass

    async def run() -> bool:
        async with ws_server(handler) as url:
            mgr = ClobUserStreamManager(url=url, session=async_test_session())
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
        mgr = ClobUserStreamManager(url="ws://127.0.0.1:1", session=async_test_session())
        await mgr.close()
        with pytest.raises(RuntimeError, match="closed"):
            await mgr.subscribe(markets=["m1"])

    asyncio.run(run())


def test_renewal_failure_on_reconnect_reschedules_instead_of_hanging() -> None:
    connect_count = 0
    renew_calls = 0
    session: AsyncAuthSession | None = None

    async def renew(current: Any) -> Any:
        nonlocal renew_calls
        renew_calls += 1
        if renew_calls <= 3:
            raise TransportError("simulated renewal outage")
        assert session is not None
        fresh = async_test_session()
        return await fresh._refresh(fresh.credentials)  # pyright: ignore[reportPrivateUsage]

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
        nonlocal session
        # The token expires after the first connection, so every reconnect renews it.
        session = async_test_session(expires_in=1, renew=renew)
        async with ws_server(handler) as url:
            mgr = ClobUserStreamManager(url=url, session=session)
            try:
                handle = await mgr.subscribe(markets=["m1"])
                await asyncio.sleep(4.0)
                await handle.close()
            finally:
                await mgr.close()
        return connect_count

    assert asyncio.run(run()) >= 2
    assert renew_calls >= 4, "renewal should be re-attempted after a transient outage"
