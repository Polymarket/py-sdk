# pyright: reportPrivateUsage=false
import asyncio
import dataclasses
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse

import httpx
import pytest

from polymarket import ApiKeyCreds, AsyncSecureClient
from polymarket._internal.actions.orders.market_data import (
    fetch_market_info,
    fetch_neg_risk,
    fetch_platform_fee_info,
    fetch_tick_size,
    resolve_condition_by_token,
)
from polymarket.clients._transport import AsyncTransport
from polymarket.errors import UnexpectedResponseError, UserInputError
from polymarket.models.types import CtfConditionId, TokenId

PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
SIGNER_ADDRESS = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
FAKE_CREDS = ApiKeyCreds(key="test-key", passphrase="test-passphrase", secret="dGVzdA==")
_CONDITION_ID = "0x5c19f205507ce03ff5f3be08a8090a5969ea6870cc07b902a4ca2e61dfe48fdd"


def _capture(captured: list[httpx.Request], status: int, payload: Any) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(status, json=payload, request=request)

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


def test_fetch_tick_size_returns_decimal_for_valid_response() -> None:
    captured: list[httpx.Request] = []

    async def run() -> Decimal:
        client = await _make_client()
        try:
            _install_public_clob(client, _capture(captured, 200, {"minimum_tick_size": 0.01}))
            return await fetch_tick_size(client._ctx, token_id="8501497")
        finally:
            await client.close()

    tick = asyncio.run(run())
    assert tick == Decimal("0.01")
    assert urlparse(str(captured[0].url)).path == "/tick-size"


def test_fetch_tick_size_accepts_new_supported_value() -> None:
    async def run() -> Decimal:
        client = await _make_client()
        try:
            _install_public_clob(client, _capture([], 200, {"minimum_tick_size": 0.005}))
            return await fetch_tick_size(client._ctx, token_id="8501497")
        finally:
            await client.close()

    assert asyncio.run(run()) == Decimal("0.005")


def test_fetch_tick_size_rejects_unsupported_value() -> None:
    async def run() -> Decimal:
        client = await _make_client()
        try:
            _install_public_clob(client, _capture([], 200, {"minimum_tick_size": 0.0005}))
            return await fetch_tick_size(client._ctx, token_id="8501497")
        finally:
            await client.close()

    with pytest.raises(UnexpectedResponseError, match="Unsupported tick size"):
        asyncio.run(run())


def test_fetch_neg_risk_returns_bool() -> None:
    async def run() -> bool:
        client = await _make_client()
        try:
            _install_public_clob(client, _capture([], 200, {"neg_risk": True}))
            return await fetch_neg_risk(client._ctx, token_id="8501497")
        finally:
            await client.close()

    assert asyncio.run(run()) is True


def test_fetch_neg_risk_rejects_non_bool() -> None:
    async def run() -> bool:
        client = await _make_client()
        try:
            _install_public_clob(client, _capture([], 200, {"neg_risk": "true"}))
            return await fetch_neg_risk(client._ctx, token_id="8501497")
        finally:
            await client.close()

    with pytest.raises(UnexpectedResponseError, match="neg_risk"):
        asyncio.run(run())


def test_resolve_condition_by_token_returns_condition_id() -> None:
    captured: list[httpx.Request] = []

    async def run() -> str:
        client = await _make_client()
        try:
            _install_public_clob(client, _capture(captured, 200, {"condition_id": _CONDITION_ID}))
            return await resolve_condition_by_token(client._ctx, token_id=TokenId("8501497"))
        finally:
            await client.close()

    assert asyncio.run(run()) == _CONDITION_ID
    assert urlparse(str(captured[0].url)).path == "/markets-by-token/8501497"


def test_resolve_condition_by_token_rejects_malformed_condition_id() -> None:
    async def run() -> str:
        client = await _make_client()
        try:
            _install_public_clob(client, _capture([], 200, {"condition_id": "0x1234"}))
            return await resolve_condition_by_token(client._ctx, token_id=TokenId("8501497"))
        finally:
            await client.close()

    with pytest.raises(UnexpectedResponseError, match="condition_id"):
        asyncio.run(run())


def test_fetch_platform_fee_info_defaults_to_zero_when_field_missing() -> None:
    async def run() -> tuple[Decimal, Decimal]:
        client = await _make_client()
        try:
            _install_public_clob(client, _capture([], 200, {"t": []}))
            info = await fetch_platform_fee_info(
                client._ctx, condition_id=CtfConditionId(_CONDITION_ID)
            )
            return info.rate, info.exponent
        finally:
            await client.close()

    rate, exponent = asyncio.run(run())
    assert rate == Decimal(0)
    assert exponent == Decimal(0)


def test_fetch_platform_fee_info_rejects_malformed_condition_id_before_request() -> None:
    captured: list[httpx.Request] = []

    async def run() -> None:
        client = await _make_client()
        try:
            _install_public_clob(client, _capture(captured, 200, {"t": []}))
            await fetch_platform_fee_info(client._ctx, condition_id=CtfConditionId("0x1234"))
        finally:
            await client.close()

    with pytest.raises(UserInputError, match="31-byte or 32-byte hex string"):
        asyncio.run(run())
    assert captured == []


def test_fetch_platform_fee_info_parses_rate_and_exponent() -> None:
    async def run() -> tuple[Decimal, Decimal]:
        client = await _make_client()
        try:
            _install_public_clob(client, _capture([], 200, {"fd": {"r": 0.0005, "e": 1}, "t": []}))
            info = await fetch_platform_fee_info(
                client._ctx, condition_id=CtfConditionId(_CONDITION_ID)
            )
            return info.rate, info.exponent
        finally:
            await client.close()

    rate, exponent = asyncio.run(run())
    assert rate == Decimal("0.0005")
    assert exponent == Decimal(1)


def test_fetch_market_info_parses_order_metadata_and_tokens() -> None:
    async def run() -> tuple[Decimal, bool, Decimal, frozenset[TokenId]]:
        client = await _make_client()
        try:
            _install_public_clob(
                client,
                _capture(
                    [],
                    200,
                    {
                        "fd": {"r": 0.0005, "e": 1},
                        "mts": 0.001,
                        "nr": True,
                        "t": [
                            {"t": "8501497", "o": "Yes"},
                            {"t": "8501498", "o": "No"},
                        ],
                    },
                ),
            )
            info = await fetch_market_info(client._ctx, condition_id=CtfConditionId(_CONDITION_ID))
            return info.fee_info.rate, info.neg_risk, info.tick_size, info.token_ids
        finally:
            await client.close()

    rate, neg_risk, tick_size, token_ids = asyncio.run(run())
    assert rate == Decimal("0.0005")
    assert neg_risk is True
    assert tick_size == Decimal("0.001")
    assert token_ids == frozenset((TokenId("8501497"), TokenId("8501498")))


def test_fetch_market_info_names_mts_in_tick_size_errors() -> None:
    async def run() -> None:
        client = await _make_client()
        try:
            _install_public_clob(
                client,
                _capture(
                    [],
                    200,
                    {
                        "mts": "invalid",
                        "nr": False,
                        "t": [{"t": "8501497", "o": "Yes"}],
                    },
                ),
            )
            await fetch_market_info(client._ctx, condition_id=CtfConditionId(_CONDITION_ID))
        finally:
            await client.close()

    with pytest.raises(UnexpectedResponseError, match="clob-markets 'mts'"):
        asyncio.run(run())
