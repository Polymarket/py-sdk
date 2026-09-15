# pyright: reportPrivateUsage=false
import asyncio
import json
import time
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

import pytest
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from polymarket import ApiKeyCreds, AsyncPublicClient, AsyncSecureClient
from polymarket._internal.environment import PRODUCTION_CONFIG, create_environment
from polymarket._internal.streams.realtime import heartbeat as heartbeat_module
from polymarket._internal.streams.realtime import session as session_module
from polymarket._internal.streams.realtime import socket as socket_module
from polymarket._internal.streams.realtime.manager import RealtimeStreamManager
from polymarket._internal.streams.realtime.protocol import parse_price_event, refresh_snapshot
from polymarket.errors import (
    ConnectionLostError,
    RequestRejectedError,
    TransportError,
    UserInputError,
)
from polymarket.streams import (
    CryptoPriceSpec,
    CryptoTwapPriceSpec,
    EquityPriceSpec,
    MarketSpec,
)

CREDS = ApiKeyCreds(key="test-key", secret="test-secret", passphrase="test-pass")
# Deterministic dummy signer, shared by existing SDK tests; never a live credential.
PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
WALLET = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
TIMESTAMP = 1788886176000
EXACT = "78803.761731790000000001"


def price_frame(
    channel: str = "price.crypto",
    symbol: str = "btcusd",
    *,
    snapshot: bool = False,
    timestamp: int = TIMESTAMP,
) -> dict[str, Any]:
    point = {"timestamp": timestamp, "value": 78803.76, "full_accuracy_value": EXACT}
    payload: dict[str, Any] = (
        {"symbol": symbol, "data": [point]} if snapshot else {"symbol": symbol, **point}
    )
    if channel == "price.crypto.twap":
        payload["window_seconds"] = 60
    return {
        "v": 1,
        "channel": channel,
        "seq": 1,
        "ts": timestamp,
        "snapshot": snapshot,
        "payload": payload,
    }


class Feed:
    """Local protocol peer; failures isolate wire and lifecycle boundaries."""

    def __init__(self) -> None:
        self.connections: list[ServerConnection] = []
        self.frames: list[dict[str, Any]] = []
        self.received_times: list[float] = []
        self.reject_symbols: set[str] = set()
        self.auth_errors: list[str] = []
        self.ack_gate: asyncio.Event | None = None
        self.ignore_subscriptions = 0
        self.ignore_unsubscriptions = 0
        self.auth_close_code: int | None = None

    async def handler(self, ws: ServerConnection) -> None:
        self.connections.append(ws)
        try:
            async for raw in ws:
                frame = json.loads(raw)
                self.frames.append(frame)
                self.received_times.append(time.monotonic())
                if frame["op"] == "auth":
                    if self.auth_close_code is not None:
                        await ws.close(self.auth_close_code, "authorization closed")
                        return
                    assert frame["auth"] == {
                        "apiKey": "test-key",
                        "secret": "test-secret",
                        "passphrase": "test-pass",
                    }
                    if self.auth_errors:
                        await ws.send(
                            json.dumps(
                                {
                                    "op": "error",
                                    "rid": frame["rid"],
                                    "code": self.auth_errors.pop(0),
                                }
                            )
                        )
                    else:
                        await ws.send(json.dumps({"op": "authed", "rid": frame["rid"]}))
                elif frame["op"] in ("subscribe", "unsubscribe"):
                    if frame["op"] == "subscribe":
                        if self.ignore_subscriptions:
                            self.ignore_subscriptions -= 1
                            continue
                        if self.ack_gate is not None:
                            await self.ack_gate.wait()
                    elif self.ignore_unsubscriptions:
                        self.ignore_unsubscriptions -= 1
                        continue
                    for sub in frame["subscriptions"]:
                        channel, symbol = sub["channel"], sub["filter"]["symbol"]
                        op = "subscribed" if frame["op"] == "subscribe" else "unsubscribed"
                        ack = {"op": op, "rid": frame["rid"], "channel": channel}
                        if op == "subscribed" and symbol in self.reject_symbols:
                            ack.update(op="error", code="bad_filter")
                        await ws.send(json.dumps(ack))
                        if ack["op"] == "subscribed":
                            await ws.send(json.dumps(price_frame(channel, symbol, snapshot=True)))
        except ConnectionClosed:
            pass

    def operations(self, op: str) -> list[dict[str, Any]]:
        return [frame for frame in self.frames if frame["op"] == op]


