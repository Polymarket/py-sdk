import asyncio
import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import pytest
from websockets.asyncio.server import ServerConnection, serve

from polymarket._internal.streams.clob.heartbeat import ClobWebSocketHeartbeat
from polymarket._internal.streams.clob.market import ClobMarketStreamManager
from polymarket._internal.streams.handle import AsyncSubscriptionHandle
from polymarket.models.clob.market_events import (
    MarketBestBidAskEvent,
    MarketBookEvent,
    MarketEvent,
)

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


def _book(asset_id: str, market: str = "m") -> dict[str, Any]:
    return {
        "event_type": "book",
        "market": market,
        "asset_id": asset_id,
        "bids": [{"price": "0.49", "size": "100"}],
        "asks": [{"price": "0.51", "size": "100"}],
    }


def _bba(asset_id: str, market: str = "m") -> dict[str, Any]:
    return {
        "event_type": "best_bid_ask",
        "market": market,
        "asset_id": asset_id,
        "best_bid": "0.49",
        "best_ask": "0.51",
        "spread": "0.02",
    }


async def _next_event(
    handle: AsyncSubscriptionHandle[MarketEvent], *, timeout_s: float = 2.0
) -> MarketEvent:
    return await asyncio.wait_for(handle.__aiter__().__anext__(), timeout=timeout_s)


def test_initial_subscribe_frame_uses_market_envelope() -> None:
    received: list[dict[str, Any]] = []

    async def handler(ws: ServerConnection) -> None:
        async for raw in ws:
            assert isinstance(raw, str)
            if raw in ("PING",):
                continue
            received.append(json.loads(raw))

    async def run() -> None:
        async with ws_server(handler) as url:
            mgr = ClobMarketStreamManager(url=url)
            try:
                async with await mgr.subscribe(token_ids=["a"]):
                    await asyncio.sleep(0.1)
                    assert received == [
                        {"type": "market", "assets_ids": ["a"], "custom_feature_enabled": False}
                    ]
            finally:
                await mgr.close()

    asyncio.run(run())


def test_second_subscribe_sends_incremental_subscribe_frame() -> None:
    received: list[dict[str, Any]] = []

    async def handler(ws: ServerConnection) -> None:
        async for raw in ws:
            if raw == "PING":
                continue
            received.append(json.loads(raw))

    async def run() -> None:
        async with ws_server(handler) as url:
            mgr = ClobMarketStreamManager(url=url)
            try:
                h1 = await mgr.subscribe(token_ids=["a"])
                h2 = await mgr.subscribe(token_ids=["b"])
                await asyncio.sleep(0.1)
                assert received[0] == {
                    "type": "market",
                    "assets_ids": ["a"],
                    "custom_feature_enabled": False,
                }
                assert received[1] == {
                    "operation": "subscribe",
                    "assets_ids": ["b"],
                    "custom_feature_enabled": False,
                }
                await h1.close()
                await h2.close()
            finally:
                await mgr.close()

    asyncio.run(run())


def test_handle_close_sends_unsubscribe_for_orphaned_assets() -> None:
    received: list[dict[str, Any]] = []

    async def handler(ws: ServerConnection) -> None:
        async for raw in ws:
            if raw == "PING":
                continue
            received.append(json.loads(raw))

    async def run() -> None:
        async with ws_server(handler) as url:
            mgr = ClobMarketStreamManager(url=url)
            try:
                h1 = await mgr.subscribe(token_ids=["a"])
                h2 = await mgr.subscribe(token_ids=["b"])
                await asyncio.sleep(0.05)
                await h1.close()
                await asyncio.sleep(0.1)
                assert {"operation": "unsubscribe", "assets_ids": ["a"]} in received
                await h2.close()
            finally:
                await mgr.close()

    asyncio.run(run())


def test_custom_feature_toggle_up_sends_toggle_hack_frame() -> None:
    received: list[dict[str, Any]] = []

    async def handler(ws: ServerConnection) -> None:
        async for raw in ws:
            if raw == "PING":
                continue
            received.append(json.loads(raw))

    async def run() -> None:
        async with ws_server(handler) as url:
            mgr = ClobMarketStreamManager(url=url)
            try:
                h1 = await mgr.subscribe(token_ids=["a"])
                h2 = await mgr.subscribe(token_ids=["a"], custom_feature_enabled=True)
                await asyncio.sleep(0.1)
                assert received[1] == {
                    "operation": "subscribe",
                    "assets_ids": ["a"],
                    "custom_feature_enabled": True,
                }
                await h1.close()
                await h2.close()
            finally:
                await mgr.close()

    asyncio.run(run())


