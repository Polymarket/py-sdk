# pyright: reportPrivateUsage=false
"""Perps session behavior against a local WebSocket server."""

import asyncio
import contextlib
import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
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
from polymarket.errors import TimeoutError as SDKTimeoutError
from polymarket.models.perps.credentials import PerpsCredentials
from polymarket.models.perps.events import (
    PerpsFillEvent,
    PerpsNotificationEvent,
    PerpsOrderEvent,
    PerpsResyncEvent,
)
from polymarket.models.perps.orders import PerpsCancelOrderErrorCode

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
    order_id: int,
    *,
    client_order_id: str | None = None,
    sequence: int = 1,
    reduce_only: bool | None = None,
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
    if client_order_id is not None:
        update["data"]["coid"] = client_order_id
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
            client_order_id = message["op"]["args"][0]["c"]
            await ws.send(
                json.dumps(
                    _order_update(
                        77,
                        client_order_id=client_order_id,
                        reduce_only=True,
                    )
                )
            )
            await ws.send(json.dumps({"id": message["id"], "data": [{"status": "ok", "oid": 77}]}))

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
            assert placement.order.client_order_id == commands[0]["op"]["args"][0]["c"]
            assert placement.order.reduce_only is True
            assert placement.order.status == "open"
            assert placement.tp_sl is None
            assert session._event_waiters == []

    asyncio.run(asyncio.wait_for(run(), timeout=10.0))
    command = commands[0]
    client_order_id = command["op"]["args"][0]["c"]
    assert isinstance(client_order_id, str)
    assert len(client_order_id) == 32
    int(client_order_id, 16)
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
            "c": client_order_id,
        }
    ]
    assert isinstance(command["salt"], int)
    assert isinstance(command["ts"], int)
    assert command["sig"].startswith("0x") and len(command["sig"]) == 132


def test_place_order_update_timeout_starts_after_ack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from polymarket._internal.actions.perps import trading

    monkeypatch.setattr(trading, "_ORDER_PLACEMENT_UPDATE_TIMEOUT_S", 0.5)

    async def handler(ws: ServerConnection) -> None:
        await _handshake(ws)
        async for raw in ws:
            message = json.loads(raw)
            if _is_ping(message):
                continue
            client_order_id = message["op"]["args"][0]["c"]
            await asyncio.sleep(0.6)
            await ws.send(json.dumps({"id": message["id"], "data": [{"status": "ok", "oid": 77}]}))
            await ws.send(
                json.dumps(
                    _order_update(
                        77,
                        client_order_id=client_order_id,
                    )
                )
            )

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

    asyncio.run(asyncio.wait_for(run(), timeout=10.0))


def test_place_order_ack_timeout_cleans_waiter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from polymarket._internal import perps_session

    async def handler(ws: ServerConnection) -> None:
        await _handshake(ws)
        with contextlib.suppress(Exception):
            async for _ in ws:
                pass

    async def run() -> None:
        async with ws_server(handler) as url, _open_session(url) as session:
            monkeypatch.setattr(perps_session, "_ACK_TIMEOUT_S", 0.01)
            with pytest.raises(
                TransportError,
                match="post order acknowledgement timed out",
            ):
                await session.place_order(
                    instrument_id=1,
                    side="BUY",
                    price="0.5",
                    quantity="10",
                    time_in_force="gtc",
                )
            assert session._event_waiters == []

    asyncio.run(asyncio.wait_for(run(), timeout=10.0))


def test_place_order_update_timeout_cleans_waiter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from polymarket._internal.actions.perps import trading

    monkeypatch.setattr(trading, "_ORDER_PLACEMENT_UPDATE_TIMEOUT_S", 0.01)

    async def handler(ws: ServerConnection) -> None:
        await _handshake(ws)
        async for raw in ws:
            message = json.loads(raw)
            if _is_ping(message):
                continue
            await ws.send(json.dumps({"id": message["id"], "data": [{"status": "ok", "oid": 77}]}))

    async def run() -> None:
        async with ws_server(handler) as url, _open_session(url) as session:
            with pytest.raises(SDKTimeoutError, match="event wait timed out"):
                await session.place_order(
                    instrument_id=1,
                    side="BUY",
                    price="0.5",
                    quantity="10",
                    time_in_force="gtc",
                )
            assert session._event_waiters == []

    asyncio.run(asyncio.wait_for(run(), timeout=10.0))


