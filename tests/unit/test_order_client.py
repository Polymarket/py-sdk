# pyright: reportPrivateUsage=false
import asyncio
import dataclasses
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse

import httpx
import pytest

from polymarket import ApiKeyCreds, AsyncSecureClient
from polymarket._internal.actions.orders.cache import AsyncOrderMetadataCache
from polymarket.clients._transport import AsyncTransport
from polymarket.errors import RequestRejectedError, UnexpectedResponseError, UserInputError
from polymarket.models.clob.order_response import AcceptedOrder

PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
SIGNER_ADDRESS = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
FAKE_CREDS = ApiKeyCreds(key="test-key", passphrase="test-passphrase", secret="dGVzdA==")
_CONDITION_ID = "0x5c19f205507ce03ff5f3be08a8090a5969ea6870cc07b902a4ca2e61dfe48fdd"


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
        # Handle path-with-id for /order/{id}
        if path.startswith("/order/") and request.method == "DELETE":
            return httpx.Response(
                200, json={"canceled": ["ord-1"], "not_canceled": {}}, request=request
            )
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


def _install_clob(client: AsyncSecureClient, handler: httpx.MockTransport) -> None:
    transport = AsyncTransport(
        base_url="https://clob.test",
        client=httpx.AsyncClient(base_url="https://clob.test", transport=handler),
    )
    client._ctx = dataclasses.replace(client._ctx, clob=transport)


def _install_secure_clob(client: AsyncSecureClient, handler: httpx.MockTransport) -> None:
    transport = AsyncTransport(
        base_url="https://clob.test",
        client=httpx.AsyncClient(base_url="https://clob.test", transport=handler),
        header_resolver=client._ctx.secure_clob._header_resolver,
    )
    client._ctx = dataclasses.replace(client._ctx, secure_clob=transport)


async def _make_client() -> AsyncSecureClient:
    return await AsyncSecureClient._create(
        private_key=PRIVATE_KEY,
        wallet=SIGNER_ADDRESS,
        credentials=FAKE_CREDS,
        validate_credentials=False,
    )


def test_create_limit_order_signs_and_returns_signed_order() -> None:
    public_captured: list[httpx.Request] = []
    secure_captured: list[httpx.Request] = []

    async def run() -> None:
        client = await _make_client()
        try:
            _install_clob(client, _routed_handler(public_captured, _public_routes()))
            _install_secure_clob(client, _routed_handler(secure_captured, _secure_routes()))
            signed = await client.create_limit_order(
                token_id="8501497", price="0.5", size="10", side="BUY"
            )
            assert signed.signature.startswith("0x")
            assert len(signed.signature) >= 132
            assert signed.maker_amount == 5_000_000
            assert signed.taker_amount == 10_000_000
            assert signed.order_type == "GTC"
            assert signed.post_only is False
        finally:
            await client.close()

    asyncio.run(run())


def test_limit_and_protected_market_orders_reuse_cached_metadata() -> None:
    public_captured: list[httpx.Request] = []

    async def run() -> None:
        client = await _make_client()
        try:
            _install_clob(client, _routed_handler(public_captured, _public_routes()))
            await client.create_limit_order(token_id="8501497", price="0.5", size="10", side="BUY")
            await client.create_market_order(
                token_id="8501497", side="BUY", amount="5", max_price="0.5"
            )
        finally:
            await client.close()

    asyncio.run(run())
    paths = [urlparse(str(request.url)).path for request in public_captured]
    assert paths.count("/markets-by-token/8501497") == 1
    assert paths.count(f"/clob-markets/{_CONDITION_ID}") == 1
    assert "/book" not in paths


def test_concurrent_limit_orders_coalesce_metadata_requests() -> None:
    public_captured: list[httpx.Request] = []

    async def run() -> None:
        client = await _make_client()
        try:
            _install_clob(client, _routed_handler(public_captured, _public_routes()))
            await asyncio.gather(
                *(
                    client.create_limit_order(
                        token_id="8501497", price="0.5", size="10", side="BUY"
                    )
                    for _ in range(3)
                )
            )
        finally:
            await client.close()

    asyncio.run(run())
    paths = [urlparse(str(request.url)).path for request in public_captured]
    assert paths.count("/markets-by-token/8501497") == 1
    assert paths.count(f"/clob-markets/{_CONDITION_ID}") == 1


def test_client_close_cancels_unobserved_metadata_load() -> None:
    request_started = asyncio.Event()
    request_cancelled = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        request_started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            request_cancelled.set()
            raise
        raise AssertionError("metadata request unexpectedly completed")

    async def run() -> None:
        client = await _make_client()
        _install_clob(client, httpx.MockTransport(handler))
        order = asyncio.create_task(
            client.create_limit_order(token_id="8501497", price="0.5", size="10", side="BUY")
        )
        await request_started.wait()
        order.cancel()
        with pytest.raises(asyncio.CancelledError):
            await order
        await client.close()
        assert request_cancelled.is_set()

    asyncio.run(run())