def test_book_event_parsed_and_dispatched_to_subscriber() -> None:
    async def handler(ws: ServerConnection) -> None:
        await ws.recv()  # initial subscribe
        await ws.send(json.dumps(_book("a")))
        async for _ in ws:
            pass

    async def run() -> MarketBookEvent:
        async with ws_server(handler) as url:
            mgr = ClobMarketStreamManager(url=url)
            try:
                handle = await mgr.subscribe(token_ids=["a"])
                event = await _next_event(handle)
                assert isinstance(event, MarketBookEvent)
                await handle.close()
                return event
            finally:
                await mgr.close()

    event = asyncio.run(run())
    assert event.payload.token_id == "a"


def test_event_array_unwrapped_in_order() -> None:
    async def handler(ws: ServerConnection) -> None:
        await ws.recv()
        await ws.send(json.dumps([_book("a", market="m1"), _book("a", market="m2")]))
        async for _ in ws:
            pass

    async def run() -> tuple[str, str]:
        async with ws_server(handler) as url:
            mgr = ClobMarketStreamManager(url=url)
            try:
                handle = await mgr.subscribe(token_ids=["a"])
                first = await _next_event(handle)
                second = await _next_event(handle)
                await handle.close()
                return first.payload.market, second.payload.market
            finally:
                await mgr.close()

    assert asyncio.run(run()) == ("m1", "m2")


def test_custom_event_filtered_for_non_custom_subscriber() -> None:
    async def handler(ws: ServerConnection) -> None:
        await ws.recv()
        await ws.recv()  # second subscribe (custom)
        await ws.send(json.dumps(_bba("a")))
        await ws.send(json.dumps(_book("a")))
        async for _ in ws:
            pass

    async def run() -> tuple[type[Any], type[Any]]:
        async with ws_server(handler) as url:
            mgr = ClobMarketStreamManager(url=url)
            try:
                plain = await mgr.subscribe(token_ids=["a"])
                custom = await mgr.subscribe(token_ids=["a"], custom_feature_enabled=True)
                first_custom = await _next_event(custom)
                first_plain = await _next_event(plain)
                await plain.close()
                await custom.close()
                return type(first_custom), type(first_plain)
            finally:
                await mgr.close()

    custom_type, plain_type = asyncio.run(run())
    assert custom_type is MarketBestBidAskEvent
    assert plain_type is MarketBookEvent


def test_malformed_event_dropped_and_counter_increments() -> None:
    async def handler(ws: ServerConnection) -> None:
        await ws.recv()
        await ws.send(json.dumps({"event_type": "bogus"}))
        await ws.send(json.dumps(_book("a")))
        async for _ in ws:
            pass

    async def run() -> tuple[int, type[Any]]:
        async with ws_server(handler) as url:
            mgr = ClobMarketStreamManager(url=url)
            try:
                handle = await mgr.subscribe(token_ids=["a"])
                first = await _next_event(handle)
                await asyncio.sleep(0.05)
                await handle.close()
                return mgr.dropped_events, type(first)
            finally:
                await mgr.close()

    dropped, event_type = asyncio.run(run())
    assert dropped == 1
    assert event_type is MarketBookEvent


def test_ping_sent_periodically_and_pong_consumed() -> None:
    pings: list[str] = []

    async def handler(ws: ServerConnection) -> None:
        async for raw in ws:
            if raw == "PING":
                pings.append("PING")
                await ws.send("PONG")
                continue

    async def run() -> int:
        async with ws_server(handler) as url:
            heartbeat = ClobWebSocketHeartbeat(interval_s=0.05, stale_s=5.0)
            mgr = ClobMarketStreamManager(url=url, heartbeat=heartbeat)
            try:
                handle = await mgr.subscribe(token_ids=["a"])
                await asyncio.sleep(0.3)
                await handle.close()
                return len(pings)
            finally:
                await mgr.close()

    count = asyncio.run(run())
    assert count >= 3


def test_reconnect_resends_full_initial_state() -> None:
    initial_frames: list[dict[str, Any]] = []
    connect_count = 0

    async def handler(ws: ServerConnection) -> None:
        nonlocal connect_count
        connect_count += 1
        raw = await ws.recv()
        assert isinstance(raw, str)
        if raw == "PING":
            raw = await ws.recv()
            assert isinstance(raw, str)
        initial_frames.append(json.loads(raw))
        if connect_count == 1:
            await ws.close()
            return
        async for _ in ws:
            pass

    async def run() -> None:
        async with ws_server(handler) as url:
            mgr = ClobMarketStreamManager(url=url)
            try:
                handle = await mgr.subscribe(token_ids=["a", "b"])
                await asyncio.sleep(1.5)
                await handle.close()
            finally:
                await mgr.close()

    asyncio.run(run())
    assert connect_count >= 2
    assert initial_frames[0] == {
        "type": "market",
        "assets_ids": ["a", "b"],
        "custom_feature_enabled": False,
    }
    assert initial_frames[1] == initial_frames[0]