def test_batched_session_updates_feed_queue_and_order_waiters() -> None:
    async def handler(ws: ServerConnection) -> None:
        await _handshake(ws)
        async for raw in ws:
            message = json.loads(raw)
            if _is_ping(message):
                continue
            client_order_id = message["op"]["args"][0]["c"]
            await ws.send(json.dumps({"id": message["id"], "data": [{"status": "ok", "oid": 77}]}))
            await ws.send(
                json.dumps(
                    [
                        _order_update(76),
                        _order_update(
                            77,
                            client_order_id=client_order_id,
                            sequence=2,
                        ),
                    ]
                )
            )

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
            client_order_id = message["op"]["args"][0]["c"]
            await ws.send(
                json.dumps(
                    _order_update(
                        100,
                        client_order_id=client_order_id,
                    )
                )
            )
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
            assert placement.order.client_order_id == commands[0]["op"]["args"][0]["c"]
            assert placement.tp_sl is not None
            assert placement.tp_sl.take_profit is not None
            assert placement.tp_sl.take_profit.order_id == 101
            assert placement.tp_sl.stop_loss is not None
            assert placement.tp_sl.stop_loss.order_id == 102

    asyncio.run(asyncio.wait_for(run(), timeout=10.0))
    op = commands[0]["op"]
    assert op["grp"] == "order"
    assert len(op["args"]) == 3
    assert len(op["args"][0]["c"]) == 32
    assert "c" not in op["args"][1]
    assert "c" not in op["args"][2]
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
            assert session._event_waiters == []

    asyncio.run(asyncio.wait_for(run(), timeout=10.0))


def test_post_orders_preserves_low_level_client_ids_and_error_acks() -> None:
    from polymarket.models.perps.requests import PerpsOrderRequest

    commands: list[dict[str, Any]] = []
    supplied_client_order_id = "aabbccddeeff00112233445566778899"

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
                            {"status": "ok", "oid": 77},
                            {"status": "err", "error": "insufficient margin"},
                        ],
                    }
                )
            )

    async def run() -> None:
        async with ws_server(handler) as url, _open_session(url) as session:
            acks = await session.post_orders(
                [
                    PerpsOrderRequest(
                        instrument_id=1,
                        side="BUY",
                        price="0.5",
                        quantity="10",
                        time_in_force="gtc",
                    ),
                    PerpsOrderRequest(
                        instrument_id=1,
                        side="SELL",
                        price="0.6",
                        quantity="5",
                        time_in_force="gtc",
                        client_order_id=supplied_client_order_id,
                    ),
                ]
            )
            assert [ack.status for ack in acks] == ["ok", "err"]
            assert acks[1].error == "insufficient margin"

    asyncio.run(asyncio.wait_for(run(), timeout=10.0))
    args = commands[0]["op"]["args"]
    assert "c" not in args[0]
    assert args[1]["c"] == supplied_client_order_id


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
                        "data": [{"status": "err", "oid": 55, "error": "order_not_found"}],
                    }
                )
            )

    async def run() -> None:
        async with ws_server(handler) as url, _open_session(url) as session:
            result = await session.cancel_order(order_id=55)
            assert result.status == "err"
            assert result.error is PerpsCancelOrderErrorCode.ORDER_NOT_FOUND

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


def test_arm_auto_cancel_rejects_deadline_less_than_five_seconds_ahead() -> None:
    async def run() -> None:
        session = PerpsSession(
            chain_id=137,
            credentials=_CREDENTIALS,
            rest_url="http://127.0.0.1:9",
            ws_url="ws://127.0.0.1:9",
        )
        try:
            with pytest.raises(UserInputError, match="at least 5 seconds"):
                await session.arm_auto_cancel(
                    cancel_at=datetime.now(tz=UTC) + timedelta(milliseconds=4_999)
                )
        finally:
            await session.close()

    asyncio.run(asyncio.wait_for(run(), timeout=10.0))


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
                await session.arm_auto_cancel(cancel_at=datetime.now(tz=UTC) + timedelta(minutes=1))
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


