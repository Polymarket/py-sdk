# pyright: reportPrivateUsage=false
import dataclasses
import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse

import httpx
import pytest
from eth_account import Account

from polymarket import ApiKeyCreds, SecureClient
from polymarket._internal.environment import PRODUCTION_CONFIG
from polymarket._internal.wallet import derive_uups_deposit_wallet_address
from polymarket.clients._transport import SyncTransport
from polymarket.errors import RequestRejectedError, UserInputError
from polymarket.models.clob.order_response import AcceptedOrder
from polymarket.models.types import TokenId

PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
SESSION_PRIVATE_KEY = "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
SIGNER_ADDRESS = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
FAKE_CREDS = ApiKeyCreds(key="test-key", passphrase="test-passphrase", secret="dGVzdA==")
_CONDITION_ID = "0x5c19f205507ce03ff5f3be08a8090a5969ea6870cc07b902a4ca2e61dfe48fdd"
_SESSION_SIGNER_MAGIC_HEX = "6492" * 16


def _public_routes() -> dict[str, Any]:
    return {
        "/markets-by-token/8501497": {"condition_id": _CONDITION_ID},
        f"/clob-markets/{_CONDITION_ID}": {
            "fd": {"r": 0, "e": 0},
            "mts": 0.01,
            "nr": False,
            "t": [{"t": "8501497", "o": "Yes"}, {"t": "8501498", "o": "No"}],
        },
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


def _make_client() -> SecureClient:
    return SecureClient._create(
        private_key=PRIVATE_KEY,
        wallet=SIGNER_ADDRESS,
        credentials=FAKE_CREDS,
        validate_credentials=False,
    )


def _make_session_client() -> SecureClient:
    owner = Account.from_key(PRIVATE_KEY)
    wallet = derive_uups_deposit_wallet_address(owner.address, PRODUCTION_CONFIG.wallet_derivation)
    return SecureClient._create(
        private_key=SESSION_PRIVATE_KEY,
        wallet=wallet,
        credentials=FAKE_CREDS,
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


def test_session_client_wraps_limit_order_signature_for_the_deposit_wallet() -> None:
    public_captured: list[httpx.Request] = []
    session_address = Account.from_key(SESSION_PRIVATE_KEY).address

    with _make_session_client() as client:
        assert client._ctx.signer_type == "SESSION_KEY"
        _install_clob(client, _routed_handler(public_captured, _public_routes()))
        signed = client.create_limit_order(
            token_id="8501497",
            price="0.5",
            size="10",
            side="BUY",
        )
        wallet = str(client.wallet)

    expected_signer_id = session_address[2:].lower().rjust(64, "0")
    assert signed.signature.startswith("0x" + expected_signer_id)
    assert signed.signature.endswith(_SESSION_SIGNER_MAGIC_HEX)
    assert signed.signature_type == 3
    assert signed.signer.lower() == wallet.lower()


def test_limit_and_protected_market_orders_reuse_cached_metadata() -> None:
    public_captured: list[httpx.Request] = []

    with _make_client() as client:
        _install_clob(client, _routed_handler(public_captured, _public_routes()))
        client.create_limit_order(token_id="8501497", price="0.5", size="10", side="BUY")
        client.create_market_order(token_id="8501497", side="BUY", amount="5", max_price="0.5")

    paths = [urlparse(str(request.url)).path for request in public_captured]
    assert paths.count("/markets-by-token/8501497") == 1
    assert paths.count(f"/clob-markets/{_CONDITION_ID}") == 1
    assert "/book" not in paths


def test_protected_market_buy_rounds_shares_down_on_the_sync_client() -> None:
    with _make_client() as client:
        _install_clob(client, _routed_handler([], _public_routes()))
        signed = client.create_market_order(
            token_id="8501497", side="BUY", amount="100", max_price="0.55"
        )

    # Same construction as the async path: maker stays the cent-rounded amount and
    # 100 / 0.55 = 181.8181... shares round DOWN, so the encoded price is at or above
    # max_price and the order can lift an ask resting at 0.55.
    assert signed.maker_amount == 100_000_000
    assert signed.taker_amount == 181_818_100


def test_concurrent_metadata_reads_are_coalesced() -> None:
    public_captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = urlparse(str(request.url)).path
        public_captured.append(request)
        if path == f"/clob-markets/{_CONDITION_ID}":
            time.sleep(0.02)
        payload = _public_routes().get(path)
        if payload is None:
            return httpx.Response(404, json={"error": "not mocked"}, request=request)
        return httpx.Response(200, json=payload, request=request)

    with _make_client() as client:
        _install_clob(client, httpx.MockTransport(handler))
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = tuple(
                executor.submit(
                    client._ctx.order_metadata.resolve_market,
                    client._ctx,
                    token_id=TokenId("8501497"),
                )
                for _ in range(3)
            )
            results = tuple(future.result() for future in futures)

    assert all(result.tick_size == Decimal("0.01") for result in results)
    paths = [urlparse(str(request.url)).path for request in public_captured]
    assert paths.count("/markets-by-token/8501497") == 1
    assert paths.count(f"/clob-markets/{_CONDITION_ID}") == 1


def test_failed_market_metadata_request_is_retried() -> None:
    public_captured: list[httpx.Request] = []
    market_requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal market_requests
        public_captured.append(request)
        path = urlparse(str(request.url)).path
        if path == "/markets-by-token/8501497":
            return httpx.Response(200, json={"condition_id": _CONDITION_ID}, request=request)
        if path == f"/clob-markets/{_CONDITION_ID}":
            market_requests += 1
            if market_requests == 1:
                return httpx.Response(500, json={"error": "try again"}, request=request)
            return httpx.Response(200, json=_public_routes()[path], request=request)
        return httpx.Response(404, json={"error": "not mocked"}, request=request)

    with _make_client() as client:
        _install_clob(client, httpx.MockTransport(handler))
        with pytest.raises(RequestRejectedError, match="try again"):
            client.create_limit_order(token_id="8501497", price="0.5", size="10", side="BUY")
        client.create_limit_order(token_id="8501497", price="0.5", size="10", side="BUY")

    paths = [urlparse(str(request.url)).path for request in public_captured]
    assert paths.count("/markets-by-token/8501497") == 1
    assert paths.count(f"/clob-markets/{_CONDITION_ID}") == 2


def test_protected_max_spend_refreshes_tick_and_fee_metadata_together() -> None:
    public_captured: list[httpx.Request] = []
    market_requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal market_requests
        public_captured.append(request)
        path = urlparse(str(request.url)).path
        if path == "/markets-by-token/8501497":
            return httpx.Response(200, json={"condition_id": _CONDITION_ID}, request=request)
        if path == f"/clob-markets/{_CONDITION_ID}":
            market_requests += 1
            return httpx.Response(
                200,
                json={
                    "fd": {"r": 0 if market_requests == 1 else 0.1, "e": 0},
                    "mts": 0.01 if market_requests == 1 else 0.001,
                    "nr": False,
                    "t": [{"t": "8501497", "o": "Yes"}],
                },
                request=request,
            )
        return httpx.Response(404, json={"error": "not mocked"}, request=request)

    with _make_client() as client:
        _install_clob(client, httpx.MockTransport(handler))
        first = client.create_market_order(
            token_id="8501497",
            side="BUY",
            amount="10",
            max_spend="10",
            max_price="0.5",
        )
        second = client.create_market_order(
            token_id="8501497",
            side="BUY",
            amount="10",
            max_spend="10",
            max_price="0.555",
        )

    assert first.maker_amount == 10_000_000
    assert second.maker_amount < first.maker_amount
    paths = [urlparse(str(request.url)).path for request in public_captured]
    assert paths.count("/markets-by-token/8501497") == 1
    assert paths.count(f"/clob-markets/{_CONDITION_ID}") == 2


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
