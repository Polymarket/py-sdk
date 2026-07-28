"""Stream 30-second and 60-second Chainlink TWAP prices.

    uv run python -m examples.crypto_twap_stream

No credentials required. Stop the stream with Ctrl-C.
"""

import asyncio

from polymarket import AsyncPublicClient
from polymarket.streams import CryptoPricesChainlinkTwapSpec


async def main() -> None:
    client = AsyncPublicClient()
    try:
        async with await client.subscribe(
            [
                CryptoPricesChainlinkTwapSpec(
                    window_seconds=30,
                    symbols=["btc/usd", "eth/usd"],
                ),
                CryptoPricesChainlinkTwapSpec(
                    window_seconds=60,
                    symbols=["btc/usd", "eth/usd"],
                ),
            ]
        ) as stream:
            async for event in stream:
                print(
                    f"{event.payload.symbol} "
                    f"{event.payload.window_seconds}s "
                    f"{event.payload.value} "
                    f"(observed {event.payload.timestamp})"
                )
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