def test_malformed_notification_decimal_is_dropped_without_disrupting_dispatch() -> None:
    async def handler(ws: ServerConnection) -> None:
        await _handshake(ws)
        malformed = _notification_update(10, "5f4a3c2b-1d0e-49f8-a7b6-c5d4e3f2a1b0")
        malformed["data"]["size"] = True
        await ws.send(json.dumps(malformed))
        await ws.send(json.dumps(_order_update(1, sequence=1)))
        with contextlib.suppress(Exception):
            async for _ in ws:
                pass

    async def run() -> None:
        async with ws_server(handler) as url, _open_session(url) as session:
            event = await asyncio.wait_for(session.__anext__(), timeout=5.0)
            assert isinstance(event, PerpsOrderEvent)
            assert event.payload.id == 1
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(session.__anext__(), timeout=0.1)

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


# Consent failures and races use controlled responses rather than mutating live accounts.
def test_builder_consent_serializes_versions_and_commits_only_confirmed_terms() -> None:
    from eth_account import Account
    from eth_account.messages import encode_typed_data

    from polymarket._internal.actions.perps.signing import build_perps_op_typed_data
    from polymarket.models.perps import PerpsBuilderAttribution

    async def run() -> None:
        signer = Account.from_key("0x" + "23" * 32)
        builder = "0x" + "ab" * 20
        other_builder = "0x" + "cd" * 20
        started = asyncio.Event()
        release = asyncio.Event()
        grants: dict[str, dict[str, Any]] = {}
        posted: list[dict[str, Any]] = []
        requests: list[httpx.Request] = []
        reject = False
        cap = "0.0002"
        reject_status = False

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path == "/v1/info/builder":
                if reject_status:
                    return httpx.Response(400, json={"error": "status unavailable"})
                return httpx.Response(
                    200,
                    json={
                        "address": request.url.params["address"],
                        "registered": True,
                        "enabled": True,
                        "admission_enabled": True,
                        "max_fee_rate": cap,
                    },
                )
            if request.method == "GET":
                saved = grants.get(str(request.url.params["builder"]).lower())
                return httpx.Response(200, json={"data": [saved] if saved else []})
            body = json.loads(request.content)
            args = body["op"]["args"]
            posted.append(args)
            typed = build_perps_op_typed_data(
                chain_id=137,
                op=[
                    "approveBuilder",
                    [args["builder"], args["max_fee_rate"], args["approval_version"]],
                ],
                salt=body["salt"],
                timestamp_ms=body["ts"],
            )
            assert (
                Account.recover_message(
                    encode_typed_data(full_message=typed), signature=body["sig"]
                )
                == signer.address
            )
            if len(posted) == 1:
                started.set()
                await release.wait()
            if reject:
                return httpx.Response(400, json={"error": "rejected"})
            approval = {**args, "trader": signer.address, "timestamp": 1751500000001, "sequence": 2}
            grants[args["builder"].lower()] = approval
            return httpx.Response(200, json=approval)

        session = PerpsSession(
            chain_id=137,
            credentials=_CREDENTIALS,
            rest_url="https://perps.test",
            ws_url="ws://unused",
            owner_signer=signer,
            builder_attribution=builder,
        )
        await session._api.close()
        session._api = AsyncTransport(
            base_url="https://perps.test",
            client=httpx.AsyncClient(
                transport=httpx.MockTransport(handler), base_url="https://perps.test"
            ),
        )
        try:
            pending = asyncio.create_task(session.approve_builder_fee(max_fee_rate="0.0002"))
            await started.wait()
            queued_revoke = asyncio.create_task(session.revoke_builder_fee())
            await asyncio.sleep(0)
            assert session.builder_attribution is None and len(posted) == 1
            release.set()
            await pending
            await queued_revoke
            assert [(p["builder"], p["approval_version"], p["max_fee_rate"]) for p in posted] == [
                (builder, 1, "0.0002"),
                (builder, 2, "0"),
            ]
            assert session.builder_attribution is None
            await session.approve_builder_fee(builder_address=builder, max_fee_rate="0.0003")
            terms = PerpsBuilderAttribution(address=builder, fee_rate=Decimal("0.0002"))
            assert session.builder_attribution == terms
            cap = "0.001"
            request_count = len(requests)
            with pytest.raises(TypeError, match="max_fee_rate"):
                await session.approve_builder_fee()  # type: ignore[call-arg]
            assert len(requests) == request_count
            await session.approve_builder_fee(builder_address=builder, max_fee_rate="0.0003")
            terms = PerpsBuilderAttribution(address=builder, fee_rate=Decimal("0.0003"))
            assert session.builder_attribution == terms
            reject_status = True
            with pytest.raises(RequestRejectedError):
                await session.approve_builder_fee(builder_address=builder, max_fee_rate="0.0001")
            assert session.builder_attribution == terms
            assert len(posted) == 5
            reject = True
            with pytest.raises(RequestRejectedError):
                await session.approve_builder_fee(
                    builder_address=other_builder, max_fee_rate="0.0004"
                )
            with pytest.raises(RequestRejectedError):
                await session.revoke_builder_fee()
            assert session.builder_attribution == terms
            reject = False
            await session.revoke_builder_fee(other_builder)
            assert session.builder_attribution == terms
            revoked = await session.approve_builder_fee(max_fee_rate="0")
            assert revoked.approval_version == 6 and session.builder_attribution is None
            reject_status = False
            cap = "0"
            await session.approve_builder_fee(builder_address=builder, max_fee_rate="0.0003")
            assert session.builder_attribution is None
            cap = "0.0002"
            await session.approve_builder_fee(max_fee_rate="0.0002")
            assert session.builder_attribution == PerpsBuilderAttribution(
                address=builder, fee_rate=Decimal("0.0002")
            )
        finally:
            await session.close()

    asyncio.run(asyncio.wait_for(run(), timeout=10))


