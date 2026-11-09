from __future__ import annotations

import asyncio
import contextlib
from decimal import Decimal

import pytest
from eth_account import Account

from polymarket import (
    AcceptedOrder,
    AsyncSecureClient,
    BuilderApiKey,
    Environment,
    Market,
    RelayerApiKey,
    SessionKeyKnownScope,
    UserInputError,
    WalletOpenOrder,
)
from polymarket.pagination import AsyncPaginator

pytestmark = pytest.mark.anyio


@pytest.mark.integration
@pytest.mark.metered
@pytest.mark.parametrize("api_key_fixture", ["relayer_api_key", "builder_api_key"])
async def test_session_key_wallet_orders_are_read_and_cancelled_by_owner(
    api_key_fixture: str,
    request: pytest.FixtureRequest,
    deposit_wallet_private_key: str,
    deposit_wallet_address: str,
    tradable_market: Market,
    integration_environment: Environment,
) -> None:
    # Live side effects: authorizes and revokes an ephemeral CLOB-scoped session
    # key, places two minimum-size post-only orders, and cancels every resting
    # order on the integration Deposit Wallet.
    api_key: BuilderApiKey | RelayerApiKey = request.getfixturevalue(api_key_fixture)
    token_id = tradable_market.outcomes.yes.token_id
    price = tradable_market.trading.minimum_tick_size
    size = tradable_market.trading.minimum_order_size
    assert token_id is not None
    assert price is not None
    assert size is not None
    asset_id = str(token_id)
    owner_address = Account.from_key(deposit_wallet_private_key).address
    session_account = Account.create()
    session_private_key = "0x" + session_account.key.hex().removeprefix("0x")

    owner = await AsyncSecureClient.create(
        private_key=deposit_wallet_private_key,
        wallet=deposit_wallet_address,
        api_key=api_key,
        environment=integration_environment,
    )
    session: AsyncSecureClient | None = None
    authorization_attempted = False
    revoked = False
    orders_may_remain = False
    try:
        authorization_attempted = True
        authorization = await owner.authorize_session_key(
            address=session_account.address,
            scopes=(SessionKeyKnownScope.CLOB,),
        )
        assert authorization.session_key.address.lower() == session_account.address.lower()
        assert authorization.session_key in await owner.fetch_session_keys()

        session = await AsyncSecureClient.create(
            private_key=session_private_key,
            wallet=deposit_wallet_address,
            environment=integration_environment,
        )

        orders_may_remain = True
        session_order_id = await _place_resting_order(session, asset_id, price, size)
        owner_order_id = await _place_resting_order(owner, asset_id, price, size)

        # Read: session signers see the whole wallet, and signer filters select
        # orders by the signer that placed them.
        await _wait_for_wallet_orders(
            session, asset_id=asset_id, order_ids={session_order_id, owner_order_id}
        )

        session_orders = await _collect(
            owner.list_wallet_open_orders(
                asset_id=asset_id, signer_addresses=[session_account.address]
            )
        )
        session_order = next(order for order in session_orders if order.id == session_order_id)
        assert session_order.asset_id == asset_id
        assert session_order.condition_id == tradable_market.condition_id
        assert session_order.maker_address.lower() == deposit_wallet_address.lower()
        assert all(
            order.signer_address.lower() == session_account.address.lower()
            for order in session_orders
        )

        owner_orders = await _collect(
            owner.list_wallet_open_orders(asset_id=asset_id, signer_addresses=[owner_address])
        )
        assert owner_order_id in {order.id for order in owner_orders}
        assert all(order.signer_address.lower() == owner_address.lower() for order in owner_orders)

        # Several signers in one filter exercise the multi-address wire format.
        both_signers = await _collect(
            owner.list_wallet_open_orders(
                asset_id=asset_id,
                signer_addresses=[session_account.address, owner_address],
            )
        )
        assert {session_order_id, owner_order_id} <= {order.id for order in both_signers}

        # Credential-scoped listing excludes the session signer's order.
        credential_scoped = [
            order async for order in owner.list_open_orders(asset_id=asset_id).iter_items()
        ]
        assert session_order_id not in {order.id for order in credential_scoped}

        # Cancel: only the owner cancels across the wallet.
        with pytest.raises(UserInputError, match="Deposit Wallet owner"):
            await session.cancel_wallet_orders(order_ids=[session_order_id])
        with pytest.raises(UserInputError, match="Deposit Wallet owner"):
            await session.cancel_all_wallet_orders()

        selected = await owner.cancel_wallet_orders(order_ids=[session_order_id])
        assert session_order_id in selected.canceled

        everything = await owner.cancel_all_wallet_orders()
        assert owner_order_id in everything.canceled
        orders_may_remain = False

        remaining = await _collect(owner.list_wallet_open_orders(asset_id=asset_id))
        assert {session_order_id, owner_order_id}.isdisjoint(order.id for order in remaining)

        await owner.revoke_session_key(address=session_account.address)
        revoked = True
        assert all(
            key.address.lower() != session_account.address.lower()
            for key in await owner.fetch_session_keys()
        )
    finally:
        if orders_may_remain:
            with contextlib.suppress(Exception):
                await owner.cancel_all_wallet_orders()
        if session is not None:
            await session.close()
        if authorization_attempted and not revoked:
            with contextlib.suppress(Exception):
                await owner.revoke_session_key(address=session_account.address)
        await owner.close()


async def _place_resting_order(
    client: AsyncSecureClient, asset_id: str, price: Decimal, size: Decimal
) -> str:
    placed = await client.place_limit_order(
        asset_id=asset_id, price=price, size=size, side="BUY", post_only=True
    )
    assert isinstance(placed, AcceptedOrder)
    assert placed.status == "live"
    return str(placed.order_id)


async def _collect(paginator: AsyncPaginator[WalletOpenOrder]) -> list[WalletOpenOrder]:
    return [order async for order in paginator.iter_items()]


async def _wait_for_wallet_orders(
    client: AsyncSecureClient, *, asset_id: str, order_ids: set[str]
) -> None:
    # Retry briefly in case the wallet listing lags order placement.
    for _ in range(20):
        orders = await _collect(client.list_wallet_open_orders(asset_id=asset_id))
        if order_ids <= {order.id for order in orders}:
            return
        await asyncio.sleep(1)
    raise AssertionError(f"wallet orders {sorted(order_ids)} did not appear")
