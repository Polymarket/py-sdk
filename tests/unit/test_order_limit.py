# pyright: reportPrivateUsage=false
import asyncio
import dataclasses
import time
from decimal import Decimal
from typing import Any

import httpx
import pytest

from polymarket import ApiKeyCreds, AsyncSecureClient
from polymarket._internal.actions.orders.limit import (
    prepare_limit_order_draft,
    validate_limit_order_params,
)
from polymarket.clients._transport import AsyncTransport
from polymarket.environments import PRODUCTION
from polymarket.errors import UserInputError

PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
SIGNER_ADDRESS = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
FAKE_CREDS = ApiKeyCreds(key="test-key", passphrase="test-passphrase", secret="dGVzdA==")


def _multi_route_handler(routes: dict[str, dict[str, Any]]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        from urllib.parse import urlparse

        path = urlparse(str(request.url)).path
        if path in routes:
            return httpx.Response(200, json=routes[path], request=request)
        return httpx.Response(404, json={"error": "not mocked"}, request=request)

    return httpx.MockTransport(handler)


def _install_public_clob(client: AsyncSecureClient, handler: httpx.MockTransport) -> None:
    transport = AsyncTransport(
        base_url="https://clob.test",
        client=httpx.AsyncClient(base_url="https://clob.test", transport=handler),
    )
    client._ctx = dataclasses.replace(client._ctx, clob=transport)


async def _make_client() -> AsyncSecureClient:
    return await AsyncSecureClient._create(
        private_key=PRIVATE_KEY,
        wallet=SIGNER_ADDRESS,
        credentials=FAKE_CREDS,
        validate_credentials=False,
    )


def test_validate_limit_order_params_accepts_basic_inputs() -> None:
    params = validate_limit_order_params(token_id="8501497", price="0.5", size="10", side="BUY")
    assert params.token_id == "8501497"
    assert params.price == Decimal("0.5")
    assert params.size == Decimal(10)
    assert params.side == "BUY"
    assert params.post_only is False
    assert params.expiration is None


def test_validate_limit_order_params_rejects_zero_price() -> None:
    with pytest.raises(UserInputError, match="price must be a positive"):
        validate_limit_order_params(token_id="8501497", price="0", size="10", side="BUY")


def test_validate_limit_order_params_accepts_float_via_str_conversion() -> None:
    params = validate_limit_order_params(token_id="8501497", price=0.5, size=10.5, side="BUY")
    assert params.price == Decimal("0.5")
    assert params.size == Decimal("10.5")


def test_validate_limit_order_params_rejects_non_bool_post_only() -> None:
    with pytest.raises(UserInputError, match="post_only"):
        validate_limit_order_params(
            token_id="8501497",
            price="0.5",
            size="10",
            side="BUY",
            post_only="false",  # type: ignore[arg-type]
        )


def test_validate_limit_order_params_rejects_int_post_only() -> None:
    with pytest.raises(UserInputError, match="post_only"):
        validate_limit_order_params(
            token_id="8501497",
            price="0.5",
            size="10",
            side="BUY",
            post_only=1,  # type: ignore[arg-type]
        )


def test_validate_limit_order_params_rejects_negative_size() -> None:
    with pytest.raises(UserInputError, match="size must be a positive"):
        validate_limit_order_params(token_id="8501497", price="0.5", size="-1", side="BUY")


def test_validate_limit_order_params_rejects_unknown_side() -> None:
    with pytest.raises(UserInputError, match="side must be"):
        validate_limit_order_params(
            token_id="8501497",
            price="0.5",
            size="10",
            side="HOLD",  # type: ignore[arg-type]
        )


def test_validate_limit_order_params_rejects_float_expiration() -> None:
    with pytest.raises(UserInputError, match="non-negative integer"):
        validate_limit_order_params(
            token_id="8501497",
            price="0.5",
            size="10",
            side="BUY",
            expiration=int(time.time()) + 600.0,  # type: ignore[arg-type]
        )


def test_validate_limit_order_params_rejects_string_expiration() -> None:
    with pytest.raises(UserInputError, match="non-negative integer"):
        validate_limit_order_params(
            token_id="8501497",
            price="0.5",
            size="10",
            side="BUY",
            expiration="9999999999",  # type: ignore[arg-type]
        )


def test_validate_limit_order_params_rejects_bool_expiration() -> None:
    with pytest.raises(UserInputError, match="non-negative integer"):
        validate_limit_order_params(
            token_id="8501497",
            price="0.5",
            size="10",
            side="BUY",
            expiration=True,  # type: ignore[arg-type]
        )


def test_validate_limit_order_params_rejects_negative_expiration() -> None:
    with pytest.raises(UserInputError, match="non-negative integer"):
        validate_limit_order_params(
            token_id="8501497",
            price="0.5",
            size="10",
            side="BUY",
            expiration=-1,
        )


def test_validate_limit_order_params_rejects_near_expiration() -> None:
    with pytest.raises(UserInputError, match="180 seconds"):
        validate_limit_order_params(
            token_id="8501497",
            price="0.5",
            size="10",
            side="BUY",
            expiration=int(time.time()) + 10,
        )


def test_validate_limit_order_params_rejects_expiration_below_minimum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 1_700_000_000
    monkeypatch.setattr("polymarket._internal.actions.orders.limit.time.time", lambda: now)
    with pytest.raises(UserInputError, match="180 seconds"):
        validate_limit_order_params(
            token_id="8501497",
            price="0.5",
            size="10",
            side="BUY",
            expiration=now + 179,
        )


def test_validate_limit_order_params_accepts_minimum_expiration_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 1_700_000_000
    monkeypatch.setattr("polymarket._internal.actions.orders.limit.time.time", lambda: now)
    params = validate_limit_order_params(
        token_id="8501497",
        price="0.5",
        size="10",
        side="BUY",
        expiration=now + 180,
    )
    assert params.expiration == now + 180


def test_validate_limit_order_params_accepts_far_expiration() -> None:
    params = validate_limit_order_params(
        token_id="8501497",
        price="0.5",
        size="10",
        side="BUY",
        expiration=int(time.time()) + 600,
    )
    assert params.expiration is not None


def test_prepare_limit_order_draft_buy_computes_offered_requested() -> None:
    routes = {
        "/tick-size": {"minimum_tick_size": 0.01},
        "/neg-risk": {"neg_risk": False},
    }

    async def run() -> tuple[int, int, str, str]:
        client = await _make_client()
        try:
            _install_public_clob(client, _multi_route_handler(routes))
            params = validate_limit_order_params(
                token_id="8501497", price="0.5", size="10", side="BUY"
            )
            draft = await prepare_limit_order_draft(client._ctx, params)
            return (
                draft.offered_amount,
                draft.requested_amount,
                draft.order_type,
                draft.exchange_address,
            )
        finally:
            await client.close()

    offered, requested, order_type, exchange = asyncio.run(run())
    assert offered == 5_000_000  # 10 * 0.5 USDC base units
    assert requested == 10_000_000  # 10 shares base units
    assert order_type == "GTC"
    assert exchange == PRODUCTION.standard_exchange


def test_prepare_limit_order_draft_sell_swaps_amounts() -> None:
    routes = {
        "/tick-size": {"minimum_tick_size": 0.01},
        "/neg-risk": {"neg_risk": True},
    }

    async def run() -> tuple[int, int, str]:
        client = await _make_client()
        try:
            _install_public_clob(client, _multi_route_handler(routes))
            params = validate_limit_order_params(
                token_id="8501497", price="0.5", size="10", side="SELL"
            )
            draft = await prepare_limit_order_draft(client._ctx, params)
            return draft.offered_amount, draft.requested_amount, draft.exchange_address
        finally:
            await client.close()

    offered, requested, exchange = asyncio.run(run())
    assert offered == 10_000_000  # 10 shares
    assert requested == 5_000_000  # 5 USDC
    assert exchange == PRODUCTION.neg_risk_exchange


def test_prepare_limit_order_draft_sets_gtd_when_expiration_given() -> None:
    routes = {
        "/tick-size": {"minimum_tick_size": 0.01},
        "/neg-risk": {"neg_risk": False},
    }

    async def run() -> tuple[str, int]:
        client = await _make_client()
        try:
            _install_public_clob(client, _multi_route_handler(routes))
            params = validate_limit_order_params(
                token_id="8501497",
                price="0.5",
                size="10",
                side="BUY",
                expiration=int(time.time()) + 600,
            )
            draft = await prepare_limit_order_draft(client._ctx, params)
            return draft.order_type, draft.expiration
        finally:
            await client.close()

    order_type, expiration = asyncio.run(run())
    assert order_type == "GTD"
    assert expiration > int(time.time())


def test_prepare_limit_order_draft_rejects_off_tick_price() -> None:
    routes = {
        "/tick-size": {"minimum_tick_size": 0.01},
        "/neg-risk": {"neg_risk": False},
    }

    async def run() -> None:
        client = await _make_client()
        try:
            _install_public_clob(client, _multi_route_handler(routes))
            params = validate_limit_order_params(
                token_id="8501497", price="0.555", size="10", side="BUY"
            )
            await prepare_limit_order_draft(client._ctx, params)
        finally:
            await client.close()

    with pytest.raises(UserInputError, match="tick size"):
        asyncio.run(run())


def test_prepare_limit_order_draft_rejects_price_outside_unit_range() -> None:
    routes = {
        "/tick-size": {"minimum_tick_size": 0.01},
        "/neg-risk": {"neg_risk": False},
    }

    async def run() -> None:
        client = await _make_client()
        try:
            _install_public_clob(client, _multi_route_handler(routes))
            params = validate_limit_order_params(
                token_id="8501497", price="0.005", size="10", side="BUY"
            )
            await prepare_limit_order_draft(client._ctx, params)
        finally:
            await client.close()

    with pytest.raises(UserInputError, match="between"):
        asyncio.run(run())
