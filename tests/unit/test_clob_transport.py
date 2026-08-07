# pyright: reportPrivateUsage=false
import asyncio
import dataclasses
import json
from decimal import Decimal
from typing import cast
from urllib.parse import parse_qs, urlparse

import httpx
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
    TokenId,
)
from polymarket._internal.context import AsyncSecureClientContext
from polymarket.clients._transport import AsyncTransport
from polymarket.errors import UnexpectedResponseError

PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
SIGNER_ADDRESS = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
FAKE_CREDS = ApiKeyCreds(key="test-key", passphrase="test-passphrase", secret="dGVzdA==")


def _clob_handler(captured: list[httpx.Request], payload: object) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=payload, request=request)

    return httpx.MockTransport(handler)


def _install_async_clob(
    client: AsyncPublicClient | AsyncSecureClient, handler: httpx.MockTransport
) -> None:
    transport = AsyncTransport(
        base_url="https://clob.test",
        client=httpx.AsyncClient(base_url="https://clob.test", transport=handler),
    )
    client._ctx = cast(AsyncSecureClientContext, dataclasses.replace(client._ctx, clob=transport))


def _body(request: httpx.Request) -> object:
    return json.loads(request.content)


def test_async_public_get_midpoint_hits_clob_midpoint_with_token_id() -> None:
    captured: list[httpx.Request] = []

    async def run() -> Decimal:
        async with AsyncPublicClient() as client:
            _install_async_clob(client, _clob_handler(captured, {"mid": "0.5125"}))
            return await client.get_midpoint(token_id="8501497")

    result = asyncio.run(run())

    assert result == Decimal("0.5125")
    assert len(captured) == 1
    parsed = urlparse(str(captured[0].url))
    assert captured[0].method == "GET"
    assert parsed.path == "/midpoint"
    assert parse_qs(parsed.query) == {"token_id": ["8501497"]}


def test_async_secure_get_midpoint_uses_same_clob_endpoint() -> None:
    captured: list[httpx.Request] = []

    async def run() -> Decimal:
        client = await AsyncSecureClient._create(
            private_key=PRIVATE_KEY,
            wallet=SIGNER_ADDRESS,
            credentials=FAKE_CREDS,
            validate_credentials=False,
        )
        try:
            _install_async_clob(client, _clob_handler(captured, {"mid": "0.42"}))
            return await client.get_midpoint(token_id="99")
        finally:
            await client.close()

    assert asyncio.run(run()) == Decimal("0.42")
    parsed = urlparse(str(captured[0].url))
    assert parsed.path == "/midpoint"


def test_async_get_midpoint_propagates_malformed_response_error() -> None:
    async def run() -> None:
        async with AsyncPublicClient() as client:
            _install_async_clob(client, _clob_handler([], {"unexpected": "shape"}))
            await client.get_midpoint(token_id="1")

    with pytest.raises(UnexpectedResponseError):
        asyncio.run(run())


def test_async_get_midpoints_posts_token_ids_to_clob() -> None:
    captured: list[httpx.Request] = []

    async def run() -> dict[TokenId, Decimal]:
        async with AsyncPublicClient() as client:
            _install_async_clob(client, _clob_handler(captured, {"1": "0.5", "2": "0.4"}))
            return await client.get_midpoints(token_ids=["1", "2"])

    result = asyncio.run(run())

    assert result == {"1": Decimal("0.5"), "2": Decimal("0.4")}
    assert captured[0].method == "POST"
    assert urlparse(str(captured[0].url)).path == "/midpoints"
    assert _body(captured[0]) == [{"token_id": "1"}, {"token_id": "2"}]


def test_async_get_price_includes_token_id_and_side() -> None:
    captured: list[httpx.Request] = []

    async def run() -> Decimal:
        async with AsyncPublicClient() as client:
            _install_async_clob(client, _clob_handler(captured, {"price": "0.52"}))
            return await client.get_price(token_id="123", side="BUY")

    result = asyncio.run(run())

    assert result == Decimal("0.52")
    parsed = urlparse(str(captured[0].url))
    assert parsed.path == "/price"
    assert parse_qs(parsed.query) == {"token_id": ["123"], "side": ["BUY"]}


def test_async_get_prices_posts_token_id_and_side() -> None:
    captured: list[httpx.Request] = []

    async def run() -> dict[TokenId, dict[OrderSide, Decimal]]:
        async with AsyncPublicClient() as client:
            _install_async_clob(
                client,
                _clob_handler(captured, {"1": {"BUY": "0.52", "SELL": "0.53"}}),
            )
            return await client.get_prices(
                requests=[PriceRequest("1", "BUY"), PriceRequest("1", "SELL")]
            )

    result = asyncio.run(run())

    assert result == {"1": {"BUY": Decimal("0.52"), "SELL": Decimal("0.53")}}
    assert captured[0].method == "POST"
    assert urlparse(str(captured[0].url)).path == "/prices"
    assert _body(captured[0]) == [
        {"token_id": "1", "side": "BUY"},
        {"token_id": "1", "side": "SELL"},
    ]