@asynccontextmanager
async def feed_server(feed: Feed) -> AsyncGenerator[str, None]:
    async with serve(feed.handler, "127.0.0.1", 0) as server:
        port = next(iter(server.sockets)).getsockname()[1]
        yield f"ws://127.0.0.1:{port}"


async def eventually(predicate: Callable[[], bool]) -> None:
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.005)


@pytest.fixture(autouse=True)
def fast_protocol(monkeypatch: pytest.MonkeyPatch) -> None:
    def delay(code: int, attempt: int) -> float:
        return 0.01

    monkeypatch.setattr(socket_module, "OPERATION_INTERVAL_S", 0.001)
    monkeypatch.setattr(session_module, "reconnect_delay", delay)


@pytest.mark.parametrize("channel", ["price.crypto", "price.crypto.twap", "price.equity"])
@pytest.mark.parametrize("snapshot", [False, True])
def test_price_frames_preserve_exact_values_and_public_types(channel: str, snapshot: bool) -> None:
    frame = price_frame(channel, snapshot=snapshot)
    frame["dropped"] = 0
    if not snapshot and channel == "price.equity":
        frame["payload"].update(received_at=0, is_carried_forward=False)
    event = parse_price_event(frame)
    assert event is not None
    assert event.timestamp == datetime.fromtimestamp(TIMESTAMP / 1000, UTC)
    assert event.seq == 1 and event.dropped == 0
    point = event.payload.data[0] if event.type == "subscribe" else event.payload
    assert point.value == Decimal(EXACT)
    assert point.timestamp.tzinfo is UTC
    if event.topic == "prices.crypto.twap":
        assert event.payload.window_seconds == 60
    if event.topic == "prices.equity" and event.type == "update":
        assert event.payload.received_at == datetime(1970, 1, 1, tzinfo=UTC)
        assert event.payload.is_carried_forward is False


@pytest.mark.parametrize(
    "change",
    [
        {"v": 2},
        {"v": True},
        {"seq": -1},
        {"seq": True},
        {"snapshot": "yes"},
        {"channel": "price.future"},
        {"dropped": -1},
        {"ts": 1.5},
        {"payload": {}},
    ],
)
def test_malformed_or_future_frames_are_dropped(change: dict[str, object]) -> None:
    assert parse_price_event({**price_frame(), **change}) is None


@pytest.mark.parametrize("value", [None, 3, "NaN", "Infinity", "not-a-price"])
def test_price_requires_exact_decimal_string(value: object) -> None:
    frame = price_frame()
    frame["payload"]["full_accuracy_value"] = value
    assert parse_price_event(frame) is None


def test_history_replaces_same_timestamp_and_ignores_older_updates() -> None:
    old = parse_price_event(price_frame(snapshot=True, timestamp=TIMESTAMP - 120001))
    current = parse_price_event(price_frame())
    assert old is not None and current is not None
    history = refresh_snapshot(old, current)
    assert history is not None and history.type == "subscribe"
    assert len(history.payload.data) == 1
    assert refresh_snapshot(history, current) == history
    older = parse_price_event(price_frame(timestamp=TIMESTAMP - 1))
    assert older is not None and refresh_snapshot(history, older) == history


@pytest.mark.parametrize(
    ("spec_type", "symbols"),
    [
        (CryptoPriceSpec, []),
        (CryptoTwapPriceSpec, "btcusd"),
        (CryptoPriceSpec, None),
        (CryptoTwapPriceSpec, ["BTCUSD"]),
        (CryptoPriceSpec, ["btc/usd"]),
        (CryptoTwapPriceSpec, ["btcusdt"]),
        (CryptoPriceSpec, [" btcusd"]),
        (CryptoTwapPriceSpec, [1]),
        (CryptoPriceSpec, ["x" * 65]),
    ],
)
def test_canonical_crypto_symbols_are_validated(symbols: Any, spec_type: Any) -> None:
    with pytest.raises(UserInputError):
        spec_type(symbols=symbols)


def test_public_client_rejects_entire_authenticated_batch_before_opening() -> None:
    async def run() -> None:
        async with AsyncPublicClient() as client:
            with pytest.raises(UserInputError, match="AsyncSecureClient"):
                await client.subscribe(
                    cast(Any, [MarketSpec(asset_ids=["1"]), CryptoPriceSpec(symbols=["btcusd"])])
                )
            assert client._market_manager is None

    asyncio.run(run())


