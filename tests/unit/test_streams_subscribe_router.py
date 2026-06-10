import asyncio
import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import pytest
from websockets.asyncio.server import ServerConnection, serve

from polymarket import AsyncPublicClient
from polymarket.environments import PRODUCTION, Environment, WalletDerivation
from polymarket.errors import UserInputError
from polymarket.models.clob.market_events import MarketBookEvent
from polymarket.streams import MarketSpec

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


def _env_with_market_ws(url: str) -> Environment:
    return _env_with(clob_market_ws_url=url)


def _env_with_sports_ws(url: str) -> Environment:
    return _env_with(sports_ws_url=url)


def _env_with_rtds_ws(url: str) -> Environment:
    return _env_with(rtds_ws_url=url)


def _env_with_both(market_url: str, sports_url: str) -> Environment:
    return _env_with(clob_market_ws_url=market_url, sports_ws_url=sports_url)


def _env_with_all(market_url: str, sports_url: str, rtds_url: str) -> Environment:
    return _env_with(clob_market_ws_url=market_url, sports_ws_url=sports_url, rtds_ws_url=rtds_url)


def _env_with(
    *,
    clob_market_ws_url: str = PRODUCTION.clob_market_ws_url,
    sports_ws_url: str = PRODUCTION.sports_ws_url,
    rtds_ws_url: str = PRODUCTION.rtds_ws_url,
) -> Environment:
    return Environment(
        name="test",
        chain_id=PRODUCTION.chain_id,
        wallet_derivation=WalletDerivation(
            proxy_factory=PRODUCTION.wallet_derivation.proxy_factory,
            proxy_implementation=PRODUCTION.wallet_derivation.proxy_implementation,
            safe_factory=PRODUCTION.wallet_derivation.safe_factory,
            safe_init_code_hash=PRODUCTION.wallet_derivation.safe_init_code_hash,
            deposit_wallet_factory=PRODUCTION.wallet_derivation.deposit_wallet_factory,
            deposit_wallet_implementation=PRODUCTION.wallet_derivation.deposit_wallet_implementation,
            deposit_wallet_beacon=PRODUCTION.wallet_derivation.deposit_wallet_beacon,
        ),
        collateral_token=PRODUCTION.collateral_token,
        conditional_tokens=PRODUCTION.conditional_tokens,
        neg_risk_adapter=PRODUCTION.neg_risk_adapter,
        collateral_adapter=PRODUCTION.collateral_adapter,
        neg_risk_collateral_adapter=PRODUCTION.neg_risk_collateral_adapter,
        standard_exchange=PRODUCTION.standard_exchange,
        neg_risk_exchange=PRODUCTION.neg_risk_exchange,
        auto_redeem_operator=PRODUCTION.auto_redeem_operator,
        safe_multisend=PRODUCTION.safe_multisend,
        relay_hub=PRODUCTION.relay_hub,
        clob_url=PRODUCTION.clob_url,
        clob_market_ws_url=clob_market_ws_url,
        clob_user_ws_url=PRODUCTION.clob_user_ws_url,
        relayer_url=PRODUCTION.relayer_url,
        gamma_url=PRODUCTION.gamma_url,
        data_url=PRODUCTION.data_url,
        rfq_url=PRODUCTION.rfq_url,
        rtds_ws_url=rtds_ws_url,
        sports_ws_url=sports_ws_url,
        rpc_url=PRODUCTION.rpc_url,
    )


def _book_frame(asset_id: str, market: str = "m") -> dict[str, Any]:
    return {
        "event_type": "book",
        "market": market,
        "asset_id": asset_id,
        "bids": [{"price": "0.49", "size": "100"}],
        "asks": [{"price": "0.51", "size": "100"}],
    }


