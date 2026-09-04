# pyright: reportPrivateUsage=false
import asyncio
import dataclasses
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from polymarket import ApiKeyCreds, AsyncSecureClient
from polymarket._internal.actions.orders.allowance import fetch_current_order_allowance
from polymarket.clients._transport import AsyncTransport
from polymarket.models.types import TokenId
from polymarket.types import EvmAddress

PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
SIGNER_ADDRESS = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
FAKE_CREDS = ApiKeyCreds(key="test-key", passphrase="test-passphrase", secret="dGVzdA==")
EXCHANGE = EvmAddress("0xE111180000d2663C0091e4f400237545B87B996B")
_CTF_ASSET_ID = str((1 << 40) + 8_501_497)
_V2_POSITION_ID = str(int("0x01" + "00" * 30 + "00", 16))


def _install_secure_clob(
    client: AsyncSecureClient,
    payload: dict[str, Any],
    *,
    captured: list[httpx.Request] | None = None,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured.append(request)
        return httpx.Response(200, json=payload, request=request)

    transport = AsyncTransport(
        base_url="https://clob.test",
        client=httpx.AsyncClient(
            base_url="https://clob.test", transport=httpx.MockTransport(handler)
        ),
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


def test_fetch_current_order_allowance_returns_buy_spender_balance() -> None:
    async def run() -> int:
        client = await _make_client()
        try:
            _install_secure_clob(
                client,
                {"balance": "0", "allowances": {EXCHANGE: "5000000"}},
            )
            return await fetch_current_order_allowance(
                client._ctx,
                side="BUY",
                asset_id=TokenId("8501497"),
                spender=EXCHANGE,
            )
        finally:
            await client.close()

    assert asyncio.run(run()) == 5_000_000


def test_fetch_current_order_allowance_returns_sell_spender_balance() -> None:
    captured: list[httpx.Request] = []

    async def run() -> int:
        client = await _make_client()
        try:
            _install_secure_clob(
                client,
                {"balance": "0", "allowances": {EXCHANGE: "777"}},
                captured=captured,
            )
            return await fetch_current_order_allowance(
                client._ctx,
                side="SELL",
                asset_id=TokenId(_CTF_ASSET_ID),
                spender=EXCHANGE,
            )
        finally:
            await client.close()

    assert asyncio.run(run()) == 777
    qs = parse_qs(urlparse(str(captured[0].url)).query)
    assert qs["asset_type"] == ["CONDITIONAL"]
    assert qs["token_id"] == [_CTF_ASSET_ID]


def test_fetch_current_order_allowance_routes_v2_sell_to_conditional_v2() -> None:
    captured: list[httpx.Request] = []

    async def run() -> int:
        client = await _make_client()
        try:
            _install_secure_clob(
                client,
                {"balance": "0", "allowances": {EXCHANGE: "888"}},
                captured=captured,
            )
            return await fetch_current_order_allowance(
                client._ctx,
                side="SELL",
                asset_id=TokenId(_V2_POSITION_ID),
                spender=EXCHANGE,
            )
        finally:
            await client.close()

    assert asyncio.run(run()) == 888
    qs = parse_qs(urlparse(str(captured[0].url)).query)
    assert qs["asset_type"] == ["CONDITIONAL-V2"]
    assert qs["token_id"] == [_V2_POSITION_ID]


def test_fetch_current_order_allowance_returns_zero_when_spender_absent() -> None:
    async def run() -> int:
        client = await _make_client()
        try:
            _install_secure_clob(client, {"balance": "0", "allowances": {}})
            return await fetch_current_order_allowance(
                client._ctx,
                side="BUY",
                asset_id=TokenId("8501497"),
                spender=EXCHANGE,
            )
        finally:
            await client.close()

    assert asyncio.run(run()) == 0


def test_fetch_current_order_allowance_spender_lookup_is_case_insensitive() -> None:
    async def run() -> int:
        client = await _make_client()
        try:
            _install_secure_clob(
                client,
                {"balance": "0", "allowances": {EXCHANGE.lower(): "42"}},
            )
            return await fetch_current_order_allowance(
                client._ctx,
                side="BUY",
                asset_id=TokenId("8501497"),
                spender=EXCHANGE,
            )
        finally:
            await client.close()

    assert asyncio.run(run()) == 42