def test_failed_client_batch_rolls_back_its_handles_and_preserves_existing_stream() -> None:
    async def run() -> None:
        feed = Feed()
        feed.reject_symbols.add("badusd")
        async with feed_server(feed) as url:
            environment = create_environment(
                name="test", config=replace(PRODUCTION_CONFIG, realtime_ws_url=url)
            )
            client = await AsyncSecureClient._create(
                private_key=PRIVATE_KEY,
                wallet=WALLET,
                credentials=CREDS,
                environment=environment,
                validate_credentials=False,
            )
            async with client:
                existing = await client.subscribe(EquityPriceSpec(symbol="aapl"))
                await anext(existing)
                with pytest.raises(RequestRejectedError):
                    await client.subscribe(
                        [
                            CryptoPriceSpec(symbols=["btcusd"]),
                            CryptoPriceSpec(symbols=["badusd"]),
                        ]
                    )
                # The accepted portion of the failed batch must be unsubscribed.
                await eventually(lambda: bool(feed.operations("unsubscribe")))
                assert feed.operations("unsubscribe")[0]["subscriptions"] == [
                    {"channel": "price.crypto", "filter": {"symbol": "btcusd"}}
                ]
                await feed.connections[0].send(json.dumps(price_frame("price.equity", "aapl")))
                assert (await anext(existing)).type == "update"
            await eventually(lambda: all(ws.close_code is not None for ws in feed.connections))

    asyncio.run(asyncio.wait_for(run(), 5))


def test_send_failure_restarts_and_preserves_existing_listener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        feed = Feed()
        async with feed_server(feed) as url:
            manager = RealtimeStreamManager(url=url, credentials=CREDS)
            try:
                existing = await manager.subscribe(CryptoPriceSpec(symbols=["btcusd"]))
                await anext(existing)
                connection = manager._sessions[0]._connection._connection
                original_send = connection.send
                failed = False

                async def send(payload: Any) -> bool:
                    nonlocal failed
                    if (
                        not failed
                        and isinstance(payload, dict)
                        and cast(dict[str, Any], payload).get("op") == "subscribe"
                    ):
                        failed = True
                        raise OSError("synthetic send failure")
                    return await original_send(payload)

                monkeypatch.setattr(connection, "send", send)
                joining = await manager.subscribe(CryptoPriceSpec(symbols=["ethusd"]))
                assert len(feed.connections) == 2
                assert (await anext(existing)).type == "subscribe"
                assert (await anext(joining)).payload.symbol == "ethusd"
            finally:
                await manager.close()

    asyncio.run(asyncio.wait_for(run(), 5))


def test_authentication_terminal_close_is_not_retried() -> None:
    async def run() -> None:
        feed = Feed()
        feed.auth_close_code = 4001
        async with feed_server(feed) as url:
            manager = RealtimeStreamManager(url=url, credentials=CREDS)
            try:
                with pytest.raises(ConnectionLostError) as failure:
                    await manager.subscribe(CryptoPriceSpec(symbols=["btcusd"]))
                assert failure.value.code == 4001
                assert len(feed.connections) == 1
            finally:
                await manager.close()

    asyncio.run(asyncio.wait_for(run(), 5))


def test_control_frames_are_paced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket_module, "OPERATION_INTERVAL_S", 0.11)

    async def run() -> None:
        feed = Feed()
        async with feed_server(feed) as url:
            manager = RealtimeStreamManager(url=url, credentials=CREDS)
            try:
                await manager.subscribe(CryptoPriceSpec(symbols=["btcusd"]))
                await manager.subscribe(CryptoPriceSpec(symbols=["ethusd"]))
                assert len(feed.received_times) == 3
                assert all(
                    later - earlier >= 0.1
                    for earlier, later in zip(
                        feed.received_times, feed.received_times[1:], strict=False
                    )
                )
            finally:
                await manager.close()

    asyncio.run(asyncio.wait_for(run(), 5))


