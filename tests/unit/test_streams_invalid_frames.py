# pyright: reportPrivateUsage=false
"""Frames a stream does not recognize are dropped without closing the
connection: after an invalid frame, a valid frame must still be delivered
on the same socket."""

import asyncio
import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, cast

from eth_account import Account
from eth_account.signers.local import LocalAccount
from websockets.asyncio.server import ServerConnection, serve

from polymarket._internal.perps_session import PerpsSession
from polymarket._internal.rfq import RfqQuoterSession
from polymarket._internal.streams.clob.market import ClobMarketStreamManager
from polymarket._internal.streams.clob.user import ClobUserStreamManager
from polymarket._internal.streams.perps.market import PerpsMarketStreamManager
from polymarket._internal.streams.rtds.manager import RtdsStreamManager
from polymarket._internal.streams.sports.manager import SportsStreamManager
from polymarket.errors import TransportError
from polymarket.models import ApiKeyCreds
from polymarket.models.perps.credentials import PerpsCredentials
from polymarket.rfq import RfqExecutionStatus, RfqExecutionUpdateEvent
from polymarket.streams import PerpsBookSpec
from polymarket.types import EvmAddress

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


_INVALID_FRAME: dict[str, Any] = {"event_type": "future_event", "payload": "new"}


async def _next_event(handle: Any, *, timeout_s: float = 2.0) -> Any:
    return await asyncio.wait_for(handle.__aiter__().__anext__(), timeout=timeout_s)


def test_clob_market_drops_invalid_frame_and_keeps_socket_open() -> None:
    async def handler(ws: ServerConnection) -> None:
        await ws.recv()
        await ws.send(json.dumps(_INVALID_FRAME))
        await ws.send(
            json.dumps(
                {"event_type": "book", "market": "m", "asset_id": "a", "bids": [], "asks": []}
            )
        )
        async for _ in ws:
            pass

    async def run() -> Any:
        async with ws_server(handler) as url:
            mgr = ClobMarketStreamManager(url=url)
            try:
                handle = await mgr.subscribe(token_ids=["a"])
                # Receiving the valid frame sent after the invalid one proves
                # the connection and the subscription survived, and that the
                # invalid frame emitted no event.
                event = await _next_event(handle)
                await handle.close()
                return event
            finally:
                await mgr.close()

    event = asyncio.run(run())
    assert event.type == "book"


def test_clob_user_drops_invalid_frame_and_keeps_socket_open() -> None:
    creds = ApiKeyCreds(key="k", secret="s", passphrase="p")

    async def resolve() -> ApiKeyCreds:
        return creds

    async def handler(ws: ServerConnection) -> None:
        await ws.recv()
        await ws.send(json.dumps(_INVALID_FRAME))
        await ws.send(
            json.dumps(
                {
                    "event_type": "order",
                    "id": "ord-1",
                    "owner": "0xowner",
                    "market": "m1",
                    "asset_id": "tid",
                    "side": "BUY",
                    "original_size": "1",
                    "size_matched": "0",
                    "price": "0.5",
                    "type": "PLACEMENT",
                    "timestamp": "1710000000000",
                }
            )
        )
        async for _ in ws:
            pass

    async def run() -> Any:
        async with ws_server(handler) as url:
            mgr = ClobUserStreamManager(url=url, resolve_credentials=resolve)
            try:
                handle = await mgr.subscribe(markets=["m1"])
                event = await _next_event(handle)
                await handle.close()
                return event
            finally:
                await mgr.close()

    event = asyncio.run(run())
    assert event.type == "order"


def test_rtds_drops_invalid_frame_and_keeps_socket_open() -> None:
    invalid = {"topic": "future_topic", "type": "update", "payload": {"hello": "world"}}

    async def handler(ws: ServerConnection) -> None:
        await ws.recv()
        await ws.send(json.dumps(invalid))
        await ws.send(
            json.dumps(
                {
                    "topic": "crypto_prices",
                    "type": "update",
                    "timestamp": "1710000000000",
                    "payload": {"symbol": "btcusdt", "timestamp": 1710000000000, "value": "1.0"},
                }
            )
        )
        async for _ in ws:
            pass

    async def run() -> tuple[int, Any]:
        from polymarket.streams import CryptoPricesSpec

        async with ws_server(handler) as url:
            mgr = RtdsStreamManager(url=url)
            try:
                handle = await mgr.subscribe(CryptoPricesSpec(topic="prices.crypto.binance"))
                event = await _next_event(handle)
                await handle.close()
                return mgr.dropped_events, event
            finally:
                await mgr.close()

    dropped, event = asyncio.run(run())
    assert dropped == 1
    assert event.type == "update"


