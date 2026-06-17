import asyncio
import json
import os
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from decimal import Decimal
from typing import Any, cast

import pytest
from websockets.asyncio.server import ServerConnection, serve

from polymarket import PRODUCTION, ApiKeyCreds, AsyncSecureClient
from polymarket.errors import TransportError, UnexpectedResponseError
from polymarket.rfq import (
    RfqConfirmationRequestEvent,
    RfqErrorCode,
    RfqExecutionStatus,
    RfqExecutionUpdateEvent,
    RfqQuoteRejectedError,
    RfqQuoteRequestEvent,
    RfqQuoteSource,
    RfqRequestedSizeUnit,
    RfqTradeEvent,
)

pytestmark = pytest.mark.anyio

RFQ_ID = "rfq-123"
QUOTE_ID = "quote-456"
TX_HASH = "0x1111111111111111111111111111111111111111111111111111111111111111"
CONDITION_ID = "0x032def24bfb0c5c57fb236fac08b94236a0000000000000000000000000000"
YES_POSITION_ID = "99878393523957043401217108863095556720659532630565063651671026144852955005052"
NO_POSITION_ID = "14961555500324159061633734348998856463418381831586644199915991405148322060881"

Handler = Callable[[ServerConnection], Awaitable[None]]


def _existing_credentials() -> ApiKeyCreds | None:
    key = os.environ.get("POLYMARKET_TEST_API_KEY")
    secret = os.environ.get("POLYMARKET_TEST_API_SECRET")
    passphrase = os.environ.get("POLYMARKET_TEST_API_PASSPHRASE")
    if key and secret and passphrase:
        return ApiKeyCreds(key=key, secret=secret, passphrase=passphrase)
    return None


@asynccontextmanager
async def _ws_server(handler: Handler) -> AsyncGenerator[str, None]:
    server = await serve(handler, host="127.0.0.1", port=0)
    try:
        sockets = tuple(server.sockets)
        assert sockets
        port = sockets[0].getsockname()[1]
        yield f"ws://127.0.0.1:{port}"
    finally:
        server.close()
        await server.wait_closed()


@asynccontextmanager
async def _rfq_client(
    require_env: Callable[[str], str], ws_url: str
) -> AsyncGenerator[AsyncSecureClient, None]:
    client = await AsyncSecureClient.create(
        private_key=require_env("POLYMARKET_PRIVATE_KEY"),
        wallet=require_env("POLYMARKET_DEPOSIT_WALLET"),
        credentials=_existing_credentials(),
        environment=replace(PRODUCTION, rfq_quoter_ws_url=ws_url),
    )
    try:
        yield client
    finally:
        await client.close()


