# pyright: reportPrivateUsage=false
"""Perps session behavior against a local WebSocket server."""

import asyncio
import contextlib
import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest
from websockets.asyncio.server import ServerConnection, serve

from polymarket._internal.perps_session import PerpsSession
from polymarket.clients._transport import AsyncTransport
from polymarket.errors import (
    AutoCancelDailyLimitError,
    RequestRejectedError,
    TransportError,
    UserInputError,
)
from polymarket.models.perps.credentials import PerpsCredentials
from polymarket.models.perps.events import (
    PerpsFillEvent,
    PerpsNotificationEvent,
    PerpsOrderEvent,
    PerpsResyncEvent,
)

Handler = Callable[[ServerConnection], Awaitable[None]]

_PROXY_PRIVATE_KEY = "0x0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
_PROXY_ADDRESS = "0x14791697260E4c9A71f18484C9f997B308e59325"

_CREDENTIALS = PerpsCredentials(
    proxy=_PROXY_ADDRESS,
    private_key=_PROXY_PRIVATE_KEY,
    secret="session-secret",
    expires_at=datetime(2030, 1, 1, tzinfo=UTC),
)


@asynccontextmanager
async def ws_server(handler: Handler) -> AsyncGenerator[str, None]:
    server = await serve(handler, host="127.0.0.1", port=0)
    try:
        port = next(iter(server.sockets)).getsockname()[1]
        yield f"ws://127.0.0.1:{port}"
    finally:
        server.close()
        await server.wait_closed()


def _is_ping(message: dict[str, Any]) -> bool:
    return message.get("id") == 0


async def _handshake(ws: ServerConnection) -> list[dict[str, Any]]:
    """Serve the auth + subscribe handshake and return the received frames."""
    frames: list[dict[str, Any]] = []
    while len(frames) < 2:
        message = json.loads(await ws.recv())
        if _is_ping(message):
            continue
        frames.append(message)
        await ws.send(json.dumps({"id": message["id"], "data": {"status": "ok"}}))
    return frames


def _order_update(
    order_id: int, *, sequence: int = 1, reduce_only: bool | None = None
) -> dict[str, Any]:
    update: dict[str, Any] = {
        "ch": "orders",
        "ts": 1751500000000,
        "sq": sequence,
        "data": {
            "oid": order_id,
            "iid": 1,
            "buy": True,
            "p": "0.5",
            "qty": "10",
            "tif": "gtc",
            "po": False,
            "ro": reduce_only or False,
            "status": "open",
            "rest": "10",
            "fill": "0",
            "cts": 1751500000000,
            "uts": 1751500000001,
        },
    }
    return update


def _fills_update(*, sequence: int = 6) -> dict[str, Any]:
    return {
        "ch": "fills",
        "ts": 1751500000002,
        "sq": sequence,
        "data": [
            {
                "tid": 9,
                "oid": 77,
                "iid": 1,
                "side": "long",
                "p": "0.5",
                "qty": "1",
                "taker": True,
                "fee": "0.01",
                "fea": "USDC",
                "psz": "0",
                "pep": "0",
                "pnl": "0",
                "liq": False,
                "ts": 1751500000000,
            },
            {
                "tid": 10,
                "oid": 78,
                "iid": 1,
                "side": "short",
                "p": "0.6",
                "qty": "2",
                "taker": False,
                "fee": "0.02",
                "fea": "USDC",
                "psz": "1",
                "pep": "0.5",
                "pnl": "0.2",
                "liq": False,
                "ts": 1751500000001,
            },
        ],
    }


@asynccontextmanager
async def _open_session(url: str) -> AsyncGenerator[PerpsSession, None]:
    session = PerpsSession(
        chain_id=137,
        credentials=_CREDENTIALS,
        rest_url="http://127.0.0.1:9",  # unused by these tests
        ws_url=url,
    )
    try:
        await session.open()
        yield session
    finally:
        await session.close()


