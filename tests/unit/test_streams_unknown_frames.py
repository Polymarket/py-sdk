# pyright: reportPrivateUsage=false
"""Unknown frames are surfaced through ``on_unknown_frame`` and never close
the connection: after an unrecognized frame, a valid frame must still be
delivered on the same socket."""

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
from polymarket.rfq import RfqExecutionUpdateEvent
from polymarket.streams import PerpsBookSpec, UnknownFrame
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


_UNKNOWN_FRAME: dict[str, Any] = {"event_type": "future_event", "payload": "new"}


async def _next_event(handle: Any, *, timeout_s: float = 2.0) -> Any:
    return await asyncio.wait_for(handle.__aiter__().__anext__(), timeout=timeout_s)


def test_clob_market_surfaces_unknown_frame_and_keeps_socket_open() -> None:
    async def handler(ws: ServerConnection) -> None:
        await ws.recv()
        await ws.send(json.dumps(_UNKNOWN_FRAME))
        await ws.send(
            json.dumps(
                {"event_type": "book", "market": "m", "asset_id": "a", "bids": [], "asks": []}
            )
        )
        async for _ in ws:
            pass

    async def run() -> tuple[list[UnknownFrame], int, Any]:
        seen: list[UnknownFrame] = []
        async with ws_server(handler) as url:
            mgr = ClobMarketStreamManager(url=url, on_unknown_frame=seen.append)
            try:
                handle = await mgr.subscribe(token_ids=["a"])
                # Receiving the valid frame sent after the unknown one proves
                # the connection and the subscription survived.
                event = await _next_event(handle)
                await handle.close()
                return seen, mgr.dropped_events, event
            finally:
                await mgr.close()

    seen, dropped, event = asyncio.run(run())
    assert seen == [UnknownFrame(frame=_UNKNOWN_FRAME, stream="clob_market")]
    assert dropped == 1
    assert event.type == "book"


def test_clob_user_surfaces_unknown_frame_and_keeps_socket_open() -> None:
    creds = ApiKeyCreds(key="k", secret="s", passphrase="p")

    async def resolve() -> ApiKeyCreds:
        return creds

    async def handler(ws: ServerConnection) -> None:
        await ws.recv()
        await ws.send(json.dumps(_UNKNOWN_FRAME))
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

    async def run() -> tuple[list[UnknownFrame], Any]:
        seen: list[UnknownFrame] = []
        async with ws_server(handler) as url:
            mgr = ClobUserStreamManager(
                url=url, resolve_credentials=resolve, on_unknown_frame=seen.append
            )
            try:
                handle = await mgr.subscribe(markets=["m1"])
                event = await _next_event(handle)
                await handle.close()
                return seen, event
            finally:
                await mgr.close()

    seen, event = asyncio.run(run())
    assert seen == [UnknownFrame(frame=_UNKNOWN_FRAME, stream="clob_user")]
    assert event.type == "order"


def test_rtds_surfaces_unknown_frame_and_keeps_socket_open() -> None:
    unknown = {"topic": "future_topic", "type": "update", "payload": {"hello": "world"}}

    async def handler(ws: ServerConnection) -> None:
        await ws.recv()
        await ws.send(json.dumps(unknown))
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

    async def run() -> tuple[list[UnknownFrame], Any]:
        from polymarket.streams import CryptoPricesSpec

        seen: list[UnknownFrame] = []
        async with ws_server(handler) as url:
            mgr = RtdsStreamManager(url=url, on_unknown_frame=seen.append)
            try:
                handle = await mgr.subscribe(CryptoPricesSpec(topic="prices.crypto.binance"))
                event = await _next_event(handle)
                await handle.close()
                return seen, event
            finally:
                await mgr.close()

    seen, event = asyncio.run(run())
    assert seen == [UnknownFrame(frame=unknown, stream="rtds")]
    assert event.type == "update"


def test_sports_surfaces_unknown_frame_and_keeps_socket_open() -> None:
    async def handler(ws: ServerConnection) -> None:
        await ws.send(json.dumps(_UNKNOWN_FRAME))
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

    async def run() -> tuple[list[UnknownFrame], Any]:
        seen: list[UnknownFrame] = []
        async with ws_server(handler) as url:
            mgr = SportsStreamManager(url=url, on_unknown_frame=seen.append)
            try:
                handle = await mgr.subscribe()
                event = await _next_event(handle)
                await handle.close()
                return seen, event
            finally:
                await mgr.close()

    seen, event = asyncio.run(run())
    assert seen == [UnknownFrame(frame=_UNKNOWN_FRAME, stream="sports")]
    assert event.type == "sport_result"


def test_perps_market_surfaces_unknown_frame_but_not_request_responses() -> None:
    unknown: dict[str, Any] = {"ch": "future_channel::1", "ts": 1751500000000, "sq": 1, "data": {}}

    async def handler(ws: ServerConnection) -> None:
        message = json.loads(await ws.recv())
        # Acknowledge the subscribe request: responses echoing the request id
        # are expected control frames and must not be reported as unknown.
        await ws.send(json.dumps({"id": message["id"], "data": {"status": "ok"}}))
        await ws.send(json.dumps(unknown))
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

    async def run() -> tuple[list[UnknownFrame], Any]:
        seen: list[UnknownFrame] = []
        async with ws_server(handler) as url:
            mgr = PerpsMarketStreamManager(url=url, on_unknown_frame=seen.append)
            try:
                handle = await mgr.subscribe(PerpsBookSpec(instrument_id=1))
                event = await _next_event(handle)
                await handle.close()
                return seen, event
            finally:
                await mgr.close()

    seen, event = asyncio.run(run())
    assert seen == [UnknownFrame(frame=unknown, stream="perps_market")]
    assert event.type == "book"