@pytest.mark.integration
async def test_rfq_session_quotes_confirms_and_receives_execution_update(
    require_env: Callable[[str], str],
) -> None:
    received: list[dict[str, Any]] = []

    async def handler(ws: ServerConnection) -> None:
        async for raw in ws:
            assert isinstance(raw, str)
            frame = json.loads(raw)
            received.append(frame)
            if frame["type"] == "auth":
                await ws.send(json.dumps({"type": "auth", "success": True}))
                await ws.send(json.dumps(_quote_request_message()))
            elif frame["type"] == "RFQ_QUOTE":
                await ws.send(
                    json.dumps(
                        {
                            "type": "ACK_RFQ_QUOTE",
                            "rfq_id": RFQ_ID,
                            "quote_id": QUOTE_ID,
                        }
                    )
                )
                await ws.send(json.dumps(_confirmation_request_message(frame)))
            elif frame["type"] == "RFQ_CONFIRMATION_RESPONSE":
                await ws.send(
                    json.dumps(
                        {
                            "type": "ACK_RFQ_CONFIRMATION_RESPONSE",
                            "rfq_id": RFQ_ID,
                            "quote_id": QUOTE_ID,
                            "decision": frame["decision"],
                        }
                    )
                )
                await ws.send(
                    json.dumps(
                        {
                            "type": "RFQ_EXECUTION_UPDATE",
                            "rfq_id": RFQ_ID,
                            "status": "MINED",
                            "tx_hash": TX_HASH,
                        }
                    )
                )
                await ws.send(json.dumps(_trade_message()))

    async with (
        _ws_server(handler) as ws_url,
        _rfq_client(require_env, ws_url) as client,
        client.open_rfq_session() as session,
    ):
        async for event in session:
            if isinstance(event, RfqQuoteRequestEvent):
                assert event.requested_size.unit is RfqRequestedSizeUnit.NOTIONAL
                assert event.requested_size.value == Decimal("1")
                quote = await event.quote(price=Decimal("0.45"), source=RfqQuoteSource.COLLATERAL)
                assert quote.rfq_id == RFQ_ID
                assert quote.quote_id == QUOTE_ID
            elif isinstance(event, RfqConfirmationRequestEvent):
                ack = await event.confirm()
                assert ack.rfq_id == RFQ_ID
                assert ack.quote_id == QUOTE_ID
            elif isinstance(event, RfqExecutionUpdateEvent):
                assert event.status is RfqExecutionStatus.MINED
                assert event.tx_hash == TX_HASH
                break

    auth = _first_frame(received, "auth")
    assert auth["auth"]["apiKey"]
    assert (
        auth["identity"]["maker_address"].lower()
        == require_env("POLYMARKET_DEPOSIT_WALLET").lower()
    )

    quote = _first_frame(received, "RFQ_QUOTE")
    assert quote["price_e6"] == "450000"
    assert quote["size_e6"] == "2222222"
    signed_order = quote["signed_order"]
    assert signed_order["tokenId"] == NO_POSITION_ID
    assert signed_order["side"] == 0
    assert signed_order["makerAmount"] == "1222223"
    assert signed_order["takerAmount"] == "2222222"
    assert signed_order["signature"].startswith("0x")

    confirmation = _first_frame(received, "RFQ_CONFIRMATION_RESPONSE")
    assert confirmation == {
        "type": "RFQ_CONFIRMATION_RESPONSE",
        "rfq_id": RFQ_ID,
        "quote_id": QUOTE_ID,
        "decision": "CONFIRM",
    }


@pytest.mark.integration
async def test_rfq_session_receives_confirmed_trade_broadcast(
    require_env: Callable[[str], str],
) -> None:
    async def handler(ws: ServerConnection) -> None:
        async for raw in ws:
            assert isinstance(raw, str)
            frame = json.loads(raw)
            if frame["type"] == "auth":
                await ws.send(json.dumps({"type": "auth", "success": True}))
                await ws.send(json.dumps(_trade_message()))

    async with (
        _ws_server(handler) as ws_url,
        _rfq_client(require_env, ws_url) as client,
        client.open_rfq_session() as session,
    ):
        async for event in session:
            assert isinstance(event, RfqTradeEvent)
            assert event.type == "trade"
            assert event.rfq_id == RFQ_ID
            assert event.requestor_public_id == "requestor-abc"
            assert event.condition_id == CONDITION_ID
            assert event.leg_position_ids == (YES_POSITION_ID, NO_POSITION_ID)
            assert event.direction == "BUY"
            assert event.side == "YES"
            assert event.price == Decimal("0.125")
            assert event.size == Decimal("0.8")
            assert event.tx_hash == TX_HASH
            assert event.executed_at == 1780854786039
            break


@pytest.mark.integration
async def test_rfq_session_quotes_explicit_inventory_size(
    require_env: Callable[[str], str],
) -> None:
    received: list[dict[str, Any]] = []

    async def handler(ws: ServerConnection) -> None:
        async for raw in ws:
            assert isinstance(raw, str)
            frame = json.loads(raw)
            received.append(frame)
            if frame["type"] == "auth":
                await ws.send(json.dumps({"type": "auth", "success": True}))
                await ws.send(json.dumps(_quote_request_message()))
            elif frame["type"] == "RFQ_QUOTE":
                await ws.send(json.dumps(_quote_ack_message()))

    async with (
        _ws_server(handler) as ws_url,
        _rfq_client(require_env, ws_url) as client,
        client.open_rfq_session() as session,
    ):
        async for event in session:
            assert isinstance(event, RfqQuoteRequestEvent)
            await event.quote(
                price=Decimal("0.45"),
                size=Decimal("0.5"),
                source=RfqQuoteSource.INVENTORY,
            )
            break

    quote = _first_frame(received, "RFQ_QUOTE")
    assert quote["size_e6"] == "500000"
    signed_order = quote["signed_order"]
    assert signed_order["tokenId"] == YES_POSITION_ID
    assert signed_order["side"] == 1
    assert signed_order["makerAmount"] == "500000"
    assert signed_order["takerAmount"] == "225000"