def test_session_authenticates_and_subscribes_all_channels() -> None:
    frames: list[dict[str, Any]] = []

    async def handler(ws: ServerConnection) -> None:
        frames.extend(await _handshake(ws))
        with contextlib.suppress(Exception):
            async for _ in ws:
                pass

    async def run() -> None:
        async with ws_server(handler) as url, _open_session(url):
            pass

    asyncio.run(asyncio.wait_for(run(), timeout=10.0))
    assert frames[0]["req"] == "post"
    assert frames[0]["op"] == {
        "type": "auth",
        "args": {"proxy": _PROXY_ADDRESS, "secret": "session-secret"},
    }
    assert frames[1]["req"] == "sub"
    assert frames[1]["chs"] == [
        "balances",
        "portfolio",
        "orders",
        "fills",
        "funding",
        "deposits",
        "withdrawals",
        "notifications",
        "tpsl",
    ]


def test_auth_rejection_surfaces_request_rejected_error() -> None:
    async def handler(ws: ServerConnection) -> None:
        message = json.loads(await ws.recv())
        await ws.send(
            json.dumps({"id": message["id"], "data": {"status": "err", "error": "bad secret"}})
        )

    async def run() -> None:
        async with ws_server(handler) as url:
            session = PerpsSession(
                chain_id=137,
                credentials=_CREDENTIALS,
                rest_url="http://127.0.0.1:9",
                ws_url=url,
            )
            try:
                with pytest.raises(RequestRejectedError, match="bad secret"):
                    await session.open()
            finally:
                await session.close()

    asyncio.run(asyncio.wait_for(run(), timeout=10.0))


def test_place_order_signs_command_and_returns_order_update() -> None:
    commands: list[dict[str, Any]] = []

    async def handler(ws: ServerConnection) -> None:
        await _handshake(ws)
        async for raw in ws:
            message = json.loads(raw)
            if _is_ping(message):
                continue
            commands.append(message)
            await ws.send(json.dumps({"id": message["id"], "data": [{"status": "ok", "oid": 77}]}))
            await ws.send(json.dumps(_order_update(77, reduce_only=True)))

    async def run() -> None:
        async with ws_server(handler) as url, _open_session(url) as session:
            placement = await session.place_order(
                instrument_id=1,
                side="BUY",
                price="0.5",
                quantity="10",
                reduce_only=True,
                time_in_force="gtc",
            )
            assert placement.order.id == 77
            assert placement.order.reduce_only is True
            assert placement.order.status == "open"
            assert placement.tp_sl is None

    asyncio.run(asyncio.wait_for(run(), timeout=10.0))
    command = commands[0]
    assert command["op"]["type"] == "createOrders"
    assert command["op"]["args"] == [
        {
            "iid": 1,
            "buy": True,
            "po": False,
            "qty": "10",
            "ro": True,
            "tif": "gtc",
            "p": "0.5",
        }
    ]
    assert isinstance(command["salt"], int)
    assert isinstance(command["ts"], int)
    assert command["sig"].startswith("0x") and len(command["sig"]) == 132


def test_batched_session_updates_feed_queue_and_order_waiters() -> None:
    async def handler(ws: ServerConnection) -> None:
        await _handshake(ws)
        async for raw in ws:
            message = json.loads(raw)
            if _is_ping(message):
                continue
            await ws.send(json.dumps({"id": message["id"], "data": [{"status": "ok", "oid": 77}]}))
            await ws.send(json.dumps([_order_update(76), _order_update(77, sequence=2)]))

    async def run() -> None:
        async with ws_server(handler) as url, _open_session(url) as session:
            placement = await session.place_order(
                instrument_id=1,
                side="BUY",
                price="0.5",
                quantity="10",
                time_in_force="gtc",
            )
            assert placement.order.id == 77

            first = await asyncio.wait_for(session.__anext__(), timeout=5.0)
            second = await asyncio.wait_for(session.__anext__(), timeout=5.0)
            assert isinstance(first, PerpsOrderEvent)
            assert first.payload.id == 76
            assert isinstance(second, PerpsOrderEvent)
            assert second.payload.id == 77

    asyncio.run(asyncio.wait_for(run(), timeout=10.0))


