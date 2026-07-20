# pyright: reportPrivateUsage=false
"""Perps market data stream manager tests against a local WebSocket server."""

import asyncio
import contextlib
import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import pytest
from websockets.asyncio.server import ServerConnection, serve

from polymarket._internal.streams.perps.market import PerpsMarketStreamManager
from polymarket._internal.streams.perps.market_protocol import derive_state
from polymarket.models.perps.events import PerpsBookEvent, PerpsTradeEvent
from polymarket.streams._specs import (
    PerpsBookSpec,
    PerpsCandlesSpec,
    PerpsStatisticsSpec,
    PerpsTickersSpec,
    PerpsTradesSpec,
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


def _is_ping(raw: str | bytes) -> bool:
    with contextlib.suppress(Exception):
        return json.loads(raw).get("id") == 0
    return False


def _book_frame(instrument_id: int) -> dict[str, Any]:
    return {
        "ch": f"book::{instrument_id}",
        "ts": 1751500000000,
        "sq": 1,
        "data": {"b": [["0.5", "10"]], "a": [["0.6", "4"]]},
    }


def _trade_frame(instrument_id: int, *, sequence: int = 2) -> dict[str, Any]:
    return {
        "ch": f"trades::{instrument_id}",
        "ts": 1751500000000,
        "sq": sequence,
        "data": [
            {
                "tid": 9,
                "iid": instrument_id,
                "side": "long",
                "p": "0.5",
                "qty": "1",
                "ts": 1751500000000,
            },
            {
                "tid": 10,
                "iid": instrument_id,
                "side": "short",
                "p": "0.6",
                "qty": "2",
                "ts": 1751500000001,
            },
        ],
    }


def test_batched_trade_frame_yields_one_event_and_routes_by_channel() -> None:
    async def handler(ws: ServerConnection) -> None:
        async for raw in ws:
            if _is_ping(raw):
                continue
            frame = json.loads(raw)
            if frame["req"] == "sub":
                await ws.send(json.dumps(_trade_frame(8)))
                await ws.send(json.dumps(_trade_frame(7)))

    async def run() -> None:
        async with ws_server(handler) as url:
            manager = PerpsMarketStreamManager(url=url)
            try:
                handle = await manager.subscribe(PerpsTradesSpec(instrument_id=7))
                async with handle:
                    event = await asyncio.wait_for(handle.__anext__(), timeout=5.0)
                    assert isinstance(event, PerpsTradeEvent)
                    assert event.channel == "trades::7"
                    assert event.sequence == 2
                    assert [trade.trade_id for trade in event.payload] == [9, 10]
                    with pytest.raises(TimeoutError):
                        await asyncio.wait_for(handle.__anext__(), timeout=0.1)
            finally:
                await manager.close()

    asyncio.run(asyncio.wait_for(run(), timeout=15.0))


def test_derive_state_collapses_all_subscriptions() -> None:
    state = derive_state(
        [
            PerpsTradesSpec(instrument_id=1),
            PerpsBookSpec(instrument_id=1),
            PerpsCandlesSpec(instrument_id=2, interval="1m"),
            PerpsTickersSpec(instrument_id=3),
            PerpsTickersSpec(),
            PerpsStatisticsSpec(instrument_id=4),
        ]
    )
    # An all-instruments tickers subscription subsumes per-instrument channels.
    assert state == frozenset(
        {"trades::1", "book::1", "klines::2::1m", "tickers::all", "statistics::4"}
    )


def test_subscribe_sends_channel_frame_and_routes_matching_events() -> None:
    received: list[dict[str, Any]] = []

    async def handler(ws: ServerConnection) -> None:
        async for raw in ws:
            if _is_ping(raw):
                continue
            frame = json.loads(raw)
            received.append(frame)
            if frame["req"] == "sub":
                await ws.send(json.dumps({"id": frame["id"], "data": {"status": "ok"}}))
                await ws.send(json.dumps(_book_frame(7)))
                await ws.send(json.dumps(_book_frame(8)))
                await ws.send(json.dumps(_trade_frame(7)))

    async def run() -> None:
        async with ws_server(handler) as url:
            manager = PerpsMarketStreamManager(url=url)
            try:
                handle = await manager.subscribe(PerpsBookSpec(instrument_id=7))
                async with handle:
                    event = await asyncio.wait_for(handle.__anext__(), timeout=5.0)
                    assert isinstance(event, PerpsBookEvent)
                    assert event.payload.instrument_id == 7
            finally:
                await manager.close()

    asyncio.run(asyncio.wait_for(run(), timeout=15.0))
    assert received[0]["req"] == "sub"
    assert received[0]["chs"] == ["book::7"]


def test_closing_one_handle_unsubscribes_only_its_channels() -> None:
    received: list[dict[str, Any]] = []

    async def handler(ws: ServerConnection) -> None:
        async for raw in ws:
            if _is_ping(raw):
                continue
            frame = json.loads(raw)
            received.append(frame)

    async def run() -> None:
        async with ws_server(handler) as url:
            manager = PerpsMarketStreamManager(url=url)
            try:
                book = await manager.subscribe(PerpsBookSpec(instrument_id=7))
                trades = await manager.subscribe(PerpsTradesSpec(instrument_id=7))
                await asyncio.sleep(0.05)
                await trades.close()
                await asyncio.sleep(0.05)
                await book.close()
            finally:
                await manager.close()

    asyncio.run(asyncio.wait_for(run(), timeout=15.0))
    assert received[0] == {"id": 1, "req": "sub", "chs": ["book::7"]}
    assert received[1] == {"id": 2, "req": "sub", "chs": ["trades::7"]}
    assert received[2] == {"id": 3, "req": "unsub", "chs": ["trades::7"]}


def test_overlapping_subscriptions_deduplicate_channels() -> None:
    received: list[dict[str, Any]] = []
    fanout: list[PerpsTradeEvent] = []

    async def handler(ws: ServerConnection) -> None:
        async for raw in ws:
            if _is_ping(raw):
                continue
            frame = json.loads(raw)
            received.append(frame)
            if frame["req"] == "sub":
                await ws.send(json.dumps(_trade_frame(7)))

    async def run() -> None:
        async with ws_server(handler) as url:
            manager = PerpsMarketStreamManager(url=url)
            try:
                first = await manager.subscribe(PerpsTradesSpec(instrument_id=7))
                second = await manager.subscribe(PerpsTradesSpec(instrument_id=7))
                async with first, second:
                    event_one = await asyncio.wait_for(first.__anext__(), timeout=5.0)
                    event_two = await asyncio.wait_for(second.__anext__(), timeout=5.0)
                    assert isinstance(event_one, PerpsTradeEvent)
                    assert isinstance(event_two, PerpsTradeEvent)
                    fanout.extend([event_one, event_two])
            finally:
                await manager.close()

    asyncio.run(asyncio.wait_for(run(), timeout=15.0))
    # The second overlapping subscription must not resend the channel.
    assert [frame for frame in received if frame["req"] == "sub"] == [
        {"id": 1, "req": "sub", "chs": ["trades::7"]}
    ]
    assert len(fanout) == 2


def test_reconnect_resubscribes_active_channels() -> None:
    connections = 0
    subscribe_frames: list[dict[str, Any]] = []
    resubscribed = asyncio.Event()

    async def handler(ws: ServerConnection) -> None:
        nonlocal connections
        connections += 1
        if connections == 1:
            raw = await ws.recv()
            subscribe_frames.append(json.loads(raw))
            await ws.close()
            return
        async for raw in ws:
            if _is_ping(raw):
                continue
            subscribe_frames.append(json.loads(raw))
            resubscribed.set()

    async def run() -> None:
        async with ws_server(handler) as url:
            manager = PerpsMarketStreamManager(url=url)
            try:
                handle = await manager.subscribe(PerpsBookSpec(instrument_id=7))
                async with handle:
                    await asyncio.wait_for(resubscribed.wait(), timeout=10.0)
            finally:
                await manager.close()

    asyncio.run(asyncio.wait_for(run(), timeout=20.0))
    assert connections == 2
    assert subscribe_frames[-1]["req"] == "sub"
    assert subscribe_frames[-1]["chs"] == ["book::7"]