@pytest.mark.integration
async def test_rfq_session_normalizes_combo_condition_id_wire_form(
    require_env: Callable[[str], str],
) -> None:
    async def handler(ws: ServerConnection) -> None:
        async for raw in ws:
            assert isinstance(raw, str)
            frame = json.loads(raw)
            if frame["type"] == "auth":
                await ws.send(json.dumps({"type": "auth", "success": True}))
                await ws.send(json.dumps(_quote_request_message(condition_id=f"{CONDITION_ID}01")))

    async with (
        _ws_server(handler) as ws_url,
        _rfq_client(require_env, ws_url) as client,
        client.open_rfq_session() as session,
    ):
        async for event in session:
            assert isinstance(event, RfqQuoteRequestEvent)
            assert event.condition_id == CONDITION_ID
            break


@pytest.mark.integration
async def test_rfq_session_rejects_non_combo_condition_id(
    require_env: Callable[[str], str],
) -> None:
    async def handler(ws: ServerConnection) -> None:
        async for raw in ws:
            assert isinstance(raw, str)
            frame = json.loads(raw)
            if frame["type"] == "auth":
                await ws.send(json.dumps({"type": "auth", "success": True}))
                await ws.send(
                    json.dumps(
                        _quote_request_message(
                            condition_id="0x022def24bfb0c5c57fb236fac08b94236a0000000000000000000000000000"
                        )
                    )
                )

    async with (
        _ws_server(handler) as ws_url,
        _rfq_client(require_env, ws_url) as client,
        client.open_rfq_session() as session,
    ):
        with pytest.raises(UnexpectedResponseError, match="combo condition ID"):
            await session.__anext__()


@pytest.mark.integration
async def test_rfq_session_cancels_submitted_quote(
    require_env: Callable[[str], str],
) -> None:
    received: list[dict[str, Any]] = []

    async def handler(ws: ServerConnection) -> None:
        async for raw in ws:
            assert isinstance(raw, str)
            frame = json.loads(raw)
            received.append(frame)
            if frame["type"] == "auth":
                await ws.send(json.dumps({"type": "auth", "success": True}))
                await ws.send(json.dumps(_quote_request_message()))
            elif frame["type"] == "RFQ_QUOTE":
                await ws.send(json.dumps(_quote_ack_message()))
            elif frame["type"] == "RFQ_QUOTE_CANCEL":
                await ws.send(
                    json.dumps(
                        {
                            "type": "ACK_RFQ_QUOTE_CANCEL",
                            "rfq_id": RFQ_ID,
                            "quote_id": QUOTE_ID,
                        }
                    )
                )

    async with (
        _ws_server(handler) as ws_url,
        _rfq_client(require_env, ws_url) as client,
        client.open_rfq_session() as session,
    ):
        async for event in session:
            assert isinstance(event, RfqQuoteRequestEvent)
            quote = await event.quote(price=Decimal("0.45"))
            ack = await session.cancel_quote(quote)
            assert ack.rfq_id == RFQ_ID
            assert ack.quote_id == QUOTE_ID
            break

    cancel = _first_frame(received, "RFQ_QUOTE_CANCEL")
    assert cancel["rfq_id"] == RFQ_ID
    assert cancel["quote_id"] == QUOTE_ID
    assert cancel["maker_address"].lower() == require_env("POLYMARKET_DEPOSIT_WALLET").lower()


