"""Static realtime stream typing examples checked by pyright."""

from __future__ import annotations

from collections.abc import Callable
from types import CoroutineType
from typing import Any, assert_type

from polymarket import AsyncPublicClient, AsyncSecureClient
from polymarket.streams import (
    CryptoPriceEvent,
    CryptoPricesChainlinkTwapEvent,
    CryptoPricesChainlinkTwapSpec,  # pyright: ignore[reportDeprecated]
    CryptoPricesEvent,
    CryptoPriceSpec,
    CryptoPricesSpec,  # pyright: ignore[reportDeprecated]
    CryptoTwapPriceEvent,
    CryptoTwapPriceSpec,
    EquityPriceEvent,
    EquityPriceSpec,
    PriceEvent,
    SubscriptionHandle,
)


async def check_authenticated_price_typing(client: AsyncSecureClient) -> None:
    assert_type(
        await client.subscribe(CryptoPriceSpec(symbols=["btcusd"])),
        SubscriptionHandle[CryptoPriceEvent],
    )
    assert_type(
        await client.subscribe([CryptoTwapPriceSpec(symbols=["btcusd"])]),
        SubscriptionHandle[CryptoTwapPriceEvent],
    )
    assert_type(
        await client.subscribe(EquityPriceSpec(symbol="aapl")), SubscriptionHandle[EquityPriceEvent]
    )
    stream = await client.subscribe(
        [CryptoPriceSpec(symbols=["btcusd"]), EquityPriceSpec(symbol="aapl")]
    )
    assert_type(stream, SubscriptionHandle[CryptoPriceEvent | EquityPriceEvent])
    async with stream:
        async for event in stream:
            if event.type == "subscribe":
                print(event.payload.data)
            else:
                print(event.payload.value)

    assert_type(
        await client.subscribe(
            [CryptoPriceSpec(symbols=["btcusd"]), CryptoTwapPriceSpec(symbols=["btcusd"])]
        ),
        SubscriptionHandle[CryptoPriceEvent | CryptoTwapPriceEvent],
    )
    assert_type(
        await client.subscribe(
            [CryptoTwapPriceSpec(symbols=["btcusd"]), EquityPriceSpec(symbol="aapl")]
        ),
        SubscriptionHandle[CryptoTwapPriceEvent | EquityPriceEvent],
    )
    assert_type(
        await client.subscribe(
            [
                CryptoPriceSpec(symbols=["btcusd"]),
                CryptoTwapPriceSpec(symbols=["btcusd"]),
                EquityPriceSpec(symbol="aapl"),
            ]
        ),
        SubscriptionHandle[PriceEvent],
    )


async def _check_async_public_twap_typing(client: AsyncPublicClient) -> None:
    spec = CryptoPricesChainlinkTwapSpec(window_seconds=30)  # pyright: ignore[reportDeprecated]

    assert_type(
        await client.subscribe(spec),
        SubscriptionHandle[CryptoPricesChainlinkTwapEvent],
    )
    assert_type(
        await client.subscribe([spec]),
        SubscriptionHandle[CryptoPricesChainlinkTwapEvent],
    )
    assert_type(
        await client.subscribe(CryptoPricesSpec(topic="prices.crypto.chainlink")),  # pyright: ignore[reportDeprecated]
        SubscriptionHandle[CryptoPricesEvent],
    )


async def _check_async_secure_twap_typing(client: AsyncSecureClient) -> None:
    spec = CryptoPricesChainlinkTwapSpec(window_seconds=60)  # pyright: ignore[reportDeprecated]

    assert_type(
        await client.subscribe(spec),
        SubscriptionHandle[CryptoPricesChainlinkTwapEvent],
    )
    assert_type(
        await client.subscribe([spec]),
        SubscriptionHandle[CryptoPricesChainlinkTwapEvent],
    )
    assert_type(
        await client.subscribe(CryptoPricesSpec(topic="prices.crypto.chainlink")),  # pyright: ignore[reportDeprecated]
        SubscriptionHandle[CryptoPricesEvent],
    )


_async_public_twap_typing_check: Callable[[AsyncPublicClient], CoroutineType[Any, Any, None]] = (
    _check_async_public_twap_typing
)
_async_secure_twap_typing_check: Callable[[AsyncSecureClient], CoroutineType[Any, Any, None]] = (
    _check_async_secure_twap_typing
)
