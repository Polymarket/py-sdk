import asyncio
import contextlib
from decimal import Decimal

import pytest

from polymarket import (
    AcceptedOrder,
    AsyncPublicClient,
    AsyncSecureClient,
    Market,
    SecureClient,
)
from polymarket.errors import InsufficientLiquidityError, UserInputError

pytestmark = pytest.mark.anyio
UNKNOWN_BUILDER_CODE = "0xabcdefabcdefabcdefabcdefabcdefabcdefabcdefabcdefabcdefabcdefabcd"


def _minimum_order_size(market: Market) -> Decimal:
    size = market.trading.minimum_order_size
    assert size is not None
    return size


def _minimum_tick_size(market: Market) -> Decimal:
    tick_size = market.trading.minimum_tick_size
    assert tick_size is not None
    return tick_size


def _limit_buy_price(market: Market) -> Decimal:
    return _minimum_tick_size(market)


async def _wait_for_order_visible(
    client: AsyncSecureClient,
    *,
    token_id: str,
    order_id: str,
    attempts: int = 16,
    delay_s: float = 0.5,
) -> bool:
    for _ in range(attempts):
        page = await client.list_open_orders(token_id=token_id).first_page()
        if any(order.id == order_id for order in page.items):
            return True
        await asyncio.sleep(delay_s)
    return False


async def _wait_for_order_not_visible(
    client: AsyncSecureClient,
    *,
    token_id: str,
    order_id: str,
    attempts: int = 8,
    delay_s: float = 0.25,
) -> bool:
    for _ in range(attempts):
        page = await client.list_open_orders(token_id=token_id).first_page()
        if all(order.id != order_id for order in page.items):
            return True
        await asyncio.sleep(delay_s)
    return False


async def _wait_for_open_orders_empty(
    client: AsyncSecureClient,
    *,
    attempts: int = 8,
    delay_s: float = 0.25,
) -> bool:
    for _ in range(attempts):
        page = await client.list_open_orders().first_page()
        if not page.items:
            return True
        await asyncio.sleep(delay_s)
    return False


def _yes_token_id(market: Market) -> str:
    token_id = market.outcomes.yes.token_id
    assert token_id is not None
    return token_id


def _market_condition_id(market: Market) -> str:
    condition_id = market.condition_id
    assert condition_id is not None
    return condition_id


@pytest.mark.integration
async def test_estimate_market_price_for_buy_returns_decimal_in_unit_range(
    public_client: AsyncPublicClient,
    tradable_market: Market,
) -> None:
    amount = tradable_market.trading.minimum_order_size
    assert amount is not None
    price = await public_client.estimate_market_price(
        token_id=_yes_token_id(tradable_market),
        side="BUY",
        amount=amount,
    )

    assert isinstance(price, Decimal)
    assert Decimal(0) < price < Decimal(1)


@pytest.mark.integration
async def test_estimate_market_price_fok_raises_on_insufficient_liquidity(
    public_client: AsyncPublicClient,
    tradable_market: Market,
) -> None:
    with pytest.raises(InsufficientLiquidityError):
        await public_client.estimate_market_price(
            token_id=_yes_token_id(tradable_market),
            side="BUY",
            amount=Decimal("1000000000"),
            order_type="FOK",
        )


@pytest.mark.integration
async def test_create_market_order_reports_unknown_builder_code_as_user_input(
    deposit_wallet_client: AsyncSecureClient,
    tradable_market: Market,
) -> None:
    amount = _minimum_order_size(tradable_market)

    with pytest.raises(UserInputError, match="Unknown builder code"):
        await deposit_wallet_client.create_market_order(
            token_id=_yes_token_id(tradable_market),
            side="BUY",
            amount=amount,
            max_spend=amount,
            builder_code=UNKNOWN_BUILDER_CODE,
        )


# Metered tests below place/cancel live orders or execute FAK market orders.
@pytest.mark.integration
@pytest.mark.metered
async def test_place_limit_order_buy_creates_visible_open_order_and_cancels_cleanly(
    deposit_wallet_client: AsyncSecureClient,
    tradable_market: Market,
) -> None:
    token_id = _yes_token_id(tradable_market)
    price = _limit_buy_price(tradable_market)
    size = _minimum_order_size(tradable_market)
    placed_id: str | None = None
    try:
        placed = await deposit_wallet_client.place_limit_order(
            token_id=token_id,
            price=price,
            size=size,
            side="BUY",
        )
        assert isinstance(placed, AcceptedOrder)
        placed_id = placed.order_id

        assert await _wait_for_order_visible(
            deposit_wallet_client, token_id=token_id, order_id=placed_id
        ), f"order {placed_id} never appeared in list_open_orders"

        canceled_id = placed_id
        response = await deposit_wallet_client.cancel_order(order_id=placed_id)
        assert placed_id in response.canceled
        placed_id = None

        assert await _wait_for_order_not_visible(
            deposit_wallet_client, token_id=token_id, order_id=canceled_id
        ), f"cancel_order did not clear {canceled_id}"
    finally:
        if placed_id is not None:
            with contextlib.suppress(Exception):
                await deposit_wallet_client.cancel_order(order_id=placed_id)