@pytest.mark.integration
async def test_rfq_session_declines_confirmation_request(
    require_env: Callable[[str], str],
) -> None:
    received: list[dict[str, Any]] = []

    async def handler(ws: ServerConnection) -> None:
        async for raw in ws:
            assert isinstance(raw, str)
            frame = json.loads(raw)
            received.append(frame)
            if frame["type"] == "auth":
                await ws.send(json.dumps({"type": "auth", "success": True}))
                await ws.send(json.dumps(_confirmation_request_message(_manual_quote_frame())))
            elif frame["type"] == "RFQ_CONFIRMATION_RESPONSE":
                await ws.send(
                    json.dumps(
                        {
                            "type": "ACK_RFQ_CONFIRMATION_RESPONSE",
                            "rfq_id": RFQ_ID,
                            "quote_id": QUOTE_ID,
                            "decision": frame["decision"],
                        }
                    )
                )

    async with (
        _ws_server(handler) as ws_url,
        _rfq_client(require_env, ws_url) as client,
        client.open_rfq_session() as session,
    ):
        async for event in session:
            assert isinstance(event, RfqConfirmationRequestEvent)
            ack = await event.decline()
            assert ack.rfq_id == RFQ_ID
            assert ack.quote_id == QUOTE_ID
            break

    confirmation = _first_frame(received, "RFQ_CONFIRMATION_RESPONSE")
    assert confirmation["decision"] == "DECLINE"


@pytest.mark.integration
async def test_rfq_session_auth_failure_raises_transport_error(
    require_env: Callable[[str], str],
) -> None:
    async def handler(ws: ServerConnection) -> None:
        async for raw in ws:
            assert isinstance(raw, str)
            frame = json.loads(raw)
            if frame["type"] == "auth":
                await ws.send(
                    json.dumps({"type": "auth", "success": False, "error": "bad credentials"})
                )

    async with _ws_server(handler) as ws_url, _rfq_client(require_env, ws_url) as client:
        with pytest.raises(TransportError, match="bad credentials"):
            async with client.open_rfq_session():
                pass


@pytest.mark.integration
@pytest.mark.parametrize(
    "code",
    [
        RfqErrorCode.ALLOWANCE_VALIDATION_FAILED,
        RfqErrorCode.BALANCE_VALIDATION_FAILED,
        RfqErrorCode.PRE_EXECUTION_BALANCE_RESERVATION_FAILED,
    ],
)
async def test_rfq_session_quote_rejection_raises_typed_error(
    require_env: Callable[[str], str],
    code: RfqErrorCode,
) -> None:
    async def handler(ws: ServerConnection) -> None:
        async for raw in ws:
            assert isinstance(raw, str)
            frame = json.loads(raw)
            if frame["type"] == "auth":
                await ws.send(json.dumps({"type": "auth", "success": True}))
                await ws.send(json.dumps(_quote_request_message()))
            elif frame["type"] == "RFQ_QUOTE":
                await ws.send(
                    json.dumps(
                        {
                            "type": "RFQ_ERROR",
                            "request_type": "RFQ_QUOTE",
                            "rfq_id": RFQ_ID,
                            "code": code,
                            "error": "quote rejected",
                        }
                    )
                )

    async with (
        _ws_server(handler) as ws_url,
        _rfq_client(require_env, ws_url) as client,
        client.open_rfq_session() as session,
    ):
        async for event in session:
            assert isinstance(event, RfqQuoteRequestEvent)
            with pytest.raises(RfqQuoteRejectedError, match="quote rejected") as exc_info:
                await event.quote(price=Decimal("0.45"))
            assert exc_info.value.code == code
            break


@pytest.mark.integration
async def test_rfq_session_resolves_same_key_quote_acks_fifo(
    require_env: Callable[[str], str],
) -> None:
    received_quotes = 0

    async def handler(ws: ServerConnection) -> None:
        nonlocal received_quotes
        async for raw in ws:
            assert isinstance(raw, str)
            frame = json.loads(raw)
            if frame["type"] == "auth":
                await ws.send(json.dumps({"type": "auth", "success": True}))
                await ws.send(json.dumps(_quote_request_message()))
            elif frame["type"] == "RFQ_QUOTE":
                received_quotes += 1
                if received_quotes == 2:
                    await ws.send(
                        json.dumps(
                            {
                                "type": "ACK_RFQ_QUOTE",
                                "rfq_id": RFQ_ID,
                                "quote_id": "quote-first",
                            }
                        )
                    )
                    await ws.send(
                        json.dumps(
                            {
                                "type": "ACK_RFQ_QUOTE",
                                "rfq_id": RFQ_ID,
                                "quote_id": "quote-second",
                            }
                        )
                    )

    async with (
        _ws_server(handler) as ws_url,
        _rfq_client(require_env, ws_url) as client,
        client.open_rfq_session() as session,
    ):
        event = await session.__anext__()
        assert isinstance(event, RfqQuoteRequestEvent)
        first = asyncio.create_task(event.quote(price=Decimal("0.45")))
        second = asyncio.create_task(event.quote(price=Decimal("0.46")))

        first_ack, second_ack = await asyncio.wait_for(asyncio.gather(first, second), timeout=1)

        assert first_ack.quote_id == "quote-first"
        assert second_ack.quote_id == "quote-second"
        assert cast(Any, session)._pending == {}