def test_equity_filter_ignores_history_and_invalid_frames_but_preserves_updates() -> None:
    async def run() -> None:
        feed = Feed()
        async with feed_server(feed) as url:
            manager = RealtimeStreamManager(url=url, credentials=CREDS)
            try:
                stream = await manager.subscribe(EquityPriceSpec(symbol=" AAPL ", types=["update"]))
                await feed.connections[0].send("not json")
                await feed.connections[0].send(json.dumps({"v": 999, "channel": "price.equity"}))
                frame = price_frame("price.equity", "AAPL")
                frame["payload"].update(received_at=0, is_carried_forward=False)
                await feed.connections[0].send(json.dumps(frame))
                event = await anext(stream)
                assert event.type == "update" and event.topic == "prices.equity"
                assert event.payload.symbol == "aapl"
                assert event.payload.is_carried_forward is False
            finally:
                await manager.close()

    asyncio.run(asyncio.wait_for(run(), 5))


def test_identified_batch_rejection_isolated_from_other_channel() -> None:
    async def run() -> None:
        feed = Feed()
        feed.reject_symbols.add("badusd")
        async with feed_server(feed) as url:
            manager = RealtimeStreamManager(url=url, credentials=CREDS)
            try:
                bad, good = await asyncio.gather(
                    manager.subscribe(CryptoPriceSpec(symbols=["badusd"])),
                    manager.subscribe(EquityPriceSpec(symbol="aapl")),
                    return_exceptions=True,
                )
                assert isinstance(bad, RequestRejectedError)
                assert not isinstance(good, BaseException)
                assert (await anext(good)).topic == "prices.equity"
                assert len(feed.operations("subscribe")) == 1
            finally:
                await manager.close()

    asyncio.run(asyncio.wait_for(run(), 5))


def test_unsubscribe_timeout_replays_replacement_without_orphaned_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(socket_module, "ACK_TIMEOUT_S", 0.06)

    async def run() -> None:
        feed = Feed()
        async with feed_server(feed) as url:
            manager = RealtimeStreamManager(url=url, credentials=CREDS)
            try:
                first = await manager.subscribe(CryptoPriceSpec(symbols=["btcusd"]))
                feed.ignore_unsubscriptions = 1
                await first.close()
                replacement = await manager.subscribe(CryptoPriceSpec(symbols=["btcusd"]))
                assert (await anext(replacement)).type == "subscribe"
                assert [frame["op"] for frame in feed.frames] == [
                    "auth",
                    "subscribe",
                    "unsubscribe",
                    "auth",
                    "subscribe",
                ]
                assert len(feed.connections) == 2
            finally:
                await manager.close()

    asyncio.run(asyncio.wait_for(run(), 5))


def test_disconnect_during_idle_grace_allows_a_new_subscription() -> None:
    async def run() -> None:
        feed = Feed()
        async with feed_server(feed) as url:
            manager = RealtimeStreamManager(url=url, credentials=CREDS)
            try:
                first = await manager.subscribe(CryptoPriceSpec(symbols=["btcusd"]))
                await first.close()
                await feed.connections[0].close(4002, "idle disconnect")
                second = await manager.subscribe(CryptoPriceSpec(symbols=["ethusd"]))
                assert (await anext(second)).payload.symbol == "ethusd"
                assert len(feed.connections) == 2
            finally:
                await manager.close()

    asyncio.run(asyncio.wait_for(run(), 5))


def test_failed_initial_connection_rejects_and_releases_unowned_filters() -> None:
    async def run() -> None:
        feed = Feed()
        async with feed_server(feed) as url:
            closed_url = url
        manager = RealtimeStreamManager(url=closed_url, credentials=CREDS)
        try:
            with pytest.raises(TransportError):
                await manager.subscribe(CryptoPriceSpec(symbols=["btcusd"]))
            # Reopen the endpoint and retry the same key: a stale failed listener must
            # neither poison acceptance nor keep the connection alive after closing.
            port = int(closed_url.rsplit(":", 1)[1])
            async with serve(feed.handler, "127.0.0.1", port):
                stream = await manager.subscribe(CryptoPriceSpec(symbols=["btcusd"]))
                assert (await anext(stream)).type == "subscribe"
                await stream.close()
                await eventually(lambda: all(ws.close_code is not None for ws in feed.connections))
        finally:
            await manager.close()

    asyncio.run(asyncio.wait_for(run(), 5))