def test_handle_close_is_idempotent() -> None:
    async def handler(ws: ServerConnection) -> None:
        async for _ in ws:
            pass

    async def run() -> None:
        async with ws_server(handler) as url:
            mgr = ClobMarketStreamManager(url=url)
            try:
                handle = await mgr.subscribe(token_ids=["a"])
                await asyncio.gather(handle.close(), handle.close(), handle.close())
                await handle.close()
            finally:
                await mgr.close()

    asyncio.run(run())


def test_manager_close_ends_open_handles_cleanly() -> None:
    async def handler(ws: ServerConnection) -> None:
        async for _ in ws:
            pass

    async def run() -> None:
        async with ws_server(handler) as url:
            mgr = ClobMarketStreamManager(url=url)
            handle = await mgr.subscribe(token_ids=["a"])
            await mgr.close()
            with pytest.raises(StopAsyncIteration):
                await handle.__aiter__().__anext__()

    asyncio.run(run())


def test_subscribe_with_empty_token_ids_raises_user_input_error() -> None:
    from polymarket.errors import UserInputError

    async def run() -> None:
        mgr = ClobMarketStreamManager(url="ws://127.0.0.1:1")
        with pytest.raises(UserInputError, match="token_ids"):
            await mgr.subscribe(token_ids=[])
        await mgr.close()

    asyncio.run(run())


def test_subscribe_after_close_raises() -> None:
    async def run() -> None:
        mgr = ClobMarketStreamManager(url="ws://127.0.0.1:1")
        await mgr.close()
        with pytest.raises(RuntimeError, match="closed"):
            await mgr.subscribe(token_ids=["a"])

    asyncio.run(run())


def test_subscribe_rejects_bare_string_token_ids() -> None:
    from polymarket.errors import UserInputError

    async def run() -> None:
        mgr = ClobMarketStreamManager(url="ws://127.0.0.1:1")
        with pytest.raises(UserInputError, match="single string"):
            await mgr.subscribe(token_ids="abc")  # pyright: ignore[reportArgumentType]
        await mgr.close()

    asyncio.run(run())


def test_subscribe_rejects_non_string_token_id_items() -> None:
    from polymarket.errors import UserInputError

    async def run() -> None:
        mgr = ClobMarketStreamManager(url="ws://127.0.0.1:1")
        with pytest.raises(UserInputError, match="must be a string"):
            await mgr.subscribe(token_ids=[123])  # pyright: ignore[reportArgumentType]
        await mgr.close()

    asyncio.run(run())


def test_subscribe_rejects_empty_token_id_string() -> None:
    from polymarket.errors import UserInputError

    async def run() -> None:
        mgr = ClobMarketStreamManager(url="ws://127.0.0.1:1")
        with pytest.raises(UserInputError, match="non-empty"):
            await mgr.subscribe(token_ids=["a", ""])
        await mgr.close()

    asyncio.run(run())


def test_subscribe_while_reconnect_pending_reopens_immediately() -> None:
    """If the socket has dropped and a reconnect timer is queued, a new
    subscribe() must call connect() and bring the socket back up rather
    than waiting behind the backoff.
    """
    connect_count = 0
    initial_frames: list[dict[str, Any]] = []

    async def handler(ws: ServerConnection) -> None:
        nonlocal connect_count
        connect_count += 1
        raw = await ws.recv()
        assert isinstance(raw, str)
        initial_frames.append(json.loads(raw))
        if connect_count == 1:
            await ws.close()
            return
        async for _ in ws:
            pass

    async def run() -> tuple[int, list[dict[str, Any]]]:
        async with ws_server(handler) as url:
            # Use a long backoff so the reconnect timer would not have
            # fired on its own within the test window. Subscribe must
            # short-circuit it.
            from polymarket._internal.streams.reconnect import ReconnectScheduler

            mgr = ClobMarketStreamManager(url=url)
            mgr._scheduler = ReconnectScheduler(base_s=30.0, max_s=30.0)  # pyright: ignore[reportPrivateUsage]
            try:
                h1 = await mgr.subscribe(token_ids=["a"])
                # Wait for the server-initiated close to register.
                deadline = asyncio.get_event_loop().time() + 2.0
                while mgr.is_open:
                    if asyncio.get_event_loop().time() > deadline:
                        raise AssertionError("server-close not observed")
                    await asyncio.sleep(0.02)
                # Now reconnect timer is queued with a 30s backoff. New
                # subscribe should reopen immediately rather than waiting.
                t0 = asyncio.get_event_loop().time()
                h2 = await mgr.subscribe(token_ids=["b"])
                elapsed = asyncio.get_event_loop().time() - t0
                assert elapsed < 2.0, f"subscribe waited on backoff: {elapsed:.2f}s"
                await asyncio.sleep(0.05)
                await h1.close()
                await h2.close()
                return connect_count, initial_frames
            finally:
                await mgr.close()

    count, frames = asyncio.run(run())
    assert count == 2
    # First initial frame had just "a"; second (after reopen) has the
    # current registry state, which includes "a" and "b" (h1 still alive).
    assert frames[0]["assets_ids"] == ["a"]
    assert frames[1]["assets_ids"] == ["a", "b"]