@pytest.mark.integration
@pytest.mark.metered
async def test_place_limit_order_post_only_lands_on_book(
    deposit_wallet_client: AsyncSecureClient,
    tradable_market: Market,
) -> None:
    token_id = _yes_token_id(tradable_market)
    price = _limit_buy_price(tradable_market)
    size = _minimum_order_size(tradable_market)
    placed_id: str | None = None
    try:
        placed = await deposit_wallet_client.place_limit_order(
            token_id=token_id,
            price=price,
            size=size,
            side="BUY",
            post_only=True,
        )
        assert isinstance(placed, AcceptedOrder)
        placed_id = placed.order_id

        assert await _wait_for_order_visible(
            deposit_wallet_client, token_id=token_id, order_id=placed_id
        )
    finally:
        if placed_id is not None:
            with contextlib.suppress(Exception):
                await deposit_wallet_client.cancel_order(order_id=placed_id)


@pytest.mark.integration
@pytest.mark.metered
async def test_create_limit_order_post_only_sets_prepared_order_flag(
    deposit_wallet_client: AsyncSecureClient,
    tradable_market: Market,
) -> None:
    token_id = _yes_token_id(tradable_market)
    price = _limit_buy_price(tradable_market)
    size = _minimum_order_size(tradable_market)
    signed = await deposit_wallet_client.create_limit_order(
        token_id=token_id,
        price=price,
        size=size,
        side="BUY",
        post_only=True,
    )

    assert signed.post_only is True


@pytest.mark.integration
@pytest.mark.metered
async def test_create_then_post_split_workflow_matches_place_helper(
    deposit_wallet_client: AsyncSecureClient,
    tradable_market: Market,
) -> None:
    token_id = _yes_token_id(tradable_market)
    price = _limit_buy_price(tradable_market)
    size = _minimum_order_size(tradable_market)
    placed_id: str | None = None
    try:
        signed = await deposit_wallet_client.create_limit_order(
            token_id=token_id, price=price, size=size, side="BUY"
        )
        assert signed.signature.startswith("0x")
        response = await deposit_wallet_client.post_order(signed)
        assert isinstance(response, AcceptedOrder)
        placed_id = response.order_id

        assert await _wait_for_order_visible(
            deposit_wallet_client, token_id=token_id, order_id=placed_id
        )
    finally:
        if placed_id is not None:
            with contextlib.suppress(Exception):
                await deposit_wallet_client.cancel_order(order_id=placed_id)


@pytest.mark.integration
@pytest.mark.metered
async def test_place_market_order_closes_inventory_or_buys_minimum_size(
    deposit_wallet_client: AsyncSecureClient,
    tradable_market: Market,
) -> None:
    token_id = _yes_token_id(tradable_market)
    amount = _minimum_order_size(tradable_market)

    response = await deposit_wallet_client.place_market_order(
        token_id=token_id,
        side="BUY",
        amount=amount,
        order_type="FAK",
    )
    assert isinstance(response, AcceptedOrder)
    assert response.status in ("live", "matched", "delayed")
    if response.taking_amount > 0:
        with contextlib.suppress(Exception):
            await deposit_wallet_client.place_market_order(
                token_id=token_id,
                side="SELL",
                shares=response.taking_amount,
                order_type="FAK",
            )

    # Follow the matched order to settlement: hashes must surface regardless
    # of whether trades settle synchronously (hashes on the order response)
    # or asynchronously (trade ids on the response, hashes on the trades).
    if response.status == "matched":
        hashes = await deposit_wallet_client.wait_for_order_settlement(response)
        assert len(hashes) > 0


@pytest.mark.integration
@pytest.mark.metered
def test_sync_secure_client_create_places_market_order(
    deposit_wallet_private_key: str,
    deposit_wallet_address: str,
    tradable_market: Market,
) -> None:
    # Live side effect: places a FAK market order, then best-effort sells any fill.
    token_id = _yes_token_id(tradable_market)
    amount = _minimum_order_size(tradable_market)

    with SecureClient.create(
        private_key=deposit_wallet_private_key,
        wallet=deposit_wallet_address,
    ) as client:
        response = client.place_market_order(
            token_id=token_id,
            side="BUY",
            amount=amount,
            order_type="FAK",
        )
        assert isinstance(response, AcceptedOrder)
        assert response.status in ("live", "matched", "delayed")

        if response.taking_amount > 0:
            with contextlib.suppress(Exception):
                client.place_market_order(
                    token_id=token_id,
                    side="SELL",
                    shares=response.taking_amount,
                    order_type="FAK",
                )

        # Follow the matched order to settlement (see the async variant note).
        if response.status == "matched":
            hashes = client.wait_for_order_settlement(response)
            assert len(hashes) > 0