_ORDER_BOOK_PAYLOAD = {
    "market": "0xMARKET",
    "asset_id": "8501497",
    "timestamp": "1716000000000",
    "bids": [{"price": "0.51", "size": "100"}],
    "asks": [{"price": "0.53", "size": "200"}],
    "min_order_size": "5",
    "tick_size": "0.01",
    "neg_risk": False,
    "last_trade_price": "0.52",
    "hash": "abc123",
}


def test_async_get_order_book_returns_parsed_model() -> None:
    captured: list[httpx.Request] = []

    async def run() -> OrderBook:
        async with AsyncPublicClient() as client:
            _install_async_clob(client, _clob_handler(captured, _ORDER_BOOK_PAYLOAD))
            return await client.get_order_book(token_id="8501497")

    book = asyncio.run(run())

    assert urlparse(str(captured[0].url)).path == "/book"
    assert book.token_id == "8501497"
    assert book.min_order_size == Decimal("5")


def test_async_get_order_books_posts_token_ids() -> None:
    captured: list[httpx.Request] = []

    async def run() -> tuple[OrderBook, ...]:
        async with AsyncPublicClient() as client:
            _install_async_clob(client, _clob_handler(captured, [_ORDER_BOOK_PAYLOAD]))
            return await client.get_order_books(token_ids=["8501497"])

    books = asyncio.run(run())

    assert len(books) == 1
    assert captured[0].method == "POST"
    assert urlparse(str(captured[0].url)).path == "/books"
    assert _body(captured[0]) == [{"token_id": "8501497"}]


def test_async_get_spread_returns_decimal() -> None:
    captured: list[httpx.Request] = []

    async def run() -> Decimal:
        async with AsyncPublicClient() as client:
            _install_async_clob(client, _clob_handler(captured, {"spread": "0.02"}))
            return await client.get_spread(token_id="123")

    assert asyncio.run(run()) == Decimal("0.02")
    assert urlparse(str(captured[0].url)).path == "/spread"


def test_async_get_spreads_posts_token_ids() -> None:
    captured: list[httpx.Request] = []

    async def run() -> dict[TokenId, Decimal]:
        async with AsyncPublicClient() as client:
            _install_async_clob(client, _clob_handler(captured, {"1": "0.02"}))
            return await client.get_spreads(token_ids=["1"])

    assert asyncio.run(run()) == {"1": Decimal("0.02")}
    assert captured[0].method == "POST"
    assert urlparse(str(captured[0].url)).path == "/spreads"


def test_async_get_last_trade_price_returns_model() -> None:
    captured: list[httpx.Request] = []

    async def run() -> LastTradePrice | None:
        async with AsyncPublicClient() as client:
            _install_async_clob(client, _clob_handler(captured, {"price": "0.53", "side": "BUY"}))
            return await client.get_last_trade_price(token_id="123")

    result = asyncio.run(run())

    assert result is not None
    assert result.price == Decimal("0.53")
    assert result.side == "BUY"
    assert urlparse(str(captured[0].url)).path == "/last-trade-price"


def test_async_get_last_trade_prices_posts_token_ids_at_correct_path() -> None:
    captured: list[httpx.Request] = []

    async def run() -> tuple[LastTradePriceForToken, ...]:
        async with AsyncPublicClient() as client:
            _install_async_clob(
                client,
                _clob_handler(
                    captured,
                    [
                        {"token_id": "1", "price": "0.5", "side": "BUY"},
                        {"token_id": "2", "price": "0.6", "side": "SELL"},
                    ],
                ),
            )
            return await client.get_last_trade_prices(token_ids=["1", "2"])

    result = asyncio.run(run())

    assert len(result) == 2
    assert captured[0].method == "POST"
    assert urlparse(str(captured[0].url)).path == "/last-trades-prices"
    assert _body(captured[0]) == [{"token_id": "1"}, {"token_id": "2"}]


def test_async_get_price_history_maps_token_id_to_market_param() -> None:
    captured: list[httpx.Request] = []

    async def run() -> tuple[PriceHistoryPoint, ...]:
        async with AsyncPublicClient() as client:
            _install_async_clob(
                client, _clob_handler(captured, {"history": [{"t": 1000, "p": 0.5}]})
            )
            return await client.get_price_history(token_id="123")

    result = asyncio.run(run())

    assert len(result) == 1
    parsed = urlparse(str(captured[0].url))
    assert parsed.path == "/prices-history"
    assert parse_qs(parsed.query) == {"market": ["123"]}


def test_async_get_price_history_preserves_camelcase_optional_params_on_wire() -> None:
    captured: list[httpx.Request] = []

    async def run() -> tuple[PriceHistoryPoint, ...]:
        async with AsyncPublicClient() as client:
            _install_async_clob(client, _clob_handler(captured, {"history": []}))
            return await client.get_price_history(
                token_id="123",
                start_ts=1000,
                end_ts=2000,
                fidelity=60,
                interval="1d",
            )

    asyncio.run(run())

    parsed_qs = parse_qs(urlparse(str(captured[0].url)).query)
    assert parsed_qs == {
        "market": ["123"],
        "startTs": ["1000"],
        "endTs": ["2000"],
        "fidelity": ["60"],
        "interval": ["1d"],
    }