def test_sports_drops_invalid_frame_and_keeps_socket_open() -> None:
    async def handler(ws: ServerConnection) -> None:
        await ws.send(json.dumps(_INVALID_FRAME))
        await ws.send(
            json.dumps(
                {
                    "gameId": 1,
                    "leagueAbbreviation": "NBA",
                    "status": "live",
                    "live": True,
                    "ended": False,
                    "score": "0-0",
                }
            )
        )
        async for _ in ws:
            pass

    async def run() -> tuple[int, Any]:
        async with ws_server(handler) as url:
            mgr = SportsStreamManager(url=url)
            try:
                handle = await mgr.subscribe()
                event = await _next_event(handle)
                await handle.close()
                return mgr.dropped_events, event
            finally:
                await mgr.close()

    dropped, event = asyncio.run(run())
    assert dropped == 1
    assert event.type == "sport_result"


def test_perps_market_drops_invalid_frames_and_ignores_request_responses() -> None:
    invalid: dict[str, Any] = {"ch": "future_channel::1", "ts": 1751500000000, "sq": 1, "data": {}}

    async def handler(ws: ServerConnection) -> None:
        message = json.loads(await ws.recv())
        # Acknowledge the subscribe request: responses echoing the request id
        # are expected control frames and must not emit events.
        await ws.send(json.dumps({"id": message["id"], "data": {"status": "ok"}}))
        await ws.send(json.dumps(invalid))
        await ws.send(
            json.dumps(
                {
                    "ch": "book::1",
                    "ts": 1751500000000,
                    "sq": 2,
                    "data": {"b": [["0.5", "10"]], "a": [["0.6", "4"]]},
                }
            )
        )
        async for _ in ws:
            pass

    async def run() -> Any:
        async with ws_server(handler) as url:
            mgr = PerpsMarketStreamManager(url=url)
            try:
                handle = await mgr.subscribe(PerpsBookSpec(instrument_id=1))
                event = await _next_event(handle)
                await handle.close()
                return event
            finally:
                await mgr.close()

    event = asyncio.run(run())
    assert event.type == "book"


