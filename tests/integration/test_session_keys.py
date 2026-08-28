from __future__ import annotations

import contextlib
import re

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
)

pytestmark = pytest.mark.anyio


@pytest.mark.integration
@pytest.mark.metered
async def test_session_key_authorizes_lists_trades_and_revokes(
    deposit_wallet_private_key: str,
    deposit_wallet_address: str,
    builder_api_key: BuilderApiKey,
    relayer_api_key: RelayerApiKey,
    tradable_market: Market,
    integration_environment: Environment,
) -> None:
    # Live side effects: authorizes an ephemeral session key with the default
    # scopes, places one post-only order, cancels it, and revokes the key.
    session_account = Account.create()
    session_private_key = "0x" + session_account.key.hex().removeprefix("0x")

    deposit_wallet_client = await AsyncSecureClient.create(
        private_key=deposit_wallet_private_key,
        wallet=deposit_wallet_address,
        api_key=builder_api_key,
        environment=integration_environment,
    )
    authorization_attempted = False
    revocation_accepted = False
    try:
        authorization_attempted = True
        authorization = await deposit_wallet_client.authorize_session_key(
            address=session_account.address,
        )

        assert authorization.transaction.transaction_id is not None
        assert re.fullmatch(r"0x[0-9a-fA-F]{64}", str(authorization.transaction.transaction_hash))
        assert authorization.session_key.address.lower() == session_account.address.lower()
        assert authorization.session_key.scopes == (SessionKeyKnownScope.ALL,)

        active_session_keys = await deposit_wallet_client.fetch_session_keys()
        assert authorization.session_key in active_session_keys

        session_client: AsyncSecureClient | None = None
        order_id: str | None = None
        try:
            session_client = await AsyncSecureClient.create(
                private_key=session_private_key,
                wallet=deposit_wallet_address,
                environment=deposit_wallet_client.environment,
                api_key=relayer_api_key,
            )
            with pytest.raises(
                UserInputError,
                match=r"^Combos is not supported with Session Keys$",
            ):
                await session_client.request_combo_quote(
                    leg_position_ids=("1", "2"),
                    direction="BUY",
                    amount=1,
                )

            token_id = tradable_market.outcomes.yes.token_id
            price = tradable_market.trading.minimum_tick_size
            size = tradable_market.trading.minimum_order_size
            assert token_id is not None
            assert price is not None
            assert size is not None

            placed = await session_client.place_limit_order(
                token_id=str(token_id),
                price=price,
                size=size,
                side="BUY",
                post_only=True,
            )
            assert isinstance(placed, AcceptedOrder)
            order_id = str(placed.order_id)
            assert placed.status == "live"

            cancellation = await session_client.cancel_order(order_id=order_id)
            assert order_id in cancellation.canceled
            order_id = None

            revocation_transaction = await deposit_wallet_client.revoke_session_key(
                address=session_account.address
            )
            revocation_accepted = True
            assert revocation_transaction.transaction_id is not None
            assert re.fullmatch(
                r"0x[0-9a-fA-F]{64}",
                str(revocation_transaction.transaction_hash),
            )

            remaining_session_keys = await deposit_wallet_client.fetch_session_keys()
            assert all(
                session_key.address.lower() != session_account.address.lower()
                for session_key in remaining_session_keys
            )
        finally:
            if order_id is not None and session_client is not None:
                with contextlib.suppress(Exception):
                    await session_client.cancel_order(order_id=order_id)
            if session_client is not None:
                await session_client.close()
    finally:
        if authorization_attempted and not revocation_accepted:
            with contextlib.suppress(Exception):
                await deposit_wallet_client.revoke_session_key(address=session_account.address)
        await deposit_wallet_client.close()