def test_batched_fill_frame_yields_one_event_with_frame_sequence() -> None:
    async def handler(ws: ServerConnection) -> None:
        await _handshake(ws)
        await ws.send(json.dumps(_fills_update()))
        with contextlib.suppress(Exception):
            async for _ in ws:
                pass

    async def run() -> None:
        async with ws_server(handler) as url, _open_session(url) as session:
            event = await asyncio.wait_for(session.__anext__(), timeout=5.0)
            assert isinstance(event, PerpsFillEvent)
            assert event.channel == "fills"
            assert event.sequence == 6
            assert [fill.trade_id for fill in event.payload] == [9, 10]
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(session.__anext__(), timeout=0.1)

    asyncio.run(asyncio.wait_for(run(), timeout=10.0))


def test_place_order_with_tp_sl_groups_rows_and_returns_trigger_ids() -> None:
    from polymarket.models.perps.requests import PerpsTpSlTrigger

    commands: list[dict[str, Any]] = []

    async def handler(ws: ServerConnection) -> None:
        await _handshake(ws)
        async for raw in ws:
            message = json.loads(raw)
            if _is_ping(message):
                continue
            commands.append(message)
            await ws.send(
                json.dumps(
                    {
                        "id": message["id"],
                        "data": [
                            {"status": "ok", "oid": 100},
                            {"status": "ok", "oid": 101},
                            {"status": "ok", "oid": 102},
                        ],
                    }
                )
            )
            await ws.send(json.dumps(_order_update(100)))

    async def run() -> None:
        async with ws_server(handler) as url, _open_session(url) as session:
            placement = await session.place_order(
                instrument_id=1,
                side="BUY",
                price="0.5",
                quantity="10",
                time_in_force="gtc",
                take_profit=PerpsTpSlTrigger(trigger_price="1"),
                stop_loss=PerpsTpSlTrigger(trigger_price="0.25"),
            )
            assert placement.order.id == 100
            assert placement.tp_sl is not None
            assert placement.tp_sl.take_profit is not None
            assert placement.tp_sl.take_profit.order_id == 101
            assert placement.tp_sl.stop_loss is not None
            assert placement.tp_sl.stop_loss.order_id == 102

    asyncio.run(asyncio.wait_for(run(), timeout=10.0))
    op = commands[0]["op"]
    assert op["grp"] == "order"
    assert len(op["args"]) == 3
    assert op["args"][1]["tr"] == {"tpsl": "tp", "trp": "1", "market": True}
    assert op["args"][2]["tr"] == {"tpsl": "sl", "trp": "0.25", "market": True}
    # Trigger legs exit the position: entry BUY -> reduce-only SELL legs.
    assert op["args"][1]["buy"] is False and op["args"][1]["ro"] is True


def test_place_order_rejection_raises_request_rejected() -> None:
    async def handler(ws: ServerConnection) -> None:
        await _handshake(ws)
        async for raw in ws:
            message = json.loads(raw)
            if _is_ping(message):
                continue
            await ws.send(
                json.dumps(
                    {
                        "id": message["id"],
                        "data": [{"status": "err", "error": "insufficient margin"}],
                    }
                )
            )

    async def run() -> None:
        async with ws_server(handler) as url, _open_session(url) as session:
            with pytest.raises(RequestRejectedError, match="insufficient margin"):
                await session.place_order(
                    instrument_id=1,
                    side="BUY",
                    price="0.5",
                    quantity="10",
                    time_in_force="gtc",
                )

    asyncio.run(asyncio.wait_for(run(), timeout=10.0))


def test_cancel_order_returns_result_without_raising_on_err_status() -> None:
    async def handler(ws: ServerConnection) -> None:
        await _handshake(ws)
        async for raw in ws:
            message = json.loads(raw)
            if _is_ping(message):
                continue
            assert message["op"] == {"type": "cancelOrders", "args": [55]}
            await ws.send(
                json.dumps(
                    {
                        "id": message["id"],
                        "data": [{"status": "err", "oid": 55, "error": "order not found"}],
                    }
                )
            )

    async def run() -> None:
        async with ws_server(handler) as url, _open_session(url) as session:
            result = await session.cancel_order(order_id=55)
            assert result.status == "err"
            assert result.error == "order not found"

    asyncio.run(asyncio.wait_for(run(), timeout=10.0))