def test_sibling_token_reuses_warmed_condition_and_market() -> None:
    public_captured: list[httpx.Request] = []

    async def run() -> None:
        client = await _make_client()
        try:
            _install_clob(client, _routed_handler(public_captured, _public_routes()))
            await client.create_limit_order(token_id="8501497", price="0.5", size="10", side="BUY")
            await client.create_limit_order(token_id="8501498", price="0.5", size="10", side="SELL")
        finally:
            await client.close()

    asyncio.run(run())
    paths = [urlparse(str(request.url)).path for request in public_captured]
    assert paths == ["/markets-by-token/8501497", f"/clob-markets/{_CONDITION_ID}"]


def test_market_metadata_expires_without_expiring_token_condition() -> None:
    public_captured: list[httpx.Request] = []
    now = [0.0]

    async def run() -> None:
        client = await _make_client()
        client._ctx = dataclasses.replace(
            client._ctx,
            order_metadata=AsyncOrderMetadataCache(clock=lambda: now[0]),
        )
        try:
            _install_clob(client, _routed_handler(public_captured, _public_routes()))
            await client.create_limit_order(token_id="8501497", price="0.5", size="10", side="BUY")
            now[0] = 599
            await client.create_limit_order(token_id="8501497", price="0.5", size="10", side="BUY")
            now[0] = 600
            await client.create_limit_order(token_id="8501497", price="0.5", size="10", side="BUY")
        finally:
            await client.close()

    asyncio.run(run())
    paths = [urlparse(str(request.url)).path for request in public_captured]
    assert paths.count("/markets-by-token/8501497") == 1
    assert paths.count(f"/clob-markets/{_CONDITION_ID}") == 2


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

    async def run() -> None:
        client = await _make_client()
        try:
            _install_clob(client, httpx.MockTransport(handler))
            with pytest.raises(RequestRejectedError, match="try again"):
                await client.create_limit_order(
                    token_id="8501497", price="0.5", size="10", side="BUY"
                )
            await client.create_limit_order(token_id="8501497", price="0.5", size="10", side="BUY")
        finally:
            await client.close()

    asyncio.run(run())
    paths = [urlparse(str(request.url)).path for request in public_captured]
    assert paths.count("/markets-by-token/8501497") == 1
    assert paths.count(f"/clob-markets/{_CONDITION_ID}") == 2


def test_cached_tick_rejection_refreshes_market_once() -> None:
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
                    "fd": {"r": 0, "e": 0},
                    "mts": 0.01 if market_requests == 1 else 0.001,
                    "nr": False,
                    "t": [{"t": "8501497", "o": "Yes"}],
                },
                request=request,
            )
        return httpx.Response(404, json={"error": "not mocked"}, request=request)

    async def run() -> None:
        client = await _make_client()
        try:
            _install_clob(client, httpx.MockTransport(handler))
            await client.create_limit_order(token_id="8501497", price="0.5", size="10", side="BUY")
            signed = await client.create_limit_order(
                token_id="8501497", price="0.555", size="10", side="BUY"
            )
            assert signed.maker_amount == 5_550_000
        finally:
            await client.close()

    asyncio.run(run())
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

    async def run() -> None:
        client = await _make_client()
        try:
            _install_clob(client, httpx.MockTransport(handler))
            first = await client.create_market_order(
                token_id="8501497",
                side="BUY",
                amount="10",
                max_spend="10",
                max_price="0.5",
            )
            second = await client.create_market_order(
                token_id="8501497",
                side="BUY",
                amount="10",
                max_spend="10",
                max_price="0.555",
            )
            assert first.maker_amount == 10_000_000
            assert second.maker_amount < first.maker_amount
        finally:
            await client.close()

    asyncio.run(run())
    paths = [urlparse(str(request.url)).path for request in public_captured]
    assert paths.count("/markets-by-token/8501497") == 1
    assert paths.count(f"/clob-markets/{_CONDITION_ID}") == 2


def test_market_without_requested_token_evicts_mapping_and_market() -> None:
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
            token_id = "8501498" if market_requests == 1 else "8501497"
            return httpx.Response(
                200,
                json={
                    "fd": {"r": 0, "e": 0},
                    "mts": 0.01,
                    "nr": False,
                    "t": [{"t": token_id, "o": "Yes"}],
                },
                request=request,
            )
        return httpx.Response(404, json={"error": "not mocked"}, request=request)

    async def run() -> None:
        client = await _make_client()
        try:
            _install_clob(client, httpx.MockTransport(handler))
            with pytest.raises(UnexpectedResponseError, match="does not include asset"):
                await client.create_limit_order(
                    token_id="8501497", price="0.5", size="10", side="BUY"
                )
            await client.create_limit_order(token_id="8501497", price="0.5", size="10", side="BUY")
        finally:
            await client.close()

    asyncio.run(run())
    paths = [urlparse(str(request.url)).path for request in public_captured]
    assert paths.count("/markets-by-token/8501497") == 2
    assert paths.count(f"/clob-markets/{_CONDITION_ID}") == 2