def test_builder_fills_share_session_iterator_before_ack_and_after_reconnect() -> None:
    from polymarket.models.perps import PerpsBuilderFillEvent

    async def run() -> None:
        disconnect = asyncio.Event()
        subscriptions: list[list[str]] = []

        async def handler(ws: ServerConnection) -> None:
            while True:
                frame = json.loads(await ws.recv())
                if _is_ping(frame):
                    continue
                if frame["req"] == "sub" and frame["chs"] == ["builderFills"]:
                    subscriptions.append(frame["chs"])
                    if len(subscriptions) == 1:
                        for sequence in (1, 100):
                            await ws.send(
                                json.dumps(
                                    {
                                        "ch": "builderFills",
                                        "ts": 1751500000000,
                                        "sq": sequence,
                                        "data": [],
                                    }
                                )
                            )
                    await ws.send(json.dumps({"id": frame["id"], "data": {"status": "ok"}}))
                    if len(subscriptions) == 1:
                        await disconnect.wait()
                        await ws.close()
                    else:
                        await ws.send(
                            json.dumps(
                                {"ch": "builderFills", "ts": 1751500000000, "sq": 200, "data": []}
                            )
                        )
                        await ws.wait_closed()
                    return
                await ws.send(json.dumps({"id": frame["id"], "data": {"status": "ok"}}))

        async with ws_server(handler) as url:
            session = PerpsSession(
                chain_id=137,
                credentials=_CREDENTIALS,
                rest_url="http://127.0.0.1:9",
                ws_url=url,
                include_builder_fills=True,
            )
            async with await session.open():
                initial = [await anext(session), await anext(session)]
                assert [e.sequence for e in initial if isinstance(e, PerpsBuilderFillEvent)] == [
                    1,
                    100,
                ]
                disconnect.set()
                recovered = [await anext(session), await anext(session)]
                assert any(
                    isinstance(e, PerpsResyncEvent) and e.reason == "reconnect" for e in recovered
                )
                assert any(
                    isinstance(e, PerpsBuilderFillEvent) and e.sequence == 200 for e in recovered
                )
                assert subscriptions[0] == subscriptions[1] and "builderFills" in subscriptions[0]

    asyncio.run(asyncio.wait_for(run(), timeout=15))


