# pyright: reportPrivateUsage=false
import asyncio
from decimal import Decimal

import pytest

from polymarket import (
    ApiKeyCreds,
    AsyncPublicClient,
    AsyncSecureClient,
    LastTradePrice,
    LastTradePriceForToken,
    OrderBook,
    OrderSide,
    PriceHistoryPoint,
    PriceRequest,
)
from polymarket.models.types import TokenId

PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
SIGNER_ADDRESS = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
FAKE_CREDS = ApiKeyCreds(key="test-key", passphrase="test-passphrase", secret="dGVzdA==")


@pytest.mark.integration
def test_async_public_get_midpoint_returns_decimal_in_unit_range(
    active_clob_token: TokenId,
) -> None:
    async def run() -> Decimal:
        async with AsyncPublicClient() as client:
            return await client.get_midpoint(token_id=active_clob_token)

    midpoint = asyncio.run(run())

    assert isinstance(midpoint, Decimal)
    assert Decimal("0") <= midpoint <= Decimal("1")


@pytest.mark.integration
def test_async_secure_get_midpoint_returns_decimal_in_unit_range(
    active_clob_token: TokenId,
) -> None:
    async def run() -> Decimal:
        client = await AsyncSecureClient._create(
            private_key=PRIVATE_KEY,
            wallet=SIGNER_ADDRESS,
            credentials=FAKE_CREDS,
            validate_credentials=False,
        )
        try:
            return await client.get_midpoint(token_id=active_clob_token)
        finally:
            await client.close()

    midpoint = asyncio.run(run())

    assert isinstance(midpoint, Decimal)
    assert Decimal("0") <= midpoint <= Decimal("1")


@pytest.mark.integration
def test_async_get_midpoints_returns_decimal_per_token(active_clob_token: TokenId) -> None:
    async def run() -> dict[TokenId, Decimal]:
        async with AsyncPublicClient() as client:
            return await client.get_midpoints(token_ids=[active_clob_token])

    result = asyncio.run(run())

    assert active_clob_token in result
    assert isinstance(result[active_clob_token], Decimal)


@pytest.mark.integration
def test_async_get_price_returns_decimal_for_buy_side(active_clob_token: TokenId) -> None:
    async def run() -> Decimal:
        async with AsyncPublicClient() as client:
            return await client.get_price(token_id=active_clob_token, side="BUY")

    price = asyncio.run(run())

    assert isinstance(price, Decimal)
    assert Decimal("0") <= price <= Decimal("1")


@pytest.mark.integration
def test_async_get_prices_returns_decimal_per_token_and_side(active_clob_token: TokenId) -> None:
    async def run() -> dict[TokenId, dict[OrderSide, Decimal]]:
        async with AsyncPublicClient() as client:
            return await client.get_prices(
                requests=[
                    PriceRequest(active_clob_token, "BUY"),
                    PriceRequest(active_clob_token, "SELL"),
                ]
            )

    result = asyncio.run(run())

    assert active_clob_token in result
    sides = result[active_clob_token]
    assert "BUY" in sides or "SELL" in sides


@pytest.mark.integration
def test_async_get_order_book_returns_book_with_levels(active_clob_token: TokenId) -> None:
    async def run() -> OrderBook:
        async with AsyncPublicClient() as client:
            return await client.get_order_book(token_id=active_clob_token)

    book = asyncio.run(run())

    assert isinstance(book, OrderBook)
    assert book.token_id == active_clob_token
    assert isinstance(book.min_order_size, Decimal)
    assert isinstance(book.tick_size, Decimal)


@pytest.mark.integration
def test_async_get_order_books_returns_tuple_of_books(active_clob_token: TokenId) -> None:
    async def run() -> tuple[OrderBook, ...]:
        async with AsyncPublicClient() as client:
            return await client.get_order_books(token_ids=[active_clob_token])

    books = asyncio.run(run())

    assert len(books) >= 1
    assert any(book.token_id == active_clob_token for book in books)


@pytest.mark.integration
def test_async_get_spread_returns_non_negative_decimal(active_clob_token: TokenId) -> None:
    async def run() -> Decimal:
        async with AsyncPublicClient() as client:
            return await client.get_spread(token_id=active_clob_token)

    spread = asyncio.run(run())

    assert isinstance(spread, Decimal)
    assert spread >= Decimal("0")


@pytest.mark.integration
def test_async_get_spreads_returns_decimal_per_token(active_clob_token: TokenId) -> None:
    async def run() -> dict[TokenId, Decimal]:
        async with AsyncPublicClient() as client:
            return await client.get_spreads(token_ids=[active_clob_token])

    result = asyncio.run(run())

    assert active_clob_token in result
    assert isinstance(result[active_clob_token], Decimal)


@pytest.mark.integration
def test_async_get_last_trade_price_returns_model(active_clob_token: TokenId) -> None:
    async def run() -> LastTradePrice | None:
        async with AsyncPublicClient() as client:
            return await client.get_last_trade_price(token_id=active_clob_token)

    last = asyncio.run(run())

    assert isinstance(last, LastTradePrice)
    assert isinstance(last.price, Decimal)
    assert last.side in ("BUY", "SELL")


@pytest.mark.integration
def test_async_get_last_trade_prices_returns_tuple_of_models(active_clob_token: TokenId) -> None:
    async def run() -> tuple[LastTradePriceForToken, ...]:
        async with AsyncPublicClient() as client:
            return await client.get_last_trade_prices(token_ids=[active_clob_token])

    result = asyncio.run(run())

    assert len(result) >= 1
    assert any(point.token_id == active_clob_token for point in result)


@pytest.mark.integration
def test_async_get_price_history_returns_points(active_clob_token: TokenId) -> None:
    async def run() -> tuple[PriceHistoryPoint, ...]:
        async with AsyncPublicClient() as client:
            return await client.get_price_history(token_id=active_clob_token, interval="1d")

    points = asyncio.run(run())

    assert isinstance(points, tuple)
    for point in points:
        assert isinstance(point.t, int)
        assert isinstance(point.p, float)