@pytest.mark.integration
async def test_rfq_session_uncorrelated_error_fails_session(
    require_env: Callable[[str], str],
) -> None:
    async def handler(ws: ServerConnection) -> None:
        async for raw in ws:
            assert isinstance(raw, str)
            frame = json.loads(raw)
            if frame["type"] == "auth":
                await ws.send(json.dumps({"type": "auth", "success": True}))
                await ws.send(json.dumps(_quote_request_message()))
            elif frame["type"] == "RFQ_QUOTE":
                await ws.send(
                    json.dumps(
                        {
                            "type": "RFQ_ERROR",
                            "request_type": "RFQ_QUOTE",
                            "code": "INVALID_QUOTE",
                            "error": "quote rejected",
                        }
                    )
                )

    async with (
        _ws_server(handler) as ws_url,
        _rfq_client(require_env, ws_url) as client,
        client.open_rfq_session() as session,
    ):
        async for event in session:
            assert isinstance(event, RfqQuoteRequestEvent)
            with pytest.raises(TransportError, match="Uncorrelated RFQ quoter error"):
                await event.quote(price=Decimal("0.45"))
            break


@pytest.mark.integration
async def test_rfq_session_ignores_unsupported_error_request_type(
    require_env: Callable[[str], str],
) -> None:
    async def handler(ws: ServerConnection) -> None:
        async for raw in ws:
            assert isinstance(raw, str)
            frame = json.loads(raw)
            if frame["type"] == "auth":
                await ws.send(json.dumps({"type": "auth", "success": True}))
                await ws.send(
                    json.dumps(
                        {
                            "type": "RFQ_ERROR",
                            "request_type": "RFQ_FUTURE_REQUEST",
                            "code": "REQUEST_FAILED",
                            "error": "future request failed",
                        }
                    )
                )
                await ws.send(json.dumps(_quote_request_message()))

    async with (
        _ws_server(handler) as ws_url,
        _rfq_client(require_env, ws_url) as client,
        client.open_rfq_session() as session,
    ):
        async for event in session:
            assert isinstance(event, RfqQuoteRequestEvent)
            assert event.rfq_id == RFQ_ID
            break


@pytest.mark.integration
async def test_rfq_session_rejects_unsupported_error_request_type_with_unknown_code(
    require_env: Callable[[str], str],
) -> None:
    async def handler(ws: ServerConnection) -> None:
        async for raw in ws:
            assert isinstance(raw, str)
            frame = json.loads(raw)
            if frame["type"] == "auth":
                await ws.send(json.dumps({"type": "auth", "success": True}))
                await ws.send(
                    json.dumps(
                        {
                            "type": "RFQ_ERROR",
                            "request_type": "RFQ_FUTURE_REQUEST",
                            "code": "FUTURE_ERROR_CODE",
                            "error": "future request failed",
                        }
                    )
                )

    async with (
        _ws_server(handler) as ws_url,
        _rfq_client(require_env, ws_url) as client,
        client.open_rfq_session() as session,
    ):
        with pytest.raises(UnexpectedResponseError, match="Unknown RFQ error code"):
            await session.__anext__()


@pytest.mark.integration
async def test_rfq_session_malformed_frame_fails_and_clears_client_session(
    require_env: Callable[[str], str],
) -> None:
    connection_count = 0

    async def handler(ws: ServerConnection) -> None:
        nonlocal connection_count
        connection_count += 1
        async for raw in ws:
            assert isinstance(raw, str)
            frame = json.loads(raw)
            if frame["type"] != "auth":
                continue
            await ws.send(json.dumps({"type": "auth", "success": True}))
            if connection_count == 1:
                await ws.send(json.dumps({"type": "RFQ_REQUEST", "rfq_id": RFQ_ID}))

    async with _ws_server(handler) as ws_url, _rfq_client(require_env, ws_url) as client:
        session = await client.open_rfq_session()
        with pytest.raises(UnexpectedResponseError, match="requestor_public_id"):
            await session.__anext__()

        next_session = await client.open_rfq_session()
        assert next_session is not session
        assert connection_count == 2