def test_drops_reduce_new_connection_capacity_without_replaying_existing_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    # Replace this module's clock only; do not move the event loop's monotonic clock.
    elapsed = 0.0
    monkeypatch.setattr(
        session_module, "time", SimpleNamespace(monotonic=lambda: time.monotonic() + elapsed)
    )

    async def run() -> None:
        nonlocal elapsed
        feed = Feed()
        async with feed_server(feed) as url:
            manager = RealtimeStreamManager(url=url, credentials=CREDS)
            try:
                stream = await manager.subscribe(
                    CryptoPriceSpec(symbols=[f"coin{i}usd" for i in range(32)])
                )
                frame = price_frame(symbol="coin0usd")
                frame["dropped"] = 1
                await feed.connections[0].send(json.dumps(frame))
                while (await anext(stream)).type != "update":
                    pass
                await manager.subscribe(CryptoPriceSpec(symbols=["ethusd"]))
                assert len(feed.connections) == 2
                assert [len(frame["subscriptions"]) for frame in feed.operations("subscribe")] == [
                    32,
                    1,
                ]
                elapsed = 61
                recovered = await manager.subscribe(CryptoPriceSpec(symbols=["btcusd"]))
                assert len(feed.connections) == 2
                # The original connection accepts new filters again after its quiet period.
                assert (await anext(recovered)).type == "subscribe"
                await feed.connections[0].send(json.dumps(price_frame()))
                assert (await anext(recovered)).type == "update"
            finally:
                await manager.close()

    asyncio.run(asyncio.wait_for(run(), 5))


def test_protocol_heartbeat_and_draining_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    from polymarket._internal.streams.realtime.protocol import reconnect_delay

    assert 0 <= reconnect_delay(4003, 100) < 10
    assert 0 <= reconnect_delay(1006, 100) < 30
    monkeypatch.setattr(heartbeat_module, "PING_INTERVAL_S", 0.01)

    async def run() -> None:
        sent: list[str] = []

        async def send(frame: str) -> bool:
            sent.append(frame)
            return True

        heartbeat = heartbeat_module.PriceHeartbeat()
        await heartbeat.start(send)
        try:
            await eventually(lambda: len(sent) > 0)
            assert sent[0] == '{"op":"ping"}'
            assert heartbeat.is_stale(time.monotonic() + 91)
            heartbeat.handle("any inbound frame")
            assert not heartbeat.is_stale(time.monotonic() + 89)
        finally:
            await heartbeat.stop()

    asyncio.run(asyncio.wait_for(run(), 5))


def test_pool_partitions_above_64_filters_and_reuses_existing_keys() -> None:
    async def run() -> None:
        feed = Feed()
        async with feed_server(feed) as url:
            manager = RealtimeStreamManager(url=url, credentials=CREDS)
            try:
                stream = await manager.subscribe(
                    CryptoPriceSpec(symbols=[f"coin{i}usd" for i in range(65)])
                )
                joined = await manager.subscribe(CryptoPriceSpec(symbols=["coin0usd", "coin64usd"]))
                assert len(feed.connections) == 2
                assert sorted(
                    len(frame["subscriptions"]) for frame in feed.operations("subscribe")
                ) == [1, 64]
                await stream.close()
                await joined.close()
            finally:
                await manager.close()

    asyncio.run(asyncio.wait_for(run(), 5))


def test_rejected_new_filter_preserves_established_sibling() -> None:
    async def run() -> None:
        feed = Feed()
        feed.reject_symbols.add("badusd")
        async with feed_server(feed) as url:
            manager = RealtimeStreamManager(url=url, credentials=CREDS)
            try:
                existing = await manager.subscribe(CryptoPriceSpec(symbols=["btcusd"]))
                await anext(existing)
                with pytest.raises(RequestRejectedError) as failure:
                    await manager.subscribe(CryptoPriceSpec(symbols=["badusd"]))
                assert failure.value.code == "bad_filter"
                await feed.connections[0].send(json.dumps(price_frame()))
                assert (await anext(existing)).type == "update"
                assert len(feed.connections) == 1
            finally:
                await manager.close()

    asyncio.run(asyncio.wait_for(run(), 5))


@pytest.mark.parametrize("code", [4001, 4008])
def test_terminal_close_ends_every_shared_handle(code: int) -> None:
    async def run() -> None:
        feed = Feed()
        async with feed_server(feed) as url:
            manager = RealtimeStreamManager(url=url, credentials=CREDS)
            try:
                first = await manager.subscribe(CryptoPriceSpec(symbols=["btcusd", "ethusd"]))
                second = await manager.subscribe(CryptoPriceSpec(symbols=["ethusd"]))
                await feed.connections[0].close(code, "terminal")
                for stream in (first, second):
                    with pytest.raises(ConnectionLostError) as failure:
                        async for _ in stream:
                            pass
                    assert failure.value.code == code
                assert len(feed.connections) == 1
            finally:
                await manager.close()

    asyncio.run(asyncio.wait_for(run(), 5))


