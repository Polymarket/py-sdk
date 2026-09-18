"""Stream authenticated prices using the normal secure-client setup."""

import asyncio

from examples.lib.env import require_env
from polymarket import AsyncSecureClient
from polymarket.streams import CryptoPriceSpec, CryptoTwapPriceSpec, EquityPriceSpec


async def main() -> None:
    client = await AsyncSecureClient.create(
        private_key=require_env("POLYMARKET_PRIVATE_KEY"),
        wallet=require_env("POLYMARKET_DEPOSIT_WALLET"),
    )
    async with (
        client,
        await client.subscribe(
            [
                CryptoPriceSpec(symbols=["btcusd", "ethusd"]),
                CryptoTwapPriceSpec(symbols=["btcusd"]),
                EquityPriceSpec(symbol="aapl"),
            ]
        ) as prices,
    ):
        count = 0
        async for event in prices:
            if event.type == "subscribe":
                print(event.topic, event.payload.symbol, event.payload.data)
            else:
                print(event.topic, event.payload.symbol, event.payload.value)
            count += 1
            if count == 20:
                break


if __name__ == "__main__":
    asyncio.run(main())