def test_position_exits_keep_terms_captured_before_portfolio_read() -> None:
    from polymarket.models.perps import PerpsBuilderAttribution, PerpsPositionTpSlTrigger

    async def run() -> None:
        frames: list[dict[str, Any]] = []

        async def handler(ws: ServerConnection) -> None:
            await _handshake(ws)
            async for raw in ws:
                frame = json.loads(raw)
                if _is_ping(frame):
                    continue
                frames.append(frame)
                await ws.send(
                    json.dumps(
                        {
                            "id": frame["id"],
                            "data": [{"status": "ok", "oid": 77}, {"status": "ok", "oid": 78}],
                        }
                    )
                )

        terms = PerpsBuilderAttribution(address="0x" + "ab" * 20, fee_rate=Decimal("0.0003"))
        async with ws_server(handler) as url:
            session = PerpsSession(
                chain_id=137,
                credentials=_CREDENTIALS,
                rest_url="https://perps.test",
                ws_url=url,
                builder_attribution=terms,
            )

            def portfolio_response(request: httpx.Request) -> httpx.Response:
                # Consent can change while the position request is in flight.
                session._builder_attribution = None
                return httpx.Response(
                    200,
                    json={
                        "positions": [
                            {
                                "instrument_id": 1,
                                "symbol": "BTC",
                                "size": "1",
                                "entry_price": "100",
                                "leverage": 1,
                                "cross": True,
                                "initial_margin": "0",
                                "maintenance_margin": "0",
                                "position_value": "100",
                                "liquidation_price": "0",
                                "unrealized_pnl": "0",
                                "return_on_equity": "0",
                                "cumulative_funding": "0",
                            }
                        ],
                        "margin": {
                            "total_account_value": "100",
                            "total_initial_margin": "0",
                            "total_maintenance_margin": "0",
                            "total_position_value": "100",
                        },
                        "withdrawable": "0",
                        "in_liquidation": False,
                        "timestamp": 1751500000000,
                    },
                )

            await session._api.close()
            session._api = AsyncTransport(
                base_url="https://perps.test",
                client=httpx.AsyncClient(
                    transport=httpx.MockTransport(portfolio_response), base_url="https://perps.test"
                ),
            )
            async with await session.open():
                await session.place_position_tp_sl(
                    instrument_id=1,
                    take_profit=PerpsPositionTpSlTrigger(trigger_price="200"),
                    stop_loss=PerpsPositionTpSlTrigger(trigger_price="50"),
                )
                assert [row["builder"] for row in frames[0]["op"]["args"]] == [
                    {"address": terms.address, "fee_rate": "0.0003"},
                    {"address": terms.address, "fee_rate": "0.0003"},
                ]

    asyncio.run(asyncio.wait_for(run(), timeout=10))