def test_subscribe_with_single_market_spec_returns_underlying_handle() -> None:
    received: list[dict[str, Any]] = []

    async def handler(ws: ServerConnection) -> None:
        raw = await ws.recv()
        assert isinstance(raw, str)
        received.append(json.loads(raw))
        await ws.send(json.dumps(_book_frame("a")))
        async for _ in ws:
            pass

    async def run() -> str:
        async with ws_server(handler) as url:
            client = AsyncPublicClient(environment=_env_with_market_ws(url))
            try:
                async with await client.subscribe(MarketSpec(token_ids=["a"])) as stream:
                    event = await asyncio.wait_for(stream.__aiter__().__anext__(), timeout=2.0)
                    assert isinstance(event, MarketBookEvent)
                    return event.payload.token_id
            finally:
                await client.close()

    token = asyncio.run(run())
    assert token == "a"
    assert received[0]["type"] == "market"
    assert received[0]["assets_ids"] == ["a"]


def test_subscribe_with_list_of_specs_returns_merged_handle() -> None:
    async def handler(ws: ServerConnection) -> None:
        await ws.recv()  # initial subscribe
        # Second spec adds another token via the same socket — incremental
        raw = await ws.recv()
        assert isinstance(raw, str)
        update = json.loads(raw)
        assert update == {
            "operation": "subscribe",
            "assets_ids": ["b"],
            "custom_feature_enabled": False,
        }
        await ws.send(json.dumps(_book_frame("a")))
        await ws.send(json.dumps(_book_frame("b")))
        async for _ in ws:
            pass

    async def run() -> set[str]:
        async with ws_server(handler) as url:
            client = AsyncPublicClient(environment=_env_with_market_ws(url))
            try:
                async with await client.subscribe(
                    [MarketSpec(token_ids=["a"]), MarketSpec(token_ids=["b"])]
                ) as stream:
                    seen: set[str] = set()
                    while len(seen) < 2:
                        event = await asyncio.wait_for(stream.__aiter__().__anext__(), timeout=2.0)
                        assert isinstance(event, MarketBookEvent)
                        seen.add(event.payload.token_id)
                    return seen
            finally:
                await client.close()

    assert asyncio.run(run()) == {"a", "b"}


def test_subscribe_rejects_empty_sequence() -> None:
    async def run() -> None:
        client = AsyncPublicClient()
        try:
            with pytest.raises(UserInputError, match="at least one"):
                await client.subscribe([])
        finally:
            await client.close()

    asyncio.run(run())


def test_subscribe_rejects_bare_string() -> None:
    async def run() -> None:
        client = AsyncPublicClient()
        try:
            with pytest.raises(UserInputError, match="sequence of Subscriptions"):
                await client.subscribe("not-a-spec")  # pyright: ignore[reportCallIssue, reportArgumentType]
        finally:
            await client.close()

    asyncio.run(run())


def test_subscribe_rejects_unknown_spec_type() -> None:
    async def run() -> None:
        client = AsyncPublicClient()
        try:
            with pytest.raises(UserInputError, match="unsupported"):
                await client.subscribe([object()])  # pyright: ignore[reportCallIssue, reportArgumentType]
        finally:
            await client.close()

    asyncio.run(run())


def test_invalid_spec_construction_raises_before_any_socket_opens() -> None:
    accepts = 0

    async def handler(ws: ServerConnection) -> None:
        nonlocal accepts
        accepts += 1
        async for _ in ws:
            pass

    async def run() -> tuple[int, bool]:
        async with ws_server(handler) as url:
            client = AsyncPublicClient(environment=_env_with_market_ws(url))
            try:
                # Invalid spec construction itself raises — no subscribe call needed.
                with pytest.raises(UserInputError, match="non-empty"):
                    MarketSpec(token_ids=[])
                await asyncio.sleep(0.05)
                return accepts, client._market_manager is None  # pyright: ignore[reportPrivateUsage]
            finally:
                await client.close()

    count, router_lazy = asyncio.run(run())
    assert count == 0
    assert router_lazy is True