def test_cancel_all_orders_uses_signed_rest_endpoint() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"status": "ok"}, request=request)

    async def run() -> None:
        session = PerpsSession(
            chain_id=137,
            credentials=_CREDENTIALS,
            rest_url="https://perps.test",
            ws_url="ws://127.0.0.1:9",
        )
        session._api = AsyncTransport(
            base_url="https://perps.test",
            client=httpx.AsyncClient(
                base_url="https://perps.test",
                transport=httpx.MockTransport(handler),
            ),
            header_resolver=session._resolve_auth_headers,
        )
        try:
            await session.cancel_all_orders(instrument_id=1, expires_at=1_700_000_005_000)
            await session.cancel_all_orders()
        finally:
            await session.close()

    asyncio.run(asyncio.wait_for(run(), timeout=10.0))

    assert len(captured) == 2
    assert captured[0].method == "DELETE"
    assert captured[0].url.path == "/v1/trade/orders/all"
    assert captured[0].headers["polymarket-proxy"] == _PROXY_ADDRESS
    assert captured[0].headers["polymarket-secret"] == "session-secret"

    scoped_body = json.loads(captured[0].content)
    assert scoped_body["op"] == {"type": "cancelAll", "args": {"iid": 1}}
    assert scoped_body["exp"] == 1_700_000_005_000
    assert isinstance(scoped_body["salt"], int)
    assert isinstance(scoped_body["ts"], int)
    assert scoped_body["sig"].startswith("0x") and len(scoped_body["sig"]) == 132

    unscoped_body = json.loads(captured[1].content)
    assert unscoped_body["op"] == {"type": "cancelAll", "args": {}}
    assert "exp" not in unscoped_body


def test_auto_cancel_uses_signed_rest_endpoint() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        time_ms = json.loads(request.content)["op"]["args"]["time"]
        return httpx.Response(200, json={"status": "ok", "deadline": time_ms}, request=request)

    async def run() -> None:
        session = PerpsSession(
            chain_id=137,
            credentials=_CREDENTIALS,
            rest_url="https://perps.test",
            ws_url="ws://127.0.0.1:9",
        )
        session._api = AsyncTransport(
            base_url="https://perps.test",
            client=httpx.AsyncClient(
                base_url="https://perps.test",
                transport=httpx.MockTransport(handler),
            ),
            header_resolver=session._resolve_auth_headers,
        )
        try:
            await session.arm_auto_cancel(cancel_at=1_767_000_045_000, expires_at=1_700_000_005_000)
            await session.clear_auto_cancel()
        finally:
            await session.close()

    asyncio.run(asyncio.wait_for(run(), timeout=10.0))

    assert len(captured) == 2
    assert captured[0].method == "PATCH"
    assert captured[0].url.path == "/v1/trade/auto-cancel"
    assert captured[0].headers["polymarket-proxy"] == _PROXY_ADDRESS
    assert captured[0].headers["polymarket-secret"] == "session-secret"

    arm_body = json.loads(captured[0].content)
    assert arm_body["op"] == {"type": "autoCancel", "args": {"time": 1_767_000_045_000}}
    assert arm_body["exp"] == 1_700_000_005_000
    assert isinstance(arm_body["salt"], int)
    assert isinstance(arm_body["ts"], int)
    assert arm_body["sig"].startswith("0x") and len(arm_body["sig"]) == 132

    clear_body = json.loads(captured[1].content)
    assert clear_body["op"] == {"type": "autoCancel", "args": {"time": 0}}
    assert "exp" not in clear_body