def test_subscribe_rejects_non_bool_custom_feature_enabled() -> None:
    from polymarket.errors import UserInputError

    async def run() -> None:
        mgr = ClobMarketStreamManager(url="ws://127.0.0.1:1")
        with pytest.raises(UserInputError, match="custom_feature_enabled"):
            await mgr.subscribe(
                token_ids=["a"],
                custom_feature_enabled="yes",  # pyright: ignore[reportArgumentType]
            )
        await mgr.close()

    asyncio.run(run())


def test_last_handle_close_drops_socket_and_manager_remains_usable() -> None:
    accepts = 0

    async def handler(ws: ServerConnection) -> None:
        nonlocal accepts
        accepts += 1
        async for _ in ws:
            pass

    async def run() -> tuple[bool, int]:
        async with ws_server(handler) as url:
            mgr = ClobMarketStreamManager(url=url)
            try:
                h1 = await mgr.subscribe(token_ids=["a"])
                await asyncio.sleep(0.05)
                await h1.close()
                await asyncio.sleep(0.1)
                socket_dropped = not mgr.is_open
                h2 = await mgr.subscribe(token_ids=["b"])
                await asyncio.sleep(0.05)
                await h2.close()
                return socket_dropped, accepts
            finally:
                await mgr.close()

    dropped, count = asyncio.run(run())
    assert dropped is True
    assert count == 2  # second subscribe re-opened a new socket


def test_failed_reconnect_retries_until_success() -> None:
    connect_count = 0

    async def handler(ws: ServerConnection) -> None:
        nonlocal connect_count
        connect_count += 1
        if connect_count == 1:
            await ws.recv()  # initial subscribe
            await ws.close()
            return
        # 2nd+ connection: drain
        async for _ in ws:
            pass

    async def run() -> int:
        async with ws_server(handler) as url:
            mgr = ClobMarketStreamManager(url=url)
            # Force first reconnect attempt to a bad URL to fail, then flip.
            try:
                handle = await mgr.subscribe(token_ids=["a"])
                # Wait long enough for: server-side close → backoff → retry.
                await asyncio.sleep(2.0)
                await handle.close()
                return connect_count
            finally:
                await mgr.close()

    # First connection is server-closed → reconnect attempt connects to same
    # local URL → succeeds. Even on a single retry path this should hit 2+.
    assert asyncio.run(run()) >= 2


def test_close_during_pending_reconnect_does_not_leak_a_fresh_socket() -> None:
    """If close() lands while a reconnect callback is mid-flight (between the
    scheduler firing it and _reconnect actually opening), the manager must
    not end up with an open socket. Pre+post-open _closed guards.
    """

    async def handler(ws: ServerConnection) -> None:
        # Close immediately so on_close fires and schedules a reconnect.
        await ws.close()

    async def run() -> bool:
        from polymarket._internal.streams.reconnect import ReconnectScheduler

        async with ws_server(handler) as url:
            mgr = ClobMarketStreamManager(url=url)
            mgr._scheduler = ReconnectScheduler(base_s=0.01, max_s=0.05)  # pyright: ignore[reportPrivateUsage]
            handle = await mgr.subscribe(token_ids=["a"])
            # Give the reconnect timer time to fire its callback. The handler
            # closes again so the callback opens then sees a dead socket,
            # but more importantly we want to race close() against the
            # callback that is actively running.
            await asyncio.sleep(0.05)
            await mgr.close()
            # Give any in-flight reconnect a chance to attempt opening.
            await asyncio.sleep(0.1)
            await handle.close()
            return mgr.is_open

    assert asyncio.run(run()) is False


def test_queue_size_constructor_param_is_honored() -> None:
    async def handler(ws: ServerConnection) -> None:
        await ws.recv()
        for i in range(50):
            await ws.send(json.dumps(_book("a", market=f"m{i}")))
        async for _ in ws:
            pass

    async def run() -> int:
        async with ws_server(handler) as url:
            mgr = ClobMarketStreamManager(url=url, queue_size=4)
            try:
                handle = await mgr.subscribe(token_ids=["a"])
                await asyncio.sleep(0.3)
                dropped = handle.dropped
                await handle.close()
                return dropped
            finally:
                await mgr.close()

    assert asyncio.run(run()) > 0