def test_failed_mid_subscribe_rolls_back_prior_handles() -> None:
    """If subscribe() raises partway through the spec list, prior handles
    must be closed so the socket doesn't leak."""

    async def handler(ws: ServerConnection) -> None:
        async for _ in ws:
            pass

    async def run() -> bool:
        async with ws_server(handler) as url:
            client = AsyncPublicClient(environment=_env_with_market_ws(url))
            try:
                # Open one valid subscribe to instantiate the manager, then
                # patch subscribe to fail on a later call so rollback runs.
                spec1 = MarketSpec(token_ids=["a"])
                spec2 = MarketSpec(token_ids=["b"])
                first_handle = await client.subscribe(spec1)
                await first_handle.close()

                manager = client._market_manager  # pyright: ignore[reportPrivateUsage]
                assert manager is not None
                original_subscribe = manager.subscribe
                call_count = 0

                async def failing_subscribe(**kwargs: Any) -> Any:
                    nonlocal call_count
                    call_count += 1
                    if call_count == 1:
                        return await original_subscribe(**kwargs)
                    raise RuntimeError("simulated mid-subscribe failure")

                manager.subscribe = failing_subscribe  # type: ignore[method-assign]
                with pytest.raises(RuntimeError, match="simulated"):
                    await client.subscribe([spec1, spec2])
                await asyncio.sleep(0.1)
                return not manager.is_open
            finally:
                await client.close()

    assert asyncio.run(run()) is True


def test_merged_handle_preserves_first_child_error() -> None:
    """If a child handle ends with an error, the merged handle must re-raise
    it at end-of-stream rather than silently producing StopAsyncIteration."""
    from polymarket._internal.streams.handle import AsyncSubscriptionHandle
    from polymarket._internal.streams.merged_handle import MergedSubscriptionHandle

    async def run() -> None:
        good: AsyncSubscriptionHandle[int] = AsyncSubscriptionHandle(queue_size=4)
        bad: AsyncSubscriptionHandle[int] = AsyncSubscriptionHandle(queue_size=4)
        good._push(1)  # pyright: ignore[reportPrivateUsage]
        good._end()  # pyright: ignore[reportPrivateUsage]
        bad._end(RuntimeError("child boom"))  # pyright: ignore[reportPrivateUsage]
        merged: MergedSubscriptionHandle[int] = MergedSubscriptionHandle([good, bad])
        first = await merged.__aiter__().__anext__()
        assert first == 1
        with pytest.raises(RuntimeError, match="child boom"):
            await merged.__aiter__().__anext__()
        await merged.close()

    asyncio.run(run())


def test_merged_handle_uses_bounded_queue_with_drop_oldest() -> None:
    """Slow consumer of a merged handle must not unboundedly grow memory."""
    from polymarket._internal.streams.handle import AsyncSubscriptionHandle
    from polymarket._internal.streams.merged_handle import MergedSubscriptionHandle

    async def run() -> int:
        child: AsyncSubscriptionHandle[int] = AsyncSubscriptionHandle(queue_size=8)
        merged: MergedSubscriptionHandle[int] = MergedSubscriptionHandle([child], queue_size=4)
        # Push more events than fit into the merged queue.
        for i in range(20):
            child._push(i)  # pyright: ignore[reportPrivateUsage]
        child._end()  # pyright: ignore[reportPrivateUsage]
        # Drain.
        collected: list[int] = []
        async for event in merged:
            collected.append(event)
        # Some events were dropped — the merged queue is bounded.
        assert len(collected) < 20
        return merged.dropped

    dropped = asyncio.run(run())
    assert dropped > 0


def test_market_spec_topic_field_is_not_caller_settable() -> None:
    # Discriminator is fixed by class; caller can't lie about it.
    with pytest.raises(TypeError):
        MarketSpec(token_ids=["a"], topic="sports")  # pyright: ignore[reportCallIssue]


def test_sports_spec_topic_field_is_not_caller_settable() -> None:
    from polymarket.streams import SportsSpec

    with pytest.raises(TypeError):
        SportsSpec(topic="market")  # pyright: ignore[reportCallIssue]


def test_close_cascades_to_streams() -> None:
    async def handler(ws: ServerConnection) -> None:
        async for _ in ws:
            pass

    async def run() -> bool:
        async with ws_server(handler) as url:
            client = AsyncPublicClient(environment=_env_with_market_ws(url))
            handle = await client.subscribe(MarketSpec(token_ids=["a"]))
            await asyncio.sleep(0.05)
            await client.close()
            # Iterating after client close should yield the end sentinel.
            with pytest.raises(StopAsyncIteration):
                await handle.__aiter__().__anext__()
            return True

    assert asyncio.run(run()) is True