def test_arm_auto_cancel_daily_limit_raises_typed_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            json={"status": "err", "error": "auto_cancel_daily_limit_reached"},
            request=request,
        )

    async def run() -> None:
        session = PerpsSession(
            chain_id=137,
            credentials=_CREDENTIALS,
            rest_url="https://perps.test",
            ws_url="ws://127.0.0.1:9",
        )
        session._api = AsyncTransport(
            base_url="https://perps.test",
            client=httpx.AsyncClient(
                base_url="https://perps.test",
                transport=httpx.MockTransport(handler),
            ),
            header_resolver=session._resolve_auth_headers,
        )
        try:
            with pytest.raises(AutoCancelDailyLimitError) as excinfo:
                await session.arm_auto_cancel(cancel_at=1_767_000_045_000)
            assert excinfo.value.status == 422
        finally:
            await session.close()

    asyncio.run(asyncio.wait_for(run(), timeout=10.0))


def test_update_margin_sends_signed_command_and_completes() -> None:
    commands: list[dict[str, Any]] = []

    async def handler(ws: ServerConnection) -> None:
        await _handshake(ws)
        async for raw in ws:
            message = json.loads(raw)
            if _is_ping(message):
                continue
            commands.append(message)
            await ws.send(json.dumps({"id": message["id"], "data": {"status": "ok"}}))

    async def run() -> None:
        async with ws_server(handler) as url, _open_session(url) as session:
            result = await session.update_margin(
                instrument_id=3, amount=Decimal("100.000000000000000001")
            )
            assert result is None

    asyncio.run(asyncio.wait_for(run(), timeout=10.0))
    assert commands[0]["op"] == {
        "type": "updateMargin",
        "args": {"amt": "100.000000000000000001", "iid": 3},
    }
    assert commands[0]["req"] == "post"
    assert commands[0]["sig"].startswith("0x") and len(commands[0]["sig"]) == 132


def test_update_margin_rejection_surfaces_request_rejected_error() -> None:
    async def handler(ws: ServerConnection) -> None:
        await _handshake(ws)
        async for raw in ws:
            message = json.loads(raw)
            if _is_ping(message):
                continue
            assert message["op"] == {
                "type": "updateMargin",
                "args": {"amt": "-25.00", "iid": 3},
            }
            await ws.send(
                json.dumps(
                    {
                        "id": message["id"],
                        "data": {"status": "err", "error": "margin_below_required_initial"},
                    }
                )
            )

    async def run() -> None:
        async with ws_server(handler) as url, _open_session(url) as session:
            with pytest.raises(RequestRejectedError, match="margin_below_required_initial"):
                await session.update_margin(instrument_id=3, amount="-25.00")

    asyncio.run(asyncio.wait_for(run(), timeout=10.0))


def test_update_margin_validates_public_inputs_before_sending() -> None:
    async def run() -> None:
        session = PerpsSession(
            chain_id=137,
            credentials=_CREDENTIALS,
            rest_url="http://127.0.0.1:9",
            ws_url="ws://127.0.0.1:9",
        )
        try:
            with pytest.raises(UserInputError, match="non-negative"):
                await session.update_margin(instrument_id=-1, amount="1")
            with pytest.raises(UserInputError, match="amount must be a valid decimal"):
                await session.update_margin(instrument_id=1, amount="not-a-decimal")
            with pytest.raises(UserInputError, match="amount must be finite"):
                await session.update_margin(instrument_id=1, amount="NaN")
        finally:
            await session.close()

    asyncio.run(asyncio.wait_for(run(), timeout=10.0))


def test_sequence_gap_emits_resync_event_before_update() -> None:
    async def handler(ws: ServerConnection) -> None:
        await _handshake(ws)
        await ws.send(json.dumps(_order_update(1, sequence=1)))
        await ws.send(json.dumps(_order_update(2, sequence=5)))
        with contextlib.suppress(Exception):
            async for _ in ws:
                pass

    async def run() -> None:
        async with ws_server(handler) as url, _open_session(url) as session:
            first = await asyncio.wait_for(session.__anext__(), timeout=5.0)
            second = await asyncio.wait_for(session.__anext__(), timeout=5.0)
            third = await asyncio.wait_for(session.__anext__(), timeout=5.0)
            assert isinstance(first, PerpsOrderEvent)
            assert isinstance(second, PerpsResyncEvent)
            assert second.reason == "sequence_gap"
            assert second.channel == "orders"
            assert second.previous_sequence == 1
            assert second.sequence == 5
            assert isinstance(third, PerpsOrderEvent)

    asyncio.run(asyncio.wait_for(run(), timeout=10.0))


