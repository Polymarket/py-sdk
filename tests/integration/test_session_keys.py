from __future__ import annotations

import contextlib
import re
from datetime import UTC, datetime, timedelta

import pytest
from eth_account import Account

from polymarket import (
    AcceptedOrder,
    AsyncSecureClient,
    Market,
    RelayerApiKey,
    SessionKeyKnownScope,
    UserInputError,
)

pytestmark = pytest.mark.anyio


@pytest.mark.integration
@pytest.mark.metered
async def test_session_key_authorizes_places_limit_order_and_cancels(
    deposit_wallet_client: AsyncSecureClient,
    deposit_wallet_address: str,
    relayer_api_key: RelayerApiKey,
    tradable_market: Market,
) -> None:
    # Live side effects: authorizes an ephemeral CLOB session key, places one
    # post-only order, and cancels it. Revocation is not available yet, so the
    # grant remains active until this short expiry.
    session_account = Account.create()
    session_private_key = "0x" + session_account.key.hex().removeprefix("0x")
    requested_expiry = datetime.now(UTC) + timedelta(minutes=15)
    expected_expiry = requested_expiry.replace(microsecond=0)

    authorization = await deposit_wallet_client.authorize_session_key(
        address=session_account.address,
        scopes=(SessionKeyKnownScope.CLOB,),
        valid_until=requested_expiry,
    )

    assert authorization.operation_id
    assert authorization.transaction.transaction_id is not None
    assert re.fullmatch(r"0x[0-9a-fA-F]{64}", str(authorization.transaction.transaction_hash))
    assert authorization.session_key.address.lower() == session_account.address.lower()
    assert authorization.session_key.scopes == (SessionKeyKnownScope.CLOB,)
    assert authorization.session_key.valid_until == expected_expiry

    session_client = await AsyncSecureClient.create(
        private_key=session_private_key,
        wallet=deposit_wallet_address,
        environment=deposit_wallet_client.environment,
        api_key=relayer_api_key,
    )
    order_id: str | None = None
    try:
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
    finally:
        if order_id is not None:
            with contextlib.suppress(Exception):
                await session_client.cancel_order(order_id=order_id)
        await session_client.close()
