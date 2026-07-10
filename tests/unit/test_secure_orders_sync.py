# pyright: reportPrivateUsage=false
import dataclasses
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse

import httpx
import pytest

from polymarket import ApiKeyCreds, BuilderApiKey, SecureClient
from polymarket.clients._transport import SyncTransport
from polymarket.errors import UserInputError
from polymarket.models.clob.order_response import AcceptedOrder

PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
SIGNER_ADDRESS = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
FAKE_CREDS = ApiKeyCreds(key="test-key", passphrase="test-passphrase", secret="dGVzdA==")
BUILDER_KEY = BuilderApiKey(key="builder-key", passphrase="builder-passphrase", secret="dGVzdA==")


def _public_routes() -> dict[str, Any]:
    return {
        "/tick-size": {"minimum_tick_size": 0.01},
        "/neg-risk": {"neg_risk": False},
    }


def _secure_routes(*, has_allowance: bool = True) -> dict[str, Any]:
    allowance = "100000000000" if has_allowance else "0"
    return {
        "/balance-allowance": {
            "balance": allowance,
            "allowances": {
                "0xE111180000d2663C0091e4f400237545B87B996B": allowance,
                "0xe2222d279d744050d28e00520010520000310F59": allowance,
            },
        },
        "/order": {
            "errorMsg": "",
            "makingAmount": "5",
            "orderID": "ord-1",
            "status": "live",
            "success": True,
            "takingAmount": "10",
            "tradeIDs": [],
            "transactionsHashes": [],
        },
        "/orders": [
            {
                "errorMsg": "",
                "makingAmount": "5",
                "orderID": "ord-2",
                "status": "live",
                "success": True,
                "takingAmount": "10",
                "tradeIDs": [],
                "transactionsHashes": [],
            }
        ],
        "/cancel-all": {"canceled": ["ord-1", "ord-2"], "not_canceled": {}},
        "/cancel-market-orders": {"canceled": ["ord-3"], "not_canceled": {}},
    }