@pytest.mark.integration
async def test_rfq_session_reuses_existing_open_session(
    require_env: Callable[[str], str],
) -> None:
    connection_count = 0

    async def handler(ws: ServerConnection) -> None:
        nonlocal connection_count
        connection_count += 1
        async for raw in ws:
            assert isinstance(raw, str)
            frame = json.loads(raw)
            if frame["type"] == "auth":
                await ws.send(json.dumps({"type": "auth", "success": True}))

    async with (
        _ws_server(handler) as ws_url,
        _rfq_client(require_env, ws_url) as client,
        client.open_rfq_session() as first,
    ):
        second = await client.open_rfq_session()
        assert second is first
        assert connection_count == 1


@pytest.mark.integration
async def test_rfq_session_reuses_in_flight_open(
    require_env: Callable[[str], str],
) -> None:
    auth_received = asyncio.Event()
    allow_auth = asyncio.Event()
    connection_count = 0

    async def handler(ws: ServerConnection) -> None:
        nonlocal connection_count
        connection_count += 1
        async for raw in ws:
            assert isinstance(raw, str)
            frame = json.loads(raw)
            if frame["type"] == "auth":
                auth_received.set()
                await allow_auth.wait()
                await ws.send(json.dumps({"type": "auth", "success": True}))

    async with _ws_server(handler) as ws_url, _rfq_client(require_env, ws_url) as client:
        first_task = asyncio.create_task(client.open_rfq_session().__aenter__())
        await auth_received.wait()
        second_task = asyncio.create_task(client.open_rfq_session().__aenter__())
        await asyncio.sleep(0)
        assert connection_count == 1

        allow_auth.set()
        first, second = await asyncio.gather(first_task, second_task)
        assert first is second
        await first.close()


@pytest.mark.integration
async def test_rfq_session_close_client_closes_in_flight_open(
    require_env: Callable[[str], str],
) -> None:
    auth_received = asyncio.Event()
    connection_closed = asyncio.Event()

    async def handler(ws: ServerConnection) -> None:
        try:
            async for raw in ws:
                assert isinstance(raw, str)
                frame = json.loads(raw)
                if frame["type"] == "auth":
                    auth_received.set()
        finally:
            connection_closed.set()

    async with _ws_server(handler) as ws_url, _rfq_client(require_env, ws_url) as client:
        opening = asyncio.create_task(client.open_rfq_session().__aenter__())
        await auth_received.wait()

        await client.close()

        with pytest.raises(TransportError, match="RFQ quoter websocket closed"):
            await asyncio.wait_for(opening, timeout=1)
        await asyncio.wait_for(connection_closed.wait(), timeout=1)
        assert cast(Any, client)._rfq_session is None
        assert cast(Any, client)._rfq_session_connecting is None
        assert cast(Any, client)._rfq_session_opening is None