def test_ack_timeout_reconnects_without_losing_existing_listener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(socket_module, "ACK_TIMEOUT_S", 0.06)

    async def run() -> None:
        feed = Feed()
        async with feed_server(feed) as url:
            manager = RealtimeStreamManager(url=url, credentials=CREDS)
            try:
                first = await manager.subscribe(CryptoPriceSpec(symbols=["btcusd"]))
                await anext(first)
                feed.ignore_subscriptions = 1
                second = await manager.subscribe(CryptoPriceSpec(symbols=["ethusd"]))
                assert len(feed.connections) == 2
                assert (await anext(first)).type == "subscribe"
                assert (await anext(second)).payload.symbol == "ethusd"
                assert len(feed.operations("auth")) == 2
            finally:
                await manager.close()

    asyncio.run(asyncio.wait_for(run(), 5))


def test_reconnect_joiners_wait_for_fresh_acceptance() -> None:
    async def run() -> None:
        feed = Feed()
        async with feed_server(feed) as url:
            manager = RealtimeStreamManager(url=url, credentials=CREDS)
            try:
                first = await manager.subscribe(CryptoPriceSpec(symbols=["btcusd"]))
                await anext(first)
                feed.ack_gate = asyncio.Event()
                await feed.connections[0].close(4002, "recover")
                await eventually(lambda: len(feed.connections) == 2)
                joining = asyncio.create_task(
                    manager.subscribe(CryptoPriceSpec(symbols=["btcusd"]))
                )
                await asyncio.sleep(0.03)
                assert not joining.done()
                feed.ack_gate.set()
                second = await joining
                assert (await anext(first)).type == "subscribe"
                assert (await anext(second)).type == "subscribe"
            finally:
                if feed.ack_gate is not None:
                    feed.ack_gate.set()
                await manager.close()

    asyncio.run(asyncio.wait_for(run(), 5))


def test_auth_rejection_is_typed_and_temporary_unavailability_retries() -> None:
    async def run() -> None:
        feed = Feed()
        feed.auth_errors = ["auth_invalid"]
        async with feed_server(feed) as url:
            manager = RealtimeStreamManager(url=url, credentials=CREDS)
            try:
                with pytest.raises(RequestRejectedError) as failure:
                    await manager.subscribe(CryptoPriceSpec(symbols=["btcusd"]))
                assert failure.value.code == "auth_invalid"
            finally:
                await manager.close()
            feed.auth_errors = ["auth_unavailable"]
            manager = RealtimeStreamManager(url=url, credentials=CREDS)
            try:
                stream = await manager.subscribe(CryptoPriceSpec(symbols=["btcusd"]))
                assert (await anext(stream)).topic == "prices.crypto"
                assert len(feed.connections) == 3
            finally:
                await manager.close()

    asyncio.run(asyncio.wait_for(run(), 5))


def test_acceptance_timeout_and_cancellation_release_only_joining_listener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(session_module, "ACCEPTANCE_TIMEOUT_S", 0.08)

    async def run() -> None:
        feed = Feed()
        async with feed_server(feed) as url:
            manager = RealtimeStreamManager(url=url, credentials=CREDS)
            try:
                first = await manager.subscribe(CryptoPriceSpec(symbols=["btcusd"]))
                await anext(first)
                feed.ack_gate = asyncio.Event()
                await feed.connections[0].close(4002, "recover")
                await eventually(lambda: len(feed.connections) == 2)
                with pytest.raises(TransportError, match="accepted"):
                    await manager.subscribe(CryptoPriceSpec(symbols=["btcusd"]))
                cancelled = asyncio.create_task(
                    manager.subscribe(CryptoPriceSpec(symbols=["btcusd"]))
                )
                await asyncio.sleep(0.01)
                cancelled.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await cancelled
                feed.ack_gate.set()
                assert (await anext(first)).type == "subscribe"
                await first.close()
                await eventually(lambda: len(feed.operations("unsubscribe")) == 1)
                await eventually(lambda: all(ws.close_code is not None for ws in feed.connections))
            finally:
                if feed.ack_gate is not None:
                    feed.ack_gate.set()
                await manager.close()

    asyncio.run(asyncio.wait_for(run(), 5))