@pytest.mark.parametrize(
    "state",
    ["approved", "lower_cap", "inactive", "missing", "revoked", "zero_cap"],
)
def test_builder_setup_restores_consent_without_writes(state: str) -> None:
    from eth_account import Account

    from polymarket.models.perps import PerpsOrderRequest

    async def run() -> None:
        builder = "0x" + "ab" * 20
        reads: list[str] = []
        cap = "0" if state == "zero_cap" else "0.0001" if state == "lower_cap" else "0.0003"
        disabled = state in ("missing", "revoked", "zero_cap")
        posted: list[dict[str, Any]] = []

        async def handler(ws: ServerConnection) -> None:
            await _handshake(ws)
            async for raw in ws:
                frame = json.loads(raw)
                if _is_ping(frame):
                    continue
                row = frame["op"]["args"][0]
                if disabled:
                    assert "builder" not in row
                else:
                    assert row["builder"] == {
                        "address": builder,
                        "fee_rate": str(min(Decimal(cap), Decimal("0.0002"))),
                    }
                await ws.send(
                    json.dumps({"id": frame["id"], "data": [{"status": "ok", "oid": 77}]})
                )

        def response(request: httpx.Request) -> httpx.Response:
            if request.method == "POST":
                args = json.loads(request.content)["op"]["args"]
                posted.append(args)
                assert args["builder"] == builder
                return httpx.Response(
                    200,
                    json={
                        **args,
                        "trader": "0x" + "12" * 20,
                        "timestamp": 1751500000000,
                        "sequence": 2,
                    },
                )
            assert request.method == "GET"
            reads.append(request.url.path)
            if request.url.path == "/v1/info/builder":
                assert request.url.params["address"] == builder
                return httpx.Response(
                    200,
                    json={
                        "address": builder,
                        "registered": True,
                        "enabled": state != "inactive",
                        "admission_enabled": True,
                        "max_fee_rate": cap,
                    },
                )
            assert request.url.path == "/v1/account/builder-approvals"
            assert request.url.params["builder"] == builder
            assert request.headers["POLYMARKET-PROXY"] == _CREDENTIALS.proxy
            assert request.headers["POLYMARKET-SECRET"] == _CREDENTIALS.secret
            return httpx.Response(
                200,
                json={
                    "data": []
                    if state == "missing"
                    else [
                        {
                            "trader": "0x" + "12" * 20,
                            "builder": builder.upper().replace("0X", "0x"),
                            "max_fee_rate": "0" if state == "revoked" else "0.0002",
                            "approval_version": 1,
                            "timestamp": 1751500000000,
                            "sequence": 1,
                        }
                    ]
                },
            )

        async with ws_server(handler) as url:
            session = PerpsSession(
                chain_id=137,
                credentials=_CREDENTIALS,
                builder_attribution=builder,
                owner_signer=Account.from_key("0x" + "23" * 32),
                rest_url="https://perps.test",
                ws_url=url,
            )
            await session._api.close()
            session._api = AsyncTransport(
                base_url="https://perps.test",
                header_resolver=session._resolve_auth_headers,
                client=httpx.AsyncClient(
                    transport=httpx.MockTransport(response), base_url="https://perps.test"
                ),
            )
            try:
                if state != "inactive":
                    await session.open()
                    orders = [
                        PerpsOrderRequest(
                            instrument_id=1, side="BUY", quantity="1", time_in_force="ioc"
                        )
                    ]
                    await session.post_orders(orders)
                    assert reads == ["/v1/info/builder", "/v1/account/builder-approvals"]
                    assert not posted
                    if disabled:
                        cap = "0.0001"
                        await session.approve_builder_fee(max_fee_rate="0.0001")
                        disabled = False
                        await session.post_orders(orders)
                else:
                    with pytest.raises(UserInputError):
                        await session.open()
            finally:
                await session.close()

    asyncio.run(asyncio.wait_for(run(), timeout=10))


@pytest.mark.parametrize("acknowledgement", ["rejected", "missing"])
def test_optional_builder_subscription_never_blocks_readiness(acknowledgement: str) -> None:
    async def run() -> None:
        subscriptions: list[list[str]] = []
        receipt_requested = asyncio.Event()
        disconnect = asyncio.Event()

        async def handler(ws: ServerConnection) -> None:
            frames = await _handshake(ws)
            subscriptions.append(frames[1]["chs"])
            assert "builderFills" not in frames[1]["chs"]
            async for raw in ws:
                frame = json.loads(raw)
                if _is_ping(frame):
                    continue
                if frame.get("req") == "sub":
                    assert frame["chs"] == ["builderFills"]
                    if acknowledgement == "rejected":
                        await ws.send(
                            json.dumps(
                                {
                                    "id": frame["id"],
                                    "data": {"status": "err", "error": "unavailable"},
                                }
                            )
                        )
                    receipt_requested.set()
                    if len(subscriptions) == 1:
                        await disconnect.wait()
                        await ws.close()
                        return
                    continue
                await ws.send(json.dumps({"id": frame["id"], "data": {"status": "ok"}}))

        async with ws_server(handler) as url:
            session = PerpsSession(
                chain_id=137,
                credentials=_CREDENTIALS,
                rest_url="http://127.0.0.1:9",
                ws_url=url,
                include_builder_fills=True,
            )
            try:
                await asyncio.wait_for(session.open(), timeout=1)
                await receipt_requested.wait()
                receipt_requested.clear()
                disconnect.set()
                event = await asyncio.wait_for(anext(session), timeout=5)
                assert isinstance(event, PerpsResyncEvent) and event.reason == "reconnect"
                await receipt_requested.wait()
            finally:
                await session.close()
            assert not session._pending
            assert session._builder_subscription_task is None

    asyncio.run(asyncio.wait_for(run(), timeout=10))


