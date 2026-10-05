import asyncio
import os
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager

import pytest

from polymarket import (
    ApiKeyCreds,
    AsyncSecureClient,
    BalanceAllowance,
    ClobTrade,
    Notification,
    NotificationType,
    OpenOrder,
)


def _existing_credentials() -> ApiKeyCreds | None:
    key = os.environ.get("POLYMARKET_TEST_API_KEY")
    secret = os.environ.get("POLYMARKET_TEST_API_SECRET")
    passphrase = os.environ.get("POLYMARKET_TEST_API_PASSPHRASE")
    if key and secret and passphrase:
        return ApiKeyCreds(key=key, secret=secret, passphrase=passphrase)
    return None


@asynccontextmanager
async def _secure_client(
    require_env: Callable[[str], str],
) -> AsyncGenerator[AsyncSecureClient, None]:
    private_key = require_env("POLYMARKET_PRIVATE_KEY")
    wallet = require_env("POLYMARKET_DEPOSIT_WALLET")
    client = await AsyncSecureClient.create(
        private_key=private_key,
        wallet=wallet,
        credentials=_existing_credentials(),
    )
    try:
        yield client
    finally:
        await client.close()


@pytest.mark.integration
@pytest.mark.metered
def test_secure_client_classifies_wallet_type(
    require_env: Callable[[str], str],
) -> None:
    async def run() -> str:
        async with _secure_client(require_env) as client:
            return client.wallet_type

    wallet_type = asyncio.run(run())
    assert wallet_type in {"EOA", "POLY_PROXY", "GNOSIS_SAFE", "DEPOSIT_WALLET"}


@pytest.mark.integration
@pytest.mark.metered
def test_get_closed_only_mode_returns_bool(
    require_env: Callable[[str], str],
) -> None:
    async def run() -> bool:
        async with _secure_client(require_env) as client:
            return await client.get_closed_only_mode()

    result = asyncio.run(run())
    assert isinstance(result, bool)


@pytest.mark.integration
@pytest.mark.metered
def test_list_open_orders_returns_open_order_models(
    require_env: Callable[[str], str],
) -> None:
    async def run() -> tuple[OpenOrder, ...]:
        async with _secure_client(require_env) as client:
            paginator = client.list_open_orders()
            first = await paginator.first_page()
            return first.items

    items = asyncio.run(run())
    for item in items:
        assert isinstance(item, OpenOrder)


@pytest.mark.integration
@pytest.mark.metered
def test_list_account_trades_returns_clob_trade_models(
    require_env: Callable[[str], str],
) -> None:
    async def run() -> tuple[ClobTrade, ...]:
        async with _secure_client(require_env) as client:
            paginator = client.list_account_trades()
            first = await paginator.first_page()
            return first.items

    items = asyncio.run(run())
    for item in items:
        assert isinstance(item, ClobTrade)


@pytest.mark.integration
@pytest.mark.metered
def test_get_notifications_returns_notification_models(
    require_env: Callable[[str], str],
) -> None:
    async def run() -> tuple[Notification, ...]:
        async with _secure_client(require_env) as client:
            return await client.get_notifications()

    items = asyncio.run(run())
    for item in items:
        assert isinstance(item.type, NotificationType)


@pytest.mark.integration
@pytest.mark.metered
def test_get_balance_allowance_collateral_returns_base_units(
    require_env: Callable[[str], str],
) -> None:
    async def run() -> BalanceAllowance:
        async with _secure_client(require_env) as client:
            return await client.get_balance_allowance(asset_type="COLLATERAL")

    ba = asyncio.run(run())
    assert isinstance(ba, BalanceAllowance)
    assert ba.balance >= 0
    for spender, allowance in ba.allowances.items():
        assert isinstance(spender, str)
        assert allowance >= 0
