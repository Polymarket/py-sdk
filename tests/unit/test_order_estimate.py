# pyright: reportPrivateUsage=false
import asyncio
import dataclasses
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse

import httpx
import pytest

from polymarket import ApiKeyCreds, AsyncSecureClient
from polymarket._internal.actions.orders.estimate import resolve_estimated_market_price
from polymarket.clients._transport import AsyncTransport
from polymarket.errors import InsufficientLiquidityError, UserInputError

PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
SIGNER_ADDRESS = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
FAKE_CREDS = ApiKeyCreds(key="test-key", passphrase="test-passphrase", secret="dGVzdA==")


def _book_payload(*, bids: list[dict[str, str]], asks: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "asset_id": "8501497",
        "market": "0xMARKET",
        "bids": bids,
        "asks": asks,
        "min_order_size": "1",
        "tick_size": "0.01",
        "neg_risk": False,
        "hash": "0xhash",
        "timestamp": "1700000000",
    }


def _install_public_clob(
    client: AsyncSecureClient, captured: list[httpx.Request], payload: dict[str, Any]
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=payload, request=request)

    transport = AsyncTransport(
        base_url="https://clob.test",
        client=httpx.AsyncClient(
            base_url="https://clob.test", transport=httpx.MockTransport(handler)
        ),
    )
    client._ctx = dataclasses.replace(client._ctx, clob=transport)


async def _make_client() -> AsyncSecureClient:
    return await AsyncSecureClient._create(
        private_key=PRIVATE_KEY,
        wallet=SIGNER_ADDRESS,
        credentials=FAKE_CREDS,
        validate_credentials=False,
    )


def test_resolve_market_price_buy_walks_asks_in_reverse() -> None:
    captured: list[httpx.Request] = []
    payload = _book_payload(
        bids=[{"price": "0.40", "size": "5"}],
        asks=[
            {"price": "0.55", "size": "10"},
            {"price": "0.52", "size": "20"},
            {"price": "0.50", "size": "30"},
        ],
    )

    async def run() -> Decimal:
        client = await _make_client()
        try:
            _install_public_clob(client, captured, payload)
            return await resolve_estimated_market_price(
                client._ctx,
                token_id="8501497",  # type: ignore[arg-type]
                side="BUY",
                notional=Decimal("5"),
                order_type="FOK",
            )
        finally:
            await client.close()

    price = asyncio.run(run())
    assert price == Decimal("0.50")
    assert urlparse(str(captured[0].url)).path == "/book"


def test_resolve_market_price_sell_walks_bids_in_reverse() -> None:
    payload = _book_payload(
        bids=[
            {"price": "0.45", "size": "10"},
            {"price": "0.48", "size": "20"},
            {"price": "0.50", "size": "30"},
        ],
        asks=[{"price": "0.55", "size": "5"}],
    )

    async def run() -> Decimal:
        client = await _make_client()
        try:
            _install_public_clob(client, [], payload)
            return await resolve_estimated_market_price(
                client._ctx,
                token_id="8501497",  # type: ignore[arg-type]
                side="SELL",
                notional=Decimal("15"),
                order_type="FOK",
            )
        finally:
            await client.close()

    assert asyncio.run(run()) == Decimal("0.50")


def test_resolve_market_price_fok_raises_when_book_too_thin() -> None:
    payload = _book_payload(
        bids=[],
        asks=[{"price": "0.50", "size": "1"}],
    )

    async def run() -> Decimal:
        client = await _make_client()
        try:
            _install_public_clob(client, [], payload)
            return await resolve_estimated_market_price(
                client._ctx,
                token_id="8501497",  # type: ignore[arg-type]
                side="BUY",
                notional=Decimal("100"),
                order_type="FOK",
            )
        finally:
            await client.close()

    with pytest.raises(InsufficientLiquidityError):
        asyncio.run(run())


def test_resolve_market_price_fak_falls_back_to_best_level_when_book_too_thin() -> None:
    payload = _book_payload(
        bids=[],
        asks=[
            {"price": "0.55", "size": "1"},
            {"price": "0.50", "size": "1"},
        ],
    )

    async def run() -> Decimal:
        client = await _make_client()
        try:
            _install_public_clob(client, [], payload)
            return await resolve_estimated_market_price(
                client._ctx,
                token_id="8501497",  # type: ignore[arg-type]
                side="BUY",
                notional=Decimal("100"),
                order_type="FAK",
            )
        finally:
            await client.close()

    assert asyncio.run(run()) == Decimal("0.55")


def test_resolve_market_price_raises_for_empty_book() -> None:
    payload = _book_payload(bids=[], asks=[])

    async def run() -> Decimal:
        client = await _make_client()
        try:
            _install_public_clob(client, [], payload)
            return await resolve_estimated_market_price(
                client._ctx,
                token_id="8501497",  # type: ignore[arg-type]
                side="BUY",
                notional=Decimal("1"),
                order_type="FOK",
            )
        finally:
            await client.close()

    with pytest.raises(InsufficientLiquidityError):
        asyncio.run(run())


def test_client_estimate_market_price_validates_input() -> None:
    async def run() -> Decimal:
        client = await _make_client()
        try:
            return await client.estimate_market_price(  # type: ignore[call-overload]
                token_id="8501497", side="BUY", amount=Decimal(1), shares=Decimal(1)
            )
        finally:
            await client.close()

    with pytest.raises(UserInputError, match="shares must not be set"):
        asyncio.run(run())


def test_public_client_exposes_estimate_market_price() -> None:
    from polymarket import AsyncPublicClient

    payload = _book_payload(
        bids=[{"price": "0.40", "size": "5"}],
        asks=[
            {"price": "0.55", "size": "10"},
            {"price": "0.50", "size": "30"},
        ],
    )

    routes = {"/book": payload}

    def handler(request: httpx.Request) -> httpx.Response:
        from urllib.parse import urlparse

        path = urlparse(str(request.url)).path
        if path in routes:
            return httpx.Response(200, json=routes[path], request=request)
        return httpx.Response(404, request=request)

    async def run() -> Decimal:
        client = AsyncPublicClient()
        client._ctx = dataclasses.replace(
            client._ctx,
            clob=AsyncTransport(
                base_url="https://clob.test",
                client=httpx.AsyncClient(
                    base_url="https://clob.test", transport=httpx.MockTransport(handler)
                ),
            ),
        )
        try:
            return await client.estimate_market_price(
                token_id="8501497", side="BUY", amount=Decimal("5")
            )
        finally:
            await client.close()

    price = asyncio.run(run())
    assert price == Decimal("0.50")


def test_client_estimate_market_price_rejects_unknown_side() -> None:
    async def run() -> Decimal:
        client = await _make_client()
        try:
            return await client.estimate_market_price(
                token_id="8501497",
                side="HOLD",  # type: ignore[arg-type]
                amount=Decimal(1),
            )
        finally:
            await client.close()

    with pytest.raises(UserInputError, match="side must be"):
        asyncio.run(run())