def test_subscribe_with_sports_spec_returns_sports_handle() -> None:
    from polymarket.models.sports_events import SportsResultEvent
    from polymarket.streams import SportsSpec

    async def handler(ws: ServerConnection) -> None:
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

    async def run() -> int:
        async with ws_server(handler) as url:
            client = AsyncPublicClient(environment=_env_with_sports_ws(url))
            try:
                async with await client.subscribe(SportsSpec()) as stream:
                    event = await asyncio.wait_for(stream.__aiter__().__anext__(), timeout=2.0)
                    assert isinstance(event, SportsResultEvent)
                    return event.payload.game_id
            finally:
                await client.close()

    assert asyncio.run(run()) == 1


def test_subscribe_with_mixed_market_and_sports_specs_returns_merged_handle() -> None:
    from polymarket.streams import SportsSpec

    async def market_handler(ws: ServerConnection) -> None:
        await ws.recv()  # initial subscribe frame
        await ws.send(
            json.dumps(
                {
                    "event_type": "book",
                    "market": "m",
                    "asset_id": "a",
                    "bids": [{"price": "0.49", "size": "100"}],
                    "asks": [{"price": "0.51", "size": "100"}],
                }
            )
        )
        async for _ in ws:
            pass

    async def sports_handler(ws: ServerConnection) -> None:
        await ws.send(
            json.dumps(
                {
                    "gameId": 99,
                    "leagueAbbreviation": "NBA",
                    "status": "live",
                    "live": True,
                    "ended": False,
                    "score": "1-1",
                }
            )
        )
        async for _ in ws:
            pass

    async def run() -> set[str]:
        async with ws_server(market_handler) as market_url, ws_server(sports_handler) as sports_url:
            client = AsyncPublicClient(environment=_env_with_both(market_url, sports_url))
            try:
                async with await client.subscribe(
                    [MarketSpec(token_ids=["a"]), SportsSpec()]
                ) as stream:
                    seen: set[str] = set()
                    while len(seen) < 2:
                        event = await asyncio.wait_for(stream.__aiter__().__anext__(), timeout=2.0)
                        seen.add(event.topic)
                    return seen
            finally:
                await client.close()

    assert asyncio.run(run()) == {"market", "sports"}


def test_close_cascades_to_both_managers() -> None:
    from polymarket.streams import SportsSpec

    async def handler(ws: ServerConnection) -> None:
        async for _ in ws:
            pass

    async def run() -> None:
        async with ws_server(handler) as market_url, ws_server(handler) as sports_url:
            client = AsyncPublicClient(environment=_env_with_both(market_url, sports_url))
            mh = await client.subscribe(MarketSpec(token_ids=["a"]))
            sh = await client.subscribe(SportsSpec())
            await asyncio.sleep(0.05)
            await client.close()
            with pytest.raises(StopAsyncIteration):
                await mh.__aiter__().__anext__()
            with pytest.raises(StopAsyncIteration):
                await sh.__aiter__().__anext__()

    asyncio.run(run())


def test_subscribe_with_rtds_spec_returns_rtds_handle() -> None:
    from polymarket.models.rtds_events import CryptoPricesBinanceEvent
    from polymarket.streams import CryptoPricesSpec

    async def handler(ws: ServerConnection) -> None:
        await ws.recv()
        await ws.send(
            json.dumps(
                {
                    "topic": "crypto_prices",
                    "type": "update",
                    "timestamp": "1710000000000",
                    "payload": {
                        "symbol": "btcusdt",
                        "timestamp": 1710000000000,
                        "value": "65000",
                    },
                }
            )
        )
        async for _ in ws:
            pass

    async def run() -> str:
        async with ws_server(handler) as url:
            client = AsyncPublicClient(environment=_env_with_rtds_ws(url))
            try:
                async with await client.subscribe(
                    CryptoPricesSpec(topic="prices.crypto.binance")
                ) as stream:
                    event = await asyncio.wait_for(stream.__aiter__().__anext__(), timeout=2.0)
                    assert isinstance(event, CryptoPricesBinanceEvent)
                    return event.payload.symbol
            finally:
                await client.close()

    assert asyncio.run(run()) == "btcusdt"