@pytest.mark.parametrize("identifiers", [[1, -1], [1, True], [1, 1.5]])
def test_cancel_validates_entire_batch_before_signing(
    monkeypatch: pytest.MonkeyPatch,
    identifiers: list[Any],
) -> None:
    def unexpected_sign(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("invalid batch reached signing")

    async def run() -> None:
        from polymarket._internal import perps_session

        monkeypatch.setattr(perps_session, "sign_perps_op_with_key", unexpected_sign)

        async def handler(ws: ServerConnection) -> None:
            await _handshake(ws)
            await ws.wait_closed()

        async with ws_server(handler) as url, _open_session(url) as session:
            with pytest.raises(UserInputError):
                await session.cancel_orders(order_ids=identifiers)
            assert not session._pending

    asyncio.run(asyncio.wait_for(run(), timeout=10))


@pytest.mark.parametrize("later_failure", [False, True])
def test_cancel_lost_response_never_replays_uncertain_command(
    monkeypatch: pytest.MonkeyPatch,
    later_failure: bool,
) -> None:
    from polymarket import PerpsCancelRetryError
    from polymarket._internal import perps_session

    monkeypatch.setattr(perps_session, "_ACK_TIMEOUT_S", 0.05)
    commands: list[dict[str, Any]] = []

    async def handler(ws: ServerConnection) -> None:
        await _handshake(ws)
        async for raw in ws:
            message = json.loads(raw)
            if _is_ping(message):
                continue
            commands.append(message)
            if later_failure and len(commands) == 1:
                await ws.send(
                    json.dumps(
                        {
                            "id": message["id"],
                            "data": [
                                {"status": "ok", "oid": 1},
                                {"status": "err", "oid": 2, "error": "order_in_flight"},
                            ],
                        }
                    )
                )

    async def run() -> None:
        async with ws_server(handler) as url, _open_session(url) as session:
            if later_failure:
                with pytest.raises(PerpsCancelRetryError) as caught:
                    await session.cancel_orders(order_ids=[1, 2], expires_at=4_000_000_000_000)
                assert caught.value.pending_indexes == (1,)
                assert caught.value.results[0].status == "ok"
                assert caught.value.results[1].status == "err"
                assert isinstance(caught.value.__cause__, TransportError)
            else:
                with pytest.raises(TransportError):
                    await session.cancel_order(order_id=2, expires_at=4_000_000_000_000)
            assert not session._pending

    asyncio.run(asyncio.wait_for(run(), timeout=10))
    assert [command["op"]["args"] for command in commands] == (
        [[1, 2], [2]] if later_failure else [[2]]
    )
    assert all(command["exp"] == 4_000_000_000_000 for command in commands)


def test_cancelling_cancel_task_removes_pending_request_without_retry() -> None:
    commands: list[dict[str, Any]] = []

    async def run() -> None:
        received = asyncio.Event()

        async def handler(ws: ServerConnection) -> None:
            await _handshake(ws)
            async for raw in ws:
                message = json.loads(raw)
                if _is_ping(message):
                    continue
                commands.append(message)
                received.set()

        async with ws_server(handler) as url, _open_session(url) as session:
            task = asyncio.create_task(session.cancel_order(order_id=1))
            await received.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert not session._pending

    asyncio.run(asyncio.wait_for(run(), timeout=10))
    assert len(commands) == 1
