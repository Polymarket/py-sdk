import asyncio
import time

import pytest

from polymarket import AsyncPublicClient
from polymarket.environments import PRODUCTION
from polymarket.streams import CryptoPricesSpec  # pyright: ignore[reportDeprecated]


@pytest.mark.integration
def test_live_rtds_single_subscription_close_returns_within_one_second() -> None:
    async def run() -> float:
        client = AsyncPublicClient(environment=PRODUCTION)
        try:
            stream = await client.subscribe(CryptoPricesSpec(topic="prices.crypto.binance"))  # pyright: ignore[reportDeprecated]
            await asyncio.sleep(0.5)
            started = time.monotonic()
            await asyncio.wait_for(stream.close(), timeout=1.0)
            return time.monotonic() - started
        finally:
            await client.close()

    elapsed_s = asyncio.run(asyncio.wait_for(run(), timeout=15.0))
    assert elapsed_s < 1.0