def test_subscribe_with_market_sports_and_rtds_returns_merged_handle() -> None:
    from polymarket.streams import CryptoPricesSpec, SportsSpec

    async def market_handler(ws: ServerConnection) -> None:
        await ws.recv()
        await ws.send(json.dumps(_book_frame("a")))
        async for _ in ws:
            pass

    async def sports_handler(ws: ServerConnection) -> None:
        await ws.send(
            json.dumps(
                {
                    "gameId": 7,
                    "leagueAbbreviation": "NBA",
                    "status": "live",
                    "live": True,
                    "ended": False,
                    "score": "2-2",
                }
            )
        )
        async for _ in ws:
            pass

    async def rtds_handler(ws: ServerConnection) -> None:
        await ws.recv()
        await ws.send(
            json.dumps(
                {
                    "topic": "crypto_prices",
                    "type": "update",
                    "timestamp": "1710000000000",
                    "payload": {
                        "symbol": "btcusdt",
                        "timestamp": 1710000000000,
                        "value": "1",
                    },
                }
            )
        )
        async for _ in ws:
            pass

    async def run() -> set[str]:
        async with (
            ws_server(market_handler) as market_url,
            ws_server(sports_handler) as sports_url,
            ws_server(rtds_handler) as rtds_url,
        ):
            client = AsyncPublicClient(environment=_env_with_all(market_url, sports_url, rtds_url))
            try:
                async with await client.subscribe(
                    [
                        MarketSpec(token_ids=["a"]),
                        SportsSpec(),
                        CryptoPricesSpec(topic="prices.crypto.binance"),
                    ]
                ) as stream:
                    seen: set[str] = set()
                    while len(seen) < 3:
                        event = await asyncio.wait_for(stream.__aiter__().__anext__(), timeout=3.0)
                        seen.add(event.topic)
                    return seen
            finally:
                await client.close()

    topics = asyncio.run(run())
    assert topics == {"market", "sports", "prices.crypto.binance"}


def test_close_cascades_to_rtds_manager() -> None:
    from polymarket.streams import CryptoPricesSpec

    async def handler(ws: ServerConnection) -> None:
        async for _ in ws:
            pass

    async def run() -> None:
        async with ws_server(handler) as url:
            client = AsyncPublicClient(environment=_env_with_rtds_ws(url))
            handle = await client.subscribe(CryptoPricesSpec(topic="prices.crypto.binance"))
            await asyncio.sleep(0.05)
            await client.close()
            with pytest.raises(StopAsyncIteration):
                await handle.__aiter__().__anext__()

    asyncio.run(run())


def test_crypto_prices_spec_topic_field_is_caller_required() -> None:
    from polymarket.streams import CryptoPricesSpec

    with pytest.raises(TypeError):
        CryptoPricesSpec()  # pyright: ignore[reportCallIssue]


def test_comments_spec_topic_field_is_not_caller_settable() -> None:
    from polymarket.streams import CommentsSpec

    with pytest.raises(TypeError):
        CommentsSpec(topic="prices.crypto.binance")  # pyright: ignore[reportCallIssue]


def test_equity_spec_topic_field_is_not_caller_settable() -> None:
    from polymarket.streams import EquityPricesSpec

    with pytest.raises(TypeError):
        EquityPricesSpec(symbol="AAPL", topic="comments")  # pyright: ignore[reportCallIssue]


def test_public_client_assert_never_protects_against_smuggled_user_spec() -> None:
    from polymarket.streams import UserSpec

    async def run() -> None:
        client = AsyncPublicClient()
        try:
            smuggled: list[Any] = [UserSpec()]
            with pytest.raises(AssertionError):
                await client.subscribe(smuggled)
        finally:
            await client.close()

    asyncio.run(run())


def test_user_spec_topic_field_is_not_caller_settable() -> None:
    from polymarket.streams import UserSpec

    with pytest.raises(TypeError):
        UserSpec(topic="market")  # pyright: ignore[reportCallIssue]


def test_user_spec_normalizes_empty_markets_to_none() -> None:
    from polymarket.streams import UserSpec

    assert UserSpec(markets=[]).markets is None
    assert UserSpec(markets=()).markets is None
    assert UserSpec().markets is None
