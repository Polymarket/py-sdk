# pyright: reportPrivateUsage=false
import dataclasses
import json
from decimal import Decimal
from typing import cast
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from polymarket import (
    ApiKeyCreds,
    LastTradePrice,
    LastTradePriceForToken,
    OrderBook,
    PriceHistoryPoint,
    PriceRequest,
    PublicClient,
    SecureClient,
    TokenId,
)
from polymarket._internal.context import SyncSecureClientContext
from polymarket.clients._transport import SyncTransport
from polymarket.errors import InsufficientLiquidityError, UnexpectedResponseError

PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
SIGNER_ADDRESS = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
FAKE_CREDS = ApiKeyCreds(key="test-key", passphrase="test-passphrase", secret="dGVzdA==")


def _clob_handler(captured: list[httpx.Request], payload: object) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=payload, request=request)

    return httpx.MockTransport(handler)


def _routed_handler(
    captured: list[httpx.Request], routes: dict[str, object]
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        path = urlparse(str(request.url)).path
        if path in routes:
            return httpx.Response(200, json=routes[path], request=request)
        return httpx.Response(404, json={"error": "not mocked"}, request=request)

    return httpx.MockTransport(handler)


def _install_sync_clob(client: PublicClient | SecureClient, handler: httpx.MockTransport) -> None:
    transport = SyncTransport(
        base_url="https://clob.test",
        client=httpx.Client(base_url="https://clob.test", transport=handler),
    )
    client._ctx = cast(SyncSecureClientContext, dataclasses.replace(client._ctx, clob=transport))


def _body(request: httpx.Request) -> object:
    return json.loads(request.content)


def _secure_client() -> SecureClient:
    return SecureClient._create(
        private_key=PRIVATE_KEY,
        wallet=SIGNER_ADDRESS,
        credentials=FAKE_CREDS,
        validate_credentials=False,
    )


class TestGetMidpoint:
    def test_public_hits_clob_midpoint_with_token_id(self) -> None:
        captured: list[httpx.Request] = []
        with PublicClient() as client:
            _install_sync_clob(client, _clob_handler(captured, {"mid": "0.5125"}))
            result = client.get_midpoint(token_id="8501497")

        assert result == Decimal("0.5125")
        assert len(captured) == 1
        parsed = urlparse(str(captured[0].url))
        assert captured[0].method == "GET"
        assert parsed.path == "/midpoint"
        assert parse_qs(parsed.query) == {"token_id": ["8501497"]}

    def test_secure_uses_same_clob_endpoint(self) -> None:
        captured: list[httpx.Request] = []
        with _secure_client() as client:
            _install_sync_clob(client, _clob_handler(captured, {"mid": "0.42"}))
            result = client.get_midpoint(token_id="99")

        assert result == Decimal("0.42")
        assert urlparse(str(captured[0].url)).path == "/midpoint"

    def test_propagates_malformed_response_error(self) -> None:
        with PublicClient() as client:
            _install_sync_clob(client, _clob_handler([], {"unexpected": "shape"}))
            with pytest.raises(UnexpectedResponseError):
                client.get_midpoint(token_id="1")


class TestGetMidpoints:
    def test_posts_token_ids_to_clob(self) -> None:
        captured: list[httpx.Request] = []
        with PublicClient() as client:
            _install_sync_clob(client, _clob_handler(captured, {"1": "0.5", "2": "0.4"}))
            result = client.get_midpoints(token_ids=["1", "2"])

        assert result == {"1": Decimal("0.5"), "2": Decimal("0.4")}
        assert captured[0].method == "POST"
        assert urlparse(str(captured[0].url)).path == "/midpoints"
        assert _body(captured[0]) == [{"token_id": "1"}, {"token_id": "2"}]


class TestGetPrice:
    def test_includes_token_id_and_side(self) -> None:
        captured: list[httpx.Request] = []
        with PublicClient() as client:
            _install_sync_clob(client, _clob_handler(captured, {"price": "0.52"}))
            result = client.get_price(token_id="123", side="BUY")

        assert result == Decimal("0.52")
        parsed = urlparse(str(captured[0].url))
        assert parsed.path == "/price"
        assert parse_qs(parsed.query) == {"token_id": ["123"], "side": ["BUY"]}


class TestGetPrices:
    def test_posts_token_id_and_side(self) -> None:
        captured: list[httpx.Request] = []
        payload: dict[str, dict[str, str]] = {
            "tok-1": {"BUY": "0.50", "SELL": "0.51"},
            "tok-2": {"BUY": "0.30"},
        }
        with PublicClient() as client:
            _install_sync_clob(client, _clob_handler(captured, payload))
            result = client.get_prices(
                requests=[
                    PriceRequest(token_id="tok-1", side="BUY"),
                    PriceRequest(token_id="tok-1", side="SELL"),
                    PriceRequest(token_id="tok-2", side="BUY"),
                ]
            )

        assert result[TokenId("tok-1")]["BUY"] == Decimal("0.50")
        assert urlparse(str(captured[0].url)).path == "/prices"
        assert captured[0].method == "POST"


class TestGetOrderBook:
    def test_returns_parsed_model(self) -> None:
        captured: list[httpx.Request] = []
        with PublicClient() as client:
            _install_sync_clob(
                client,
                _clob_handler(
                    captured,
                    {
                        "asset_id": "1",
                        "market": "0xM",
                        "bids": [],
                        "asks": [{"price": "0.5", "size": "10"}],
                        "min_order_size": "1",
                        "tick_size": "0.01",
                        "neg_risk": False,
                        "hash": "0xhash",
                        "timestamp": "0",
                    },
                ),
            )
            book = client.get_order_book(token_id="1")

        assert isinstance(book, OrderBook)
        assert urlparse(str(captured[0].url)).path == "/book"


class TestGetOrderBooks:
    def test_posts_token_ids(self) -> None:
        captured: list[httpx.Request] = []
        payload: list[dict[str, object]] = [
            {
                "asset_id": "1",
                "market": "0xM",
                "bids": [],
                "asks": [],
                "min_order_size": "1",
                "tick_size": "0.01",
                "neg_risk": False,
                "hash": "0xhash",
                "timestamp": "0",
            }
        ]
        with PublicClient() as client:
            _install_sync_clob(client, _clob_handler(captured, payload))
            books = client.get_order_books(token_ids=["1"])

        assert len(books) == 1
        assert captured[0].method == "POST"
        assert urlparse(str(captured[0].url)).path == "/books"
        assert _body(captured[0]) == [{"token_id": "1"}]


class TestGetSpread:
    def test_returns_decimal(self) -> None:
        captured: list[httpx.Request] = []
        with PublicClient() as client:
            _install_sync_clob(client, _clob_handler(captured, {"spread": "0.02"}))
            spread = client.get_spread(token_id="1")

        assert spread == Decimal("0.02")
        assert urlparse(str(captured[0].url)).path == "/spread"


class TestGetSpreads:
    def test_posts_token_ids(self) -> None:
        captured: list[httpx.Request] = []
        with PublicClient() as client:
            _install_sync_clob(client, _clob_handler(captured, {"1": "0.02", "2": "0.03"}))
            spreads = client.get_spreads(token_ids=["1", "2"])

        assert spreads == {"1": Decimal("0.02"), "2": Decimal("0.03")}
        assert urlparse(str(captured[0].url)).path == "/spreads"


class TestGetLastTradePrice:
    def test_returns_model(self) -> None:
        captured: list[httpx.Request] = []
        with PublicClient() as client:
            _install_sync_clob(
                client,
                _clob_handler(captured, {"asset_id": "1", "price": "0.55", "side": "BUY"}),
            )
            ltp = client.get_last_trade_price(token_id="1")

        assert isinstance(ltp, LastTradePrice)
        assert urlparse(str(captured[0].url)).path == "/last-trade-price"


class TestGetLastTradePrices:
    def test_posts_token_ids_at_correct_path(self) -> None:
        captured: list[httpx.Request] = []
        payload: list[dict[str, str]] = [
            {"token_id": "1", "price": "0.5", "side": "BUY"},
        ]
        with PublicClient() as client:
            _install_sync_clob(client, _clob_handler(captured, payload))
            result = client.get_last_trade_prices(token_ids=["1"])

        assert len(result) == 1
        assert isinstance(result[0], LastTradePriceForToken)
        assert urlparse(str(captured[0].url)).path == "/last-trades-prices"
        assert _body(captured[0]) == [{"token_id": "1"}]


class TestGetPriceHistory:
    def test_maps_token_id_to_market_param(self) -> None:
        captured: list[httpx.Request] = []
        with PublicClient() as client:
            _install_sync_clob(
                client,
                _clob_handler(captured, {"history": [{"t": 1700000000, "p": 0.5}]}),
            )
            result = client.get_price_history(token_id="abc")

        assert len(result) == 1
        assert isinstance(result[0], PriceHistoryPoint)
        parsed = urlparse(str(captured[0].url))
        assert parsed.path == "/prices-history"
        assert parse_qs(parsed.query) == {"market": ["abc"]}

    def test_preserves_camelcase_optional_params_on_wire(self) -> None:
        captured: list[httpx.Request] = []
        with PublicClient() as client:
            _install_sync_clob(client, _clob_handler(captured, {"history": []}))
            client.get_price_history(
                token_id="abc",
                start_ts=1700000000,
                end_ts=1700001000,
                fidelity=60,
                interval="1d",
            )

        parsed = urlparse(str(captured[0].url))
        qs = parse_qs(parsed.query)
        assert qs["market"] == ["abc"]
        assert qs["startTs"] == ["1700000000"]
        assert qs["endTs"] == ["1700001000"]
        assert qs["fidelity"] == ["60"]
        assert qs["interval"] == ["1d"]


class TestEstimateMarketPrice:
    def test_buy_fetches_tick_size_and_book(self) -> None:
        captured: list[httpx.Request] = []
        routes: dict[str, object] = {
            "/tick-size": {"minimum_tick_size": 0.01},
            "/book": {
                "asset_id": "1",
                "market": "0xM",
                "bids": [{"price": "0.49", "size": "100"}],
                "asks": [{"price": "0.50", "size": "100"}],
                "min_order_size": "1",
                "tick_size": "0.01",
                "neg_risk": False,
                "hash": "0xhash",
                "timestamp": "0",
            },
        }
        with PublicClient() as client:
            _install_sync_clob(client, _routed_handler(captured, routes))
            price = client.estimate_market_price(token_id="1", side="BUY", amount=Decimal(2))

        assert price == Decimal("0.50")
        paths = [urlparse(str(r.url)).path for r in captured]
        assert "/tick-size" in paths
        assert "/book" in paths

    def test_sell_uses_bids(self) -> None:
        captured: list[httpx.Request] = []
        routes: dict[str, object] = {
            "/tick-size": {"minimum_tick_size": 0.01},
            "/book": {
                "asset_id": "1",
                "market": "0xM",
                "bids": [{"price": "0.49", "size": "100"}],
                "asks": [{"price": "0.50", "size": "100"}],
                "min_order_size": "1",
                "tick_size": "0.01",
                "neg_risk": False,
                "hash": "0xhash",
                "timestamp": "0",
            },
        }
        with PublicClient() as client:
            _install_sync_clob(client, _routed_handler(captured, routes))
            price = client.estimate_market_price(token_id="1", side="SELL", shares=Decimal(1))

        assert price == Decimal("0.49")

    def test_fok_raises_on_insufficient_liquidity(self) -> None:
        routes: dict[str, object] = {
            "/tick-size": {"minimum_tick_size": 0.01},
            "/book": {
                "asset_id": "1",
                "market": "0xM",
                "bids": [],
                "asks": [{"price": "0.50", "size": "1"}],
                "min_order_size": "1",
                "tick_size": "0.01",
                "neg_risk": False,
                "hash": "0xhash",
                "timestamp": "0",
            },
        }
        with PublicClient() as client:
            _install_sync_clob(client, _routed_handler([], routes))
            with pytest.raises(InsufficientLiquidityError):
                client.estimate_market_price(
                    token_id="1", side="BUY", amount=Decimal(1000), order_type="FOK"
                )

    def test_available_on_secure_client(self) -> None:
        routes: dict[str, object] = {
            "/tick-size": {"minimum_tick_size": 0.01},
            "/book": {
                "asset_id": "1",
                "market": "0xM",
                "bids": [],
                "asks": [{"price": "0.5", "size": "100"}],
                "min_order_size": "1",
                "tick_size": "0.01",
                "neg_risk": False,
                "hash": "0xhash",
                "timestamp": "0",
            },
        }
        with _secure_client() as client:
            _install_sync_clob(client, _routed_handler([], routes))
            price = client.estimate_market_price(token_id="1", side="BUY", amount=Decimal(1))

        assert price == Decimal("0.5")
