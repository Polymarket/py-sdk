import asyncio

import pytest

from polymarket import AsyncPublicClient
from polymarket.environments import PRODUCTION
from polymarket.streams import (
    CryptoPricesBinanceEvent,
    CryptoPricesSpec,  # pyright: ignore[reportDeprecated]
)


@pytest.mark.integration
def test_live_rtds_clean_shutdown() -> None:
    async def run() -> None:
        client = AsyncPublicClient(environment=PRODUCTION)
        try:
            async with await client.subscribe(CryptoPricesSpec(topic="prices.crypto.binance")):  # pyright: ignore[reportDeprecated]
                await asyncio.sleep(0.5)
        finally:
            await client.close()

    asyncio.run(asyncio.wait_for(run(), timeout=15.0))


@pytest.mark.integration
def test_live_rtds_receives_a_crypto_price_event() -> None:
    async def run() -> CryptoPricesBinanceEvent:
        client = AsyncPublicClient(environment=PRODUCTION)
        try:
            async with await client.subscribe(
                CryptoPricesSpec(topic="prices.crypto.binance")  # pyright: ignore[reportDeprecated]
            ) as stream:
                async for event in stream:
                    assert isinstance(event, CryptoPricesBinanceEvent)
                    return event
        finally:
            await client.close()
        raise AssertionError("stream closed before any event arrived")

    event = asyncio.run(asyncio.wait_for(run(), timeout=35.0))
    assert event.topic == "prices.crypto.binance"
    assert event.type == "update"
    assert event.payload.symbol
    assert event.payload.value > 0