def test_create_limit_order_does_not_preflight_allowance() -> None:
    secure_captured: list[httpx.Request] = []

    async def run() -> None:
        client = await _make_client()
        try:
            _install_clob(client, _routed_handler([], _public_routes()))
            _install_secure_clob(
                client, _routed_handler(secure_captured, _secure_routes(has_allowance=False))
            )
            await client.create_limit_order(token_id="8501497", price="0.5", size="10", side="BUY")
        finally:
            await client.close()

    asyncio.run(run())
    paths = [urlparse(str(r.url)).path for r in secure_captured]
    assert "/balance-allowance" not in paths
    assert "/balance-allowance/update" not in paths


def test_place_limit_order_posts_after_signing() -> None:
    secure_captured: list[httpx.Request] = []

    async def run() -> None:
        client = await _make_client()
        try:
            _install_clob(client, _routed_handler([], _public_routes()))
            _install_secure_clob(client, _routed_handler(secure_captured, _secure_routes()))
            response = await client.place_limit_order(
                token_id="8501497", price="0.5", size="10", side="BUY"
            )
            assert isinstance(response, AcceptedOrder)
            assert response.order_id == "ord-1"
        finally:
            await client.close()

    asyncio.run(run())
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

    async def run() -> None:
        client = await _make_client()
        try:
            _install_clob(client, _routed_handler([], public_routes))
            _install_secure_clob(client, _routed_handler(secure_captured, _secure_routes()))
            response = await client.place_market_order(
                token_id="8501497", side="BUY", amount=Decimal(2)
            )
            assert isinstance(response, AcceptedOrder)
        finally:
            await client.close()

    asyncio.run(run())


def test_post_order_validation_rejects_post_only_on_market_order() -> None:
    async def run() -> None:
        client = await _make_client()
        try:
            _install_clob(client, _routed_handler([], _public_routes()))
            _install_secure_clob(client, _routed_handler([], _secure_routes()))
            signed = await client.create_limit_order(
                token_id="8501497", price="0.5", size="10", side="BUY"
            )
            # Mutate to a FAK-with-post-only to confirm post-time validation
            mutated = dataclasses.replace(signed, order_type="FAK", post_only=True)
            await client.post_order(mutated)
        finally:
            await client.close()

    with pytest.raises(UserInputError, match="post-only"):
        asyncio.run(run())


def test_cancel_order_targets_order_path_with_capital_order_id_key() -> None:
    captured: list[httpx.Request] = []

    async def run() -> None:
        client = await _make_client()
        try:
            _install_secure_clob(client, _routed_handler(captured, _secure_routes()))
            await client.cancel_order(order_id="ord-1")
        finally:
            await client.close()

    asyncio.run(run())
    delete = captured[0]
    assert delete.method == "DELETE"
    assert urlparse(str(delete.url)).path == "/order"
    body = delete.content.decode()
    assert "orderID" in body


def test_cancel_all_targets_cancel_all_path() -> None:
    captured: list[httpx.Request] = []

    async def run() -> None:
        client = await _make_client()
        try:
            _install_secure_clob(client, _routed_handler(captured, _secure_routes()))
            response = await client.cancel_all()
            assert response.canceled == ("ord-1", "ord-2")
        finally:
            await client.close()

    asyncio.run(run())
    assert urlparse(str(captured[0].url)).path == "/cancel-all"


def test_cancel_market_orders_sends_filters_in_body() -> None:
    captured: list[httpx.Request] = []

    async def run() -> None:
        client = await _make_client()
        try:
            _install_secure_clob(client, _routed_handler(captured, _secure_routes()))
            await client.cancel_market_orders(market="0xMARKET", token_id="8501497")
        finally:
            await client.close()

    asyncio.run(run())
    request = captured[0]
    assert urlparse(str(request.url)).path == "/cancel-market-orders"
    body = request.content.decode()
    assert "0xMARKET" in body
    assert "asset_id" in body


def test_cancel_market_orders_requires_condition_or_asset() -> None:
    async def run() -> None:
        client = await _make_client()
        try:
            await client.cancel_market_orders()
        finally:
            await client.close()

    with pytest.raises(UserInputError, match="condition_id or asset_id"):
        asyncio.run(run())