def test_perps_session_surfaces_unknown_frame_and_keeps_session_open() -> None:
    unknown: dict[str, Any] = {"ch": "future_channel", "ts": 1751500000000, "sq": 1, "data": {}}
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
                await ws.send(json.dumps(unknown))
                await ws.send(json.dumps(balance))

    async def run() -> tuple[list[UnknownFrame], Any]:
        seen: list[UnknownFrame] = []
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
                on_unknown_frame=seen.append,
            )
            try:
                await session.open()
                event = await asyncio.wait_for(session.__anext__(), timeout=2.0)
                return seen, event
            finally:
                await session.close()

    seen, event = asyncio.run(asyncio.wait_for(run(), timeout=10.0))
    assert seen == [UnknownFrame(frame=unknown, stream="perps_session")]
    assert event.type == "balance"


def _quoter_session(seen: list[UnknownFrame]) -> RfqQuoterSession:
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
        on_unknown_frame=seen.append,
    )


def test_rfq_quoter_surfaces_unknown_message_types_and_stays_open() -> None:
    async def run() -> tuple[list[UnknownFrame], bool]:
        seen: list[UnknownFrame] = []
        session = _quoter_session(seen)
        session._on_message({"type": "RFQ_FUTURE_MESSAGE", "payload": "ignored"})
        session._on_message(["not", "a", "dict"])
        session._on_message({"payload": "missing type"})
        return seen, session.closed

    seen, closed = asyncio.run(run())
    assert [unknown.frame for unknown in seen] == [
        {"type": "RFQ_FUTURE_MESSAGE", "payload": "ignored"},
        ["not", "a", "dict"],
        {"payload": "missing type"},
    ]
    assert all(unknown.stream == "rfq_quoter" for unknown in seen)
    assert closed is False


def test_rfq_quoter_surfaces_malformed_known_frames_and_stays_open() -> None:
    # A known message type with an unreadable payload must not end the
    # session; the pending acknowledgement fails through its timeout instead.
    malformed = {"type": "ACK_RFQ_QUOTE", "rfq_id": "rfq-1"}

    async def run() -> tuple[list[UnknownFrame], bool]:
        seen: list[UnknownFrame] = []
        session = _quoter_session(seen)
        session._on_message(malformed)
        return seen, session.closed

    seen, closed = asyncio.run(run())
    assert seen == [UnknownFrame(frame=malformed, stream="rfq_quoter")]
    assert closed is False


def test_rfq_quoter_delivers_execution_updates_with_future_statuses() -> None:
    async def run() -> tuple[list[UnknownFrame], object]:
        seen: list[UnknownFrame] = []
        session = _quoter_session(seen)
        session._on_message(
            {"type": "RFQ_EXECUTION_UPDATE", "rfq_id": "rfq-1", "status": "FUTURE_STATUS"}
        )
        return seen, session._queue.get_nowait()

    seen, event = asyncio.run(run())
    assert seen == []
    assert isinstance(event, RfqExecutionUpdateEvent)
    assert event.status == "FUTURE_STATUS"


def test_rfq_quoter_still_fails_on_uncorrelated_error_frames() -> None:
    # Deliberate exception to the unknown-frame policy: a well-formed
    # RFQ_ERROR that cannot be correlated to a request still ends the session.
    async def run() -> tuple[list[UnknownFrame], bool, BaseException | None]:
        seen: list[UnknownFrame] = []
        session = _quoter_session(seen)
        session._on_message(
            {
                "type": "RFQ_ERROR",
                "request_type": "RFQ_QUOTE",
                "code": "REQUEST_FAILED",
                "error": "boom",
            }
        )
        await asyncio.sleep(0)  # let _fail's connection-close task run
        return seen, session.closed, session._end_error

    seen, closed, error = asyncio.run(run())
    assert seen == []
    assert closed is True
    assert isinstance(error, TransportError)


def test_unknown_frame_callback_errors_are_isolated() -> None:
    async def handler(ws: ServerConnection) -> None:
        await ws.recv()
        await ws.send(json.dumps(_UNKNOWN_FRAME))
        await ws.send(
            json.dumps(
                {"event_type": "book", "market": "m", "asset_id": "a", "bids": [], "asks": []}
            )
        )
        async for _ in ws:
            pass

    async def run() -> Any:
        def explode(unknown: UnknownFrame) -> None:
            raise RuntimeError("consumer callback bug")

        async with ws_server(handler) as url:
            mgr = ClobMarketStreamManager(url=url, on_unknown_frame=explode)
            try:
                handle = await mgr.subscribe(token_ids=["a"])
                event = await _next_event(handle)
                await handle.close()
                return event
            finally:
                await mgr.close()

    event = asyncio.run(run())
    assert event.type == "book"