def _routed_handler(captured: list[httpx.Request], routes: dict[str, Any]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        path = urlparse(str(request.url)).path
        if path == "/order" and request.method == "DELETE":
            return httpx.Response(
                200, json={"canceled": ["ord-1"], "not_canceled": {}}, request=request
            )
        if path == "/orders" and request.method == "DELETE":
            return httpx.Response(
                200, json={"canceled": ["a", "b"], "not_canceled": {}}, request=request
            )
        if path in routes:
            return httpx.Response(200, json=routes[path], request=request)
        return httpx.Response(404, json={"error": "not mocked"}, request=request)

    return httpx.MockTransport(handler)


def _install_clob(client: SecureClient, handler: httpx.MockTransport) -> None:
    transport = SyncTransport(
        base_url="https://clob.test",
        client=httpx.Client(base_url="https://clob.test", transport=handler),
    )
    client._ctx = dataclasses.replace(client._ctx, clob=transport)


def _install_secure_clob(client: SecureClient, handler: httpx.MockTransport) -> None:
    transport = SyncTransport(
        base_url="https://clob.test",
        client=httpx.Client(base_url="https://clob.test", transport=handler),
        header_resolver=client._ctx.secure_clob._header_resolver,
    )
    client._ctx = dataclasses.replace(client._ctx, secure_clob=transport)


def _make_client(*, builder_auth: bool = False) -> SecureClient:
    return SecureClient._create(
        private_key=PRIVATE_KEY,
        wallet=SIGNER_ADDRESS,
        credentials=FAKE_CREDS,
        api_key=BUILDER_KEY if builder_auth else None,
        validate_credentials=False,
    )


def test_create_limit_order_signs_and_returns_signed_order() -> None:
    public_captured: list[httpx.Request] = []
    secure_captured: list[httpx.Request] = []

    with _make_client() as client:
        _install_clob(client, _routed_handler(public_captured, _public_routes()))
        _install_secure_clob(client, _routed_handler(secure_captured, _secure_routes()))
        signed = client.create_limit_order(token_id="8501497", price="0.5", size="10", side="BUY")

    assert signed.signature.startswith("0x")
    assert len(signed.signature) >= 132
    assert signed.maker_amount == 5_000_000
    assert signed.taker_amount == 10_000_000
    assert signed.order_type == "GTC"
    assert signed.post_only is False


def test_create_limit_order_does_not_preflight_allowance() -> None:
    secure_captured: list[httpx.Request] = []

    with _make_client() as client:
        _install_clob(client, _routed_handler([], _public_routes()))
        _install_secure_clob(
            client, _routed_handler(secure_captured, _secure_routes(has_allowance=False))
        )
        client.create_limit_order(token_id="8501497", price="0.5", size="10", side="BUY")

    paths = [urlparse(str(r.url)).path for r in secure_captured]
    assert "/balance-allowance" not in paths
    assert "/balance-allowance/update" not in paths


def test_place_limit_order_posts_after_signing() -> None:
    secure_captured: list[httpx.Request] = []

    with _make_client() as client:
        _install_clob(client, _routed_handler([], _public_routes()))
        _install_secure_clob(client, _routed_handler(secure_captured, _secure_routes()))
        response = client.place_limit_order(token_id="8501497", price="0.5", size="10", side="BUY")

    assert isinstance(response, AcceptedOrder)
    assert response.order_id == "ord-1"
    post_request = next(
        r for r in secure_captured if r.method == "POST" and urlparse(str(r.url)).path == "/order"
    )
    assert post_request.headers.get("POLY_SIGNATURE")


def test_place_limit_order_sends_builder_headers() -> None:
    secure_captured: list[httpx.Request] = []

    with _make_client(builder_auth=True) as client:
        _install_clob(client, _routed_handler([], _public_routes()))
        _install_secure_clob(client, _routed_handler(secure_captured, _secure_routes()))
        client.place_limit_order(token_id="8501497", price="0.5", size="10", side="BUY")

    post_request = next(
        r for r in secure_captured if r.method == "POST" and urlparse(str(r.url)).path == "/order"
    )
    assert post_request.headers.get("POLY_SIGNATURE")
    assert post_request.headers.get("POLY_BUILDER_API_KEY") == BUILDER_KEY.key
    assert post_request.headers.get("POLY_BUILDER_PASSPHRASE") == BUILDER_KEY.passphrase
    assert post_request.headers.get("POLY_BUILDER_SIGNATURE")


def test_place_market_order_buy_signs_and_posts() -> None:
    secure_captured: list[httpx.Request] = []
    public_routes = {
        **_public_routes(),
        "/book": {
            "asset_id": "8501497",
            "market": "0xMARKET",
            "bids": [],
            "asks": [{"price": "0.50", "size": "100"}],
            "min_order_size": "1",
            "tick_size": "0.01",
            "neg_risk": False,
            "hash": "0xhash",
            "timestamp": "0",
        },
    }

    with _make_client() as client:
        _install_clob(client, _routed_handler([], public_routes))
        _install_secure_clob(client, _routed_handler(secure_captured, _secure_routes()))
        response = client.place_market_order(token_id="8501497", side="BUY", amount=Decimal(2))

    assert isinstance(response, AcceptedOrder)


def test_post_order_validation_rejects_post_only_on_market_order() -> None:
    with pytest.raises(UserInputError, match="post-only"), _make_client() as client:
        _install_clob(client, _routed_handler([], _public_routes()))
        _install_secure_clob(client, _routed_handler([], _secure_routes()))
        signed = client.create_limit_order(token_id="8501497", price="0.5", size="10", side="BUY")
        mutated = dataclasses.replace(signed, order_type="FAK", post_only=True)
        client.post_order(mutated)


def test_cancel_order_targets_order_path() -> None:
    captured: list[httpx.Request] = []

    with _make_client() as client:
        _install_secure_clob(client, _routed_handler(captured, _secure_routes()))
        client.cancel_order(order_id="ord-1")

    delete = captured[0]
    assert delete.method == "DELETE"
    assert urlparse(str(delete.url)).path == "/order"
    body = delete.content.decode()
    assert "orderID" in body


def test_cancel_all_targets_cancel_all_path() -> None:
    captured: list[httpx.Request] = []

    with _make_client() as client:
        _install_secure_clob(client, _routed_handler(captured, _secure_routes()))
        response = client.cancel_all()

    assert response.canceled == ("ord-1", "ord-2")
    assert urlparse(str(captured[0].url)).path == "/cancel-all"


def test_cancel_market_orders_sends_filters_in_body() -> None:
    captured: list[httpx.Request] = []

    with _make_client() as client:
        _install_secure_clob(client, _routed_handler(captured, _secure_routes()))
        client.cancel_market_orders(market="0xMARKET", token_id="8501497")

    request = captured[0]
    assert urlparse(str(request.url)).path == "/cancel-market-orders"
    body = request.content.decode()
    assert "0xMARKET" in body
    assert "asset_id" in body


def test_cancel_market_orders_requires_market_or_token() -> None:
    with pytest.raises(UserInputError, match="market or token_id"), _make_client() as client:
        client.cancel_market_orders()