def _notification_update(sequence: int, notification_id: str) -> dict[str, Any]:
    return {
        "ch": "notifications",
        "ts": 1751500000000,
        "sq": sequence,
        "data": {
            "id": notification_id,
            "type": "position_opened",
            "instrument_id": 1,
            "side": "long",
            "size": "0.5",
            "avg_price": "100",
            "leverage": 2,
            "order_type": "market",
        },
    }


def test_notification_sequence_gaps_do_not_emit_local_resync() -> None:
    async def handler(ws: ServerConnection) -> None:
        await _handshake(ws)
        await ws.send(json.dumps(_notification_update(10, "5f4a3c2b-1d0e-49f8-a7b6-c5d4e3f2a1b0")))
        await ws.send(json.dumps(_notification_update(50, "6a5b4c3d-2e1f-40a9-b8c7-d6e5f4a3b2c1")))
        await ws.send(json.dumps(_order_update(1, sequence=1)))
        with contextlib.suppress(Exception):
            async for _ in ws:
                pass

    async def run() -> None:
        async with ws_server(handler) as url, _open_session(url) as session:
            first = await asyncio.wait_for(session.__anext__(), timeout=5.0)
            second = await asyncio.wait_for(session.__anext__(), timeout=5.0)
            third = await asyncio.wait_for(session.__anext__(), timeout=5.0)
            assert isinstance(first, PerpsNotificationEvent)
            assert first.payload.type == "position_opened"
            assert first.payload.order_type == "market"
            assert first.sequence == 10
            assert isinstance(second, PerpsNotificationEvent)
            assert second.sequence == 50
            assert isinstance(third, PerpsOrderEvent)

    asyncio.run(asyncio.wait_for(run(), timeout=10.0))


def test_server_notifications_resync_frame_emits_server_resync_event() -> None:
    async def handler(ws: ServerConnection) -> None:
        await _handshake(ws)
        await ws.send(
            json.dumps({"ch": "notifications", "ts": 1751500000000, "sq": 77, "type": "resync"})
        )
        with contextlib.suppress(Exception):
            async for _ in ws:
                pass

    async def run() -> None:
        async with ws_server(handler) as url, _open_session(url) as session:
            event = await asyncio.wait_for(session.__anext__(), timeout=5.0)
            assert isinstance(event, PerpsResyncEvent)
            assert event.reason == "server"
            assert event.channel == "notifications"
            assert event.sequence == 77
            assert event.previous_sequence is None

    asyncio.run(asyncio.wait_for(run(), timeout=10.0))


def test_session_reconnects_reauthenticates_and_emits_resync() -> None:
    connections = 0
    connected = asyncio.Event()

    async def handler(ws: ServerConnection) -> None:
        nonlocal connections
        connections += 1
        await _handshake(ws)
        if connections == 1:
            await ws.close()
            return
        connected.set()
        with contextlib.suppress(Exception):
            async for _ in ws:
                pass

    async def run() -> None:
        async with ws_server(handler) as url, _open_session(url) as session:
            event = await asyncio.wait_for(session.__anext__(), timeout=10.0)
            assert isinstance(event, PerpsResyncEvent)
            assert event.reason == "reconnect"
            await asyncio.wait_for(connected.wait(), timeout=10.0)
            assert connections == 2

    asyncio.run(asyncio.wait_for(run(), timeout=20.0))


def test_commands_fail_fast_after_close() -> None:
    async def handler(ws: ServerConnection) -> None:
        await _handshake(ws)
        with contextlib.suppress(Exception):
            async for _ in ws:
                pass

    async def run() -> None:
        async with ws_server(handler) as url:
            async with _open_session(url) as session:
                pass
            with pytest.raises(TransportError, match="closed"):
                await session.cancel_order(order_id=1)

    asyncio.run(asyncio.wait_for(run(), timeout=10.0))