@pytest.mark.integration
async def test_rfq_session_close_client_closes_open_that_completes_during_close(
    require_env: Callable[[str], str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from polymarket._internal.rfq import RfqQuoterSession

    auth_received = asyncio.Event()
    auth_sent = asyncio.Event()
    close_started = asyncio.Event()
    allow_close = asyncio.Event()
    connection_closed = asyncio.Event()
    original_close = RfqQuoterSession.close

    async def delayed_close(self: RfqQuoterSession) -> None:
        if not close_started.is_set():
            close_started.set()
            await allow_close.wait()
        await original_close(self)

    monkeypatch.setattr(RfqQuoterSession, "close", delayed_close)

    async def handler(ws: ServerConnection) -> None:
        try:
            async for raw in ws:
                assert isinstance(raw, str)
                frame = json.loads(raw)
                if frame["type"] == "auth":
                    auth_received.set()
                    await close_started.wait()
                    await ws.send(json.dumps({"type": "auth", "success": True}))
                    auth_sent.set()
        finally:
            connection_closed.set()

    async with _ws_server(handler) as ws_url, _rfq_client(require_env, ws_url) as client:
        opening = asyncio.create_task(client.open_rfq_session().__aenter__())
        await auth_received.wait()

        closing = asyncio.create_task(client.close())
        await close_started.wait()
        await auth_sent.wait()
        allow_close.set()
        await asyncio.wait_for(closing, timeout=1)

        try:
            opened = await asyncio.wait_for(opening, timeout=1)
        except TransportError:
            pass
        else:
            assert cast(Any, opened).closed
        await asyncio.wait_for(connection_closed.wait(), timeout=1)
        assert cast(Any, client)._rfq_session is None
        assert cast(Any, client)._rfq_session_connecting is None
        assert cast(Any, client)._rfq_session_opening is None


@pytest.mark.integration
async def test_rfq_session_opens_fresh_session_after_close(
    require_env: Callable[[str], str],
) -> None:
    connection_count = 0

    async def handler(ws: ServerConnection) -> None:
        nonlocal connection_count
        connection_count += 1
        async for raw in ws:
            assert isinstance(raw, str)
            frame = json.loads(raw)
            if frame["type"] == "auth":
                await ws.send(json.dumps({"type": "auth", "success": True}))

    async with _ws_server(handler) as ws_url, _rfq_client(require_env, ws_url) as client:
        first = await client.open_rfq_session()
        await first.close()

        second = await client.open_rfq_session()
        assert second is not first
        assert connection_count == 2


def _quote_request_message(*, condition_id: str = CONDITION_ID) -> dict[str, object]:
    return {
        "type": "RFQ_REQUEST",
        "rfq_id": RFQ_ID,
        "requestor_public_id": "requestor-abc",
        "leg_position_ids": [YES_POSITION_ID, NO_POSITION_ID],
        "condition_id": condition_id,
        "yes_position_id": YES_POSITION_ID,
        "no_position_id": NO_POSITION_ID,
        "direction": "BUY",
        "side": "YES",
        "requested_size": {"unit": "notional", "value_e6": "1000000"},
        "submission_deadline": 1780805856000,
    }


def _confirmation_request_message(quote: dict[str, Any]) -> dict[str, object]:
    signed_order = quote["signed_order"]
    return {
        "type": "RFQ_CONFIRMATION_REQUEST",
        "rfq_id": RFQ_ID,
        "quote_id": QUOTE_ID,
        "signer_address": signed_order["signer"],
        "maker_address": signed_order["maker"],
        "signature_type": signed_order["signatureType"],
        "leg_position_ids": [YES_POSITION_ID, NO_POSITION_ID],
        "condition_id": CONDITION_ID,
        "yes_position_id": YES_POSITION_ID,
        "no_position_id": NO_POSITION_ID,
        "direction": "BUY",
        "side": "YES",
        "fill_size_e6": quote["size_e6"],
        "price_e6": quote["price_e6"],
        "confirm_by": 1780805866000,
    }


def _quote_ack_message() -> dict[str, object]:
    return {
        "type": "ACK_RFQ_QUOTE",
        "rfq_id": RFQ_ID,
        "quote_id": QUOTE_ID,
    }


def _manual_quote_frame() -> dict[str, Any]:
    return {
        "type": "RFQ_QUOTE",
        "rfq_id": RFQ_ID,
        "quote_id": QUOTE_ID,
        "price_e6": "450000",
        "size_e6": "500000",
        "signed_order": {
            "maker": "0x0000000000000000000000000000000000000001",
            "signer": "0x0000000000000000000000000000000000000001",
            "signatureType": 0,
        },
    }


def _trade_message() -> dict[str, object]:
    return {
        "type": "RFQ_TRADE",
        "rfq_id": RFQ_ID,
        "requestor_public_id": "requestor-abc",
        "condition_id": CONDITION_ID,
        "leg_position_ids": [YES_POSITION_ID, NO_POSITION_ID],
        "direction": "BUY",
        "side": "YES",
        "price_e6": "125000",
        "size_e6": "800000",
        "tx_hash": TX_HASH,
        "executed_at": 1780854786039,
    }


def _first_frame(frames: list[dict[str, Any]], frame_type: str) -> dict[str, Any]:
    for frame in frames:
        if frame.get("type") == frame_type:
            return frame
    raise AssertionError(f"No {frame_type} frame recorded")
