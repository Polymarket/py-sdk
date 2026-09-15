import asyncio
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from polymarket import AsyncSecureClient
from polymarket.streams import CryptoPriceSpec, CryptoTwapPriceSpec, EquityPriceSpec, PriceEvent


def assert_price_values(event: PriceEvent) -> None:
    assert event.timestamp.utcoffset() == timedelta(0)
    points = event.payload.data if event.type == "subscribe" else (event.payload,)
    for point in points:
        assert isinstance(point.value, Decimal)
        assert point.value.is_finite() and point.value > 0
        assert point.timestamp.utcoffset() == timedelta(0)
    if event.type == "subscribe":
        timestamps = [point.timestamp for point in event.payload.data]
        assert timestamps == sorted(timestamps)
    if event.topic == "prices.crypto.twap":
        assert event.payload.window_seconds == 60


@pytest.mark.integration
@pytest.mark.anyio
async def test_authenticated_price_history_and_updates(
    deposit_wallet_client: AsyncSecureClient,
) -> None:
    """Read all feeds and exercise shared subscriptions; no trading or account writes."""
    crypto_keys = {
        ("prices.crypto", "btcusd"),
        ("prices.crypto", "ethusd"),
        ("prices.crypto.twap", "btcusd"),
    }
    expected_keys = crypto_keys | {("prices.equity", "aapl")}
    histories: set[tuple[str, str]] = set()
    updates: dict[tuple[str, str], set[int]] = {key: set() for key in crypto_keys}
    latest_updates: dict[tuple[str, str], datetime] = {}
    async with asyncio.timeout(60):
        async with await deposit_wallet_client.subscribe(
            [
                CryptoPriceSpec(symbols=["btcusd", "btcusd", "ethusd"]),
                CryptoTwapPriceSpec(symbols=["btcusd"]),
                EquityPriceSpec(symbol=" AAPL ", types=[]),
            ]
        ) as stream:
            while histories != expected_keys or any(len(seqs) < 2 for seqs in updates.values()):
                event = await anext(stream)
                key = (event.topic, event.payload.symbol)
                assert key in expected_keys
                assert_price_values(event)
                if event.type == "subscribe":
                    # Equity's recent history can be empty while its market is inactive.
                    if key in crypto_keys:
                        assert event.payload.data, f"Missing price history for {key}"
                        # Recovery snapshots start a new connection-local sequence.
                        updates[key].clear()
                    histories.add(key)
                elif key in crypto_keys:
                    assert event.seq is not None
                    assert event.seq not in updates[key], f"Duplicate delivery for {key}"
                    updates[key].add(event.seq)
                    latest_updates[key] = event.payload.timestamp

            # A late joiner receives current history. Closing it leaves the original active.
            async with await deposit_wallet_client.subscribe(
                CryptoPriceSpec(symbols=["btcusd"])
            ) as joined:
                snapshot = await anext(joined)
                assert snapshot.type == "subscribe"
                assert snapshot.payload.symbol == "btcusd"
                assert snapshot.payload.data
                assert_price_values(snapshot)
                latest = snapshot.payload.data[-1].timestamp
                assert latest >= latest_updates[("prices.crypto", "btcusd")]
            with pytest.raises(StopAsyncIteration):
                await anext(joined)
            while True:
                event = await anext(stream)
                if (
                    event.topic == "prices.crypto"
                    and event.type == "update"
                    and event.payload.symbol == "btcusd"
                    and event.payload.timestamp > latest
                ):
                    assert_price_values(event)
                    break

        with pytest.raises(StopAsyncIteration):
            await anext(stream)
        # Closing all subscriptions does not prevent reusing the client.
        async with await deposit_wallet_client.subscribe(
            CryptoPriceSpec(symbols=["btcusd"])
        ) as reopened:
            snapshot = await anext(reopened)
            assert snapshot.type == "subscribe" and snapshot.payload.data
            assert_price_values(snapshot)


@pytest.mark.integration
@pytest.mark.anyio
async def test_equity_history_and_update_filters(deposit_wallet_client: AsyncSecureClient) -> None:
    """Check equity filters when recent data is available; no account writes."""
    async with asyncio.timeout(45):
        async with await deposit_wallet_client.subscribe(
            EquityPriceSpec(symbol=" AAPL ", types=["subscribe"])
        ) as history:
            snapshot = await anext(history)
            assert snapshot.type == "subscribe" and snapshot.payload.symbol == "aapl"
            assert_price_values(snapshot)
            if not snapshot.payload.data:
                pytest.skip("AAPL has no recent price history; live equity updates are unavailable")

            async with await deposit_wallet_client.subscribe(
                EquityPriceSpec(symbol="aapl", types=["update"])
            ) as updates:
                # A shared snapshot must not leak through the update-only filter.
                for _ in range(2):
                    event = await anext(updates)
                    assert event.type == "update" and event.payload.symbol == "aapl"
                    assert_price_values(event)
                # Updates arrived for this key, but the history-only handle must exclude them.
                with pytest.raises(TimeoutError):
                    await asyncio.wait_for(anext(history), 0.1)
        with pytest.raises(StopAsyncIteration):
            await anext(history)
        with pytest.raises(StopAsyncIteration):
            await anext(updates)