@pytest.mark.integration
@pytest.mark.metered
async def test_post_orders_batch_places_multiple_resting_orders(
    deposit_wallet_client: AsyncSecureClient,
    tradable_market: Market,
) -> None:
    token_id = _yes_token_id(tradable_market)
    price = _limit_buy_price(tradable_market)
    size = _minimum_order_size(tradable_market)
    signed_orders = [
        await deposit_wallet_client.create_limit_order(
            token_id=token_id, price=price, size=size, side="BUY"
        )
        for _ in range(2)
    ]
    placed_ids: list[str] = []
    try:
        responses = await deposit_wallet_client.post_orders(signed_orders)
        assert len(responses) == 2
        for r in responses:
            assert isinstance(r, AcceptedOrder)
            placed_ids.append(r.order_id)
    finally:
        for order_id in placed_ids:
            with contextlib.suppress(Exception):
                await deposit_wallet_client.cancel_order(order_id=order_id)


@pytest.mark.integration
@pytest.mark.metered
async def test_cancel_orders_batch_removes_multiple_open_orders(
    deposit_wallet_client: AsyncSecureClient,
    tradable_market: Market,
) -> None:
    token_id = _yes_token_id(tradable_market)
    price = _limit_buy_price(tradable_market)
    size = _minimum_order_size(tradable_market)
    placed_ids: list[str] = []
    try:
        for _ in range(2):
            placed = await deposit_wallet_client.place_limit_order(
                token_id=token_id, price=price, size=size, side="BUY"
            )
            assert isinstance(placed, AcceptedOrder)
            placed_ids.append(placed.order_id)

        response = await deposit_wallet_client.cancel_orders(order_ids=placed_ids)
        for order_id in placed_ids:
            assert order_id in response.canceled
        placed_ids = []
    finally:
        for order_id in placed_ids:
            with contextlib.suppress(Exception):
                await deposit_wallet_client.cancel_order(order_id=order_id)


@pytest.mark.integration
@pytest.mark.metered
async def test_cancel_market_orders_filters_by_market_and_token_id(
    deposit_wallet_client: AsyncSecureClient,
    tradable_market: Market,
) -> None:
    token_id = _yes_token_id(tradable_market)
    market = _market_condition_id(tradable_market)
    price = _limit_buy_price(tradable_market)
    size = _minimum_order_size(tradable_market)
    placed_id: str | None = None
    try:
        placed = await deposit_wallet_client.place_limit_order(
            token_id=token_id, price=price, size=size, side="BUY"
        )
        assert isinstance(placed, AcceptedOrder)
        placed_id = placed.order_id

        response = await deposit_wallet_client.cancel_market_orders(
            market=market, token_id=token_id
        )
        assert placed_id in response.canceled
        placed_id = None
    finally:
        if placed_id is not None:
            with contextlib.suppress(Exception):
                await deposit_wallet_client.cancel_order(order_id=placed_id)


@pytest.mark.integration
@pytest.mark.metered
async def test_cancel_all_removes_all_open_orders(
    deposit_wallet_client: AsyncSecureClient,
    tradable_market: Market,
) -> None:
    token_id = _yes_token_id(tradable_market)
    price = _limit_buy_price(tradable_market)
    size = _minimum_order_size(tradable_market)
    existing = await deposit_wallet_client.list_open_orders().first_page()
    if existing.items:
        pytest.skip(
            "wallet has open orders not placed by this test; "
            "skipping cancel_all to avoid destructive cleanup of unrelated state"
        )

    placed_id: str | None = None
    try:
        placed = await deposit_wallet_client.place_limit_order(
            token_id=token_id, price=price, size=size, side="BUY"
        )
        assert isinstance(placed, AcceptedOrder)
        placed_id = placed.order_id

        response = await deposit_wallet_client.cancel_all()
        assert placed_id in response.canceled
        placed_id = None

        assert await _wait_for_open_orders_empty(deposit_wallet_client), (
            "cancel_all did not clear open orders within the polling window"
        )
    finally:
        if placed_id is not None:
            with contextlib.suppress(Exception):
                await deposit_wallet_client.cancel_order(order_id=placed_id)