def test_perps_session_drops_invalid_frame_and_keeps_session_open() -> None:
    invalid: dict[str, Any] = {"ch": "future_channel", "ts": 1751500000000, "sq": 1, "data": {}}
    balance = {
        "ch": "balances",
        "ts": 1751500000000,
        "sq": 1,
        "data": {"asset": "USDC", "balance": "1", "value": "1"},
    }

    async def handler(ws: ServerConnection) -> None:
        handshakes = 0
        async for raw in ws:
            message = json.loads(raw)
            if message.get("id") == 0:
                continue
            await ws.send(json.dumps({"id": message["id"], "data": {"status": "ok"}}))
            handshakes += 1
            if handshakes == 2:
                await ws.send(json.dumps(invalid))
                await ws.send(json.dumps(balance))

    async def run() -> Any:
        async with ws_server(handler) as url:
            session = PerpsSession(
                chain_id=137,
                credentials=PerpsCredentials(
                    proxy="0x14791697260E4c9A71f18484C9f997B308e59325",
                    private_key=(
                        "0x0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                    ),
                    secret="session-secret",
                    expires_at=datetime(2030, 1, 1, tzinfo=UTC),
                ),
                rest_url="http://127.0.0.1:9",  # unused by this test
                ws_url=url,
            )
            try:
                await session.open()
                # The balance event arriving after the invalid frame proves
                # the session survived and the invalid frame was dropped.
                return await asyncio.wait_for(session.__anext__(), timeout=2.0)
            finally:
                await session.close()

    event = asyncio.run(asyncio.wait_for(run(), timeout=10.0))
    assert event.type == "balance"


def _quoter_session() -> RfqQuoterSession:
    signer = cast(LocalAccount, Account.create())
    return RfqQuoterSession(
        chain_id=137,
        credentials=ApiKeyCreds(key="k", secret="s", passphrase="p"),
        exchange=EvmAddress("0x0000000000000000000000000000000000000001"),
        headers=None,
        logger=None,
        signer=signer,
        url="ws://127.0.0.1:9",  # never connected by these tests
        wallet=EvmAddress(signer.address),
        wallet_type="EOA",
    )


def test_rfq_quoter_drops_unknown_message_types_and_stays_open() -> None:
    async def run() -> tuple[int, bool]:
        session = _quoter_session()
        session._on_message({"type": "RFQ_FUTURE_MESSAGE", "payload": "ignored"})
        session._on_message(["not", "a", "dict"])
        session._on_message({"payload": "missing type"})
        return session._queue.qsize(), session.closed

    queued, closed = asyncio.run(run())
    assert queued == 0
    assert closed is False


def test_rfq_quoter_drops_malformed_known_frames_and_stays_open() -> None:
    # A known message type with an unreadable payload must not end the
    # session; the pending acknowledgement fails through its timeout instead.
    malformed = {"type": "ACK_RFQ_QUOTE", "rfq_id": "rfq-1"}

    async def run() -> tuple[int, bool]:
        session = _quoter_session()
        session._on_message(malformed)
        return session._queue.qsize(), session.closed

    queued, closed = asyncio.run(run())
    assert queued == 0
    assert closed is False


def test_rfq_quoter_drops_frames_with_unmodeled_field_values_and_stays_open() -> None:
    # A known message type whose field carries a value the SDK does not model
    # (here a direction enum the client predates) must be dropped, not end
    # the session.
    trade = {
        "type": "RFQ_TRADE",
        "rfq_id": "rfq-1",
        "requester_id": "req-1",
        "condition_id": "0x" + "11" * 32,
        "leg_position_ids": ["1"],
        "direction": "FUTURE_DIRECTION",
        "side": "BUY",
        "price_e6": "500000",
        "size_e6": "1000000",
        "executed_at": 1751500000,
    }

    async def run() -> tuple[int, bool]:
        session = _quoter_session()
        session._on_message(trade)
        return session._queue.qsize(), session.closed

    queued, closed = asyncio.run(run())
    assert queued == 0
    assert closed is False


def test_rfq_quoter_drops_execution_updates_with_unmodeled_statuses() -> None:
    # An execution update whose status the SDK does not model is dropped
    # without ending the session; later readable updates are still delivered.
    async def run() -> tuple[int, bool, object]:
        session = _quoter_session()
        session._on_message(
            {"type": "RFQ_EXECUTION_UPDATE", "rfq_id": "rfq-1", "status": "FUTURE_STATUS"}
        )
        queued_after_drop = session._queue.qsize()
        session._on_message(
            {"type": "RFQ_EXECUTION_UPDATE", "rfq_id": "rfq-1", "status": "CONFIRMED"}
        )
        return queued_after_drop, session.closed, session._queue.get_nowait()

    queued_after_drop, closed, event = asyncio.run(run())
    assert queued_after_drop == 0
    assert closed is False
    assert isinstance(event, RfqExecutionUpdateEvent)
    assert event.status is RfqExecutionStatus.CONFIRMED


def test_rfq_quoter_still_fails_on_uncorrelated_error_frames() -> None:
    # Deliberate exception to the invalid-frame policy: a well-formed
    # RFQ_ERROR that cannot be correlated to a request still ends the session.
    async def run() -> tuple[bool, BaseException | None]:
        session = _quoter_session()
        session._on_message(
            {
                "type": "RFQ_ERROR",
                "request_type": "RFQ_QUOTE",
                "code": "REQUEST_FAILED",
                "error": "boom",
            }
        )
        await asyncio.sleep(0)  # let _fail's connection-close task run
        return session.closed, session._end_error

    closed, error = asyncio.run(run())
    assert closed is True
    assert isinstance(error, TransportError)
