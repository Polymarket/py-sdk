"""Static CLOB typing examples checked by pyright."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from types import CoroutineType
from typing import Any, assert_type

from polymarket import AsyncPublicClient, AsyncSecureClient, PublicClient, SecureClient
from polymarket.models import ClobAssetId, OrderSide, PriceRequest


def _check_public_client_batch_price_typing(client: PublicClient) -> None:
    assert_type(client.get_midpoints(asset_ids=["1"]), dict[ClobAssetId, Decimal])
    assert_type(
        client.get_prices(requests=[PriceRequest("1", "BUY")]),
        dict[ClobAssetId, dict[OrderSide, Decimal]],
    )
    assert_type(client.get_spreads(asset_ids=["1"]), dict[ClobAssetId, Decimal])


def _check_secure_client_batch_price_typing(client: SecureClient) -> None:
    assert_type(client.get_midpoints(asset_ids=["1"]), dict[ClobAssetId, Decimal])
    assert_type(
        client.get_prices(requests=[PriceRequest("1", "BUY")]),
        dict[ClobAssetId, dict[OrderSide, Decimal]],
    )
    assert_type(client.get_spreads(asset_ids=["1"]), dict[ClobAssetId, Decimal])


async def _check_async_public_client_batch_price_typing(client: AsyncPublicClient) -> None:
    assert_type(await client.get_midpoints(asset_ids=["1"]), dict[ClobAssetId, Decimal])
    assert_type(
        await client.get_prices(requests=[PriceRequest("1", "BUY")]),
        dict[ClobAssetId, dict[OrderSide, Decimal]],
    )
    assert_type(await client.get_spreads(asset_ids=["1"]), dict[ClobAssetId, Decimal])


async def _check_async_secure_client_batch_price_typing(client: AsyncSecureClient) -> None:
    assert_type(await client.get_midpoints(asset_ids=["1"]), dict[ClobAssetId, Decimal])
    assert_type(
        await client.get_prices(requests=[PriceRequest("1", "BUY")]),
        dict[ClobAssetId, dict[OrderSide, Decimal]],
    )
    assert_type(await client.get_spreads(asset_ids=["1"]), dict[ClobAssetId, Decimal])


_public_client_typing_check: Callable[[PublicClient], None] = (
    _check_public_client_batch_price_typing
)
_secure_client_typing_check: Callable[[SecureClient], None] = (
    _check_secure_client_batch_price_typing
)
_async_public_client_typing_check: Callable[[AsyncPublicClient], CoroutineType[Any, Any, None]] = (
    _check_async_public_client_batch_price_typing
)
_async_secure_client_typing_check: Callable[[AsyncSecureClient], CoroutineType[Any, Any, None]] = (
    _check_async_secure_client_batch_price_typing
)
