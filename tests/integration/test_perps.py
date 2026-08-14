# pyright: reportPrivateUsage=false
"""Live Perps integration tests.

Mirrors the TypeScript SDK Perps integration suite. All metered tests run
against production Perps with the Deposit Wallet configured in ``.env``.

Metered side effects:
- ``test_deposits_and_withdraws_the_same_perps_amount`` approves collateral,
  moves 10 USDC into Perps, and withdraws the same amount.
- Session tests create (and where noted revoke) delegated Perps credentials.
- Order tests place resting orders far from the mark price and cancel them.
- The auto-cancel test arms a 10-minute dead man's switch and disarms it.
"""

import asyncio
import contextlib
import math
from collections.abc import AsyncGenerator, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from polymarket import (
    AsyncPublicClient,
    AsyncSecureClient,
    BuilderApiKey,
    PerpsInstrument,
    PerpsTpSlTrigger,
    RequestRejectedError,
)
from polymarket._internal.environment import get_environment_config
from polymarket.errors import UnexpectedResponseError
from polymarket.perps import PerpsSession
from polymarket.streams import PerpsBookSpec

pytestmark = pytest.mark.anyio

DEFAULT_PERPS_CREDENTIAL_TTL = timedelta(days=7)
_MAX_PRICE_SIGNIFICANT_FIGURES = 5
_DEPOSIT_AMOUNT_BASE_UNITS = 10_000_000  # 10 USDC
_DEPOSIT_CONFIRM_TIMEOUT_S = 5 * 60.0


@pytest.fixture
async def relayer_enabled_deposit_wallet_client(
    require_env: Callable[[str], str],
) -> AsyncGenerator[AsyncSecureClient, None]:
    """Deposit Wallet client with relayer access for gasless transactions."""
    api_key = BuilderApiKey(
        key=require_env("POLYMARKET_BUILDER_API_KEY"),
        secret=require_env("POLYMARKET_BUILDER_SECRET"),
        passphrase=require_env("POLYMARKET_BUILDER_PASSPHRASE"),
    )
    client = await AsyncSecureClient.create(
        private_key=require_env("POLYMARKET_PRIVATE_KEY"),
        wallet=require_env("POLYMARKET_DEPOSIT_WALLET"),
        api_key=api_key,
    )
    try:
        yield client
    finally:
        await client.close()


def _format_perps_price(price: Decimal, price_decimals: int) -> str:
    """Round to five significant figures and trim to the instrument's decimals."""
    rounded = float(f"{float(price):.{_MAX_PRICE_SIGNIFICANT_FIGURES}g}")
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:.{price_decimals}f}".rstrip("0").rstrip(".")


def _minimal_order_quantity(instrument: PerpsInstrument, price: Decimal) -> str:
    scale = 10**instrument.quantity_decimals
    quantity = math.ceil(float(instrument.min_notional) / float(price) * scale) / scale
    return f"{quantity:.{instrument.quantity_decimals}f}"


async def _first_instrument(client: AsyncSecureClient) -> PerpsInstrument:
    instruments = await client.fetch_perps_instruments()
    assert instruments, "expected at least one Perps instrument"
    return instruments[0]


async def _wait_for_confirmed_deposit(session: PerpsSession, *, hash: str, amount: Decimal) -> None:
    async def poll() -> None:
        while True:
            page = await session.list_deposits(hash=hash).first_page()
            deposit = next((item for item in page.items if item.hash == hash), None)
            if deposit is not None and deposit.status == "confirmed":
                assert deposit.amount == amount
                return
            await asyncio.sleep(5.0)

    await asyncio.wait_for(poll(), timeout=_DEPOSIT_CONFIRM_TIMEOUT_S)


@pytest.mark.integration
async def test_public_perps_reads() -> None:
    async with AsyncPublicClient() as client:
        instruments = await client.fetch_perps_instruments()
        assert instruments
        instrument = instruments[0]
        ticker = await client.fetch_perps_ticker(instrument_id=instrument.id)
        assert ticker.mark_price > 0
        book = await client.fetch_perps_book(instrument_id=instrument.id, depth=10)
        assert book.instrument_id == instrument.id
        fees = await client.fetch_perps_fees()
        assert fees
        assert fees[0].tiers
        candles = await client.list_perps_candles(
            instrument_id=instrument.id, interval="1h"
        ).first_page()
        assert candles.items


@pytest.mark.integration
async def test_get_server_time() -> None:
    before = datetime.now(UTC) - timedelta(seconds=5)
    async with AsyncPublicClient() as client:
        server_time = await client.get_server_time()
    after = datetime.now(UTC) + timedelta(seconds=5)

    assert server_time.tzinfo is not None
    assert before <= server_time <= after


@pytest.mark.integration
async def test_perps_book_subscription_receives_an_event() -> None:
    async with AsyncPublicClient() as client:
        instruments = await client.fetch_perps_instruments()
        assert instruments
        handle = await client.subscribe(PerpsBookSpec(instrument_id=instruments[0].id))
        async with handle:
            event = await asyncio.wait_for(handle.__anext__(), timeout=30.0)
            assert event.topic == "perps.book"
            assert event.payload.instrument_id == instruments[0].id


@pytest.mark.integration
@pytest.mark.metered
async def test_deposits_and_withdraws_the_same_perps_amount(
    relayer_enabled_deposit_wallet_client: AsyncSecureClient,
) -> None:
    client = relayer_enabled_deposit_wallet_client
    approval = await client.approve_erc20(
        amount="max",
        spender_address=get_environment_config(client.environment).perps_deposit_contract,
        token_address=get_environment_config(client.environment).collateral_token,
    )
    await approval.wait()

    deposit = await client.deposit_to_perps(amount=_DEPOSIT_AMOUNT_BASE_UNITS)
    outcome = await deposit.wait()
    assert outcome is not None
    transaction_hash = outcome.transaction_hash
    assert transaction_hash is not None
    assert transaction_hash.startswith("0x")

    session = await client.open_perps_session(expires_in=timedelta(minutes=30))
    try:
        await _wait_for_confirmed_deposit(session, hash=transaction_hash, amount=Decimal(10))
        withdrawal_id = await client.withdraw_from_perps(amount=_DEPOSIT_AMOUNT_BASE_UNITS)
        assert isinstance(withdrawal_id, int)
    finally:
        await session.close()


@pytest.mark.integration
@pytest.mark.metered
async def test_creates_delegated_perps_credentials_with_the_default_expiry(
    deposit_wallet_client: AsyncSecureClient,
) -> None:
    started_at = datetime.now(tz=UTC)
    session = await deposit_wallet_client.open_perps_session()
    try:
        credentials = session.credentials
        assert credentials.proxy.startswith("0x") and len(credentials.proxy) == 42
        assert credentials.private_key.startswith("0x")
        assert len(credentials.private_key) == 66
        assert credentials.secret
        assert credentials.expires_at >= started_at + DEFAULT_PERPS_CREDENTIAL_TTL
        assert credentials.expires_at <= datetime.now(tz=UTC) + DEFAULT_PERPS_CREDENTIAL_TTL
    finally:
        await session.close()


@pytest.mark.integration
@pytest.mark.metered
async def test_places_and_cancels_one_perps_order(
    deposit_wallet_client: AsyncSecureClient,
) -> None:
    instrument = await _first_instrument(deposit_wallet_client)
    ticker = await deposit_wallet_client.fetch_perps_ticker(instrument_id=instrument.id)
    # Half the mark price so the order rests instead of filling.
    price = _format_perps_price(ticker.mark_price / 2, instrument.price_decimals)
    session = await deposit_wallet_client.open_perps_session()
    try:
        placement = await session.place_order(
            instrument_id=instrument.id,
            side="BUY",
            price=price,
            quantity=_minimal_order_quantity(instrument, Decimal(price)),
            time_in_force="gtc",
        )
        assert placement.order.instrument_id == instrument.id
        assert placement.order.side == "BUY"

        result = await session.cancel_order(order_id=placement.order.id)
        assert result.status == "ok"
    finally:
        await session.close()


@pytest.mark.integration
@pytest.mark.metered
async def test_places_and_cancels_all_perps_orders_for_one_instrument(
    deposit_wallet_client: AsyncSecureClient,
) -> None:
    instrument = await _first_instrument(deposit_wallet_client)
    ticker = await deposit_wallet_client.fetch_perps_ticker(instrument_id=instrument.id)
    # Places two resting orders and cancels all open orders for this instrument.
    price = _format_perps_price(ticker.mark_price / 2, instrument.price_decimals)
    quantity = _minimal_order_quantity(instrument, Decimal(price))
    order_ids: list[int] = []
    session = await deposit_wallet_client.open_perps_session()
    try:
        for _ in range(2):
            placement = await session.place_order(
                instrument_id=instrument.id,
                side="BUY",
                price=price,
                quantity=quantity,
                time_in_force="gtc",
            )
            order_ids.append(placement.order.id)

        await session.cancel_all_orders(instrument_id=instrument.id)

        async def poll() -> None:
            while True:
                open_order_ids = {
                    order.id
                    for order in await session.fetch_open_orders(instrument_id=instrument.id)
                }
                if all(order_id not in open_order_ids for order_id in order_ids):
                    return
                await asyncio.sleep(1.0)

        await asyncio.wait_for(poll(), timeout=30.0)
    finally:
        if order_ids:
            with contextlib.suppress(Exception):
                await session.cancel_orders(order_ids=order_ids)
        await session.close()


@pytest.mark.integration
@pytest.mark.metered
async def test_places_and_cancels_one_perps_order_with_tp_sl(
    deposit_wallet_client: AsyncSecureClient,
) -> None:
    instrument = await _first_instrument(deposit_wallet_client)
    ticker = await deposit_wallet_client.fetch_perps_ticker(instrument_id=instrument.id)
    mark_price = ticker.mark_price
    price = _format_perps_price(mark_price / 2, instrument.price_decimals)
    session = await deposit_wallet_client.open_perps_session()
    try:
        placement = await session.place_order(
            instrument_id=instrument.id,
            side="BUY",
            price=price,
            quantity=_minimal_order_quantity(instrument, Decimal(price)),
            time_in_force="gtc",
            stop_loss=PerpsTpSlTrigger(
                trigger_price=_format_perps_price(mark_price / 4, instrument.price_decimals)
            ),
            take_profit=PerpsTpSlTrigger(
                trigger_price=_format_perps_price(mark_price * 2, instrument.price_decimals)
            ),
        )
        assert placement.tp_sl is not None
        assert placement.tp_sl.take_profit is not None
        assert placement.tp_sl.take_profit.order_id > 0
        assert placement.tp_sl.stop_loss is not None
        assert placement.tp_sl.stop_loss.order_id > 0

        result = await session.cancel_order(order_id=placement.order.id)
        assert result.status == "ok"
    finally:
        await session.close()


@pytest.mark.integration
@pytest.mark.metered
async def test_arms_reads_and_disarms_the_auto_cancel_switch(
    deposit_wallet_client: AsyncSecureClient,
) -> None:
    # Metered side effect: if the run dies between arm and disarm, the switch
    # cancel-alls the wallet's open orders (test orders only) at the deadline.
    session = await deposit_wallet_client.open_perps_session()
    try:
        # Whole seconds so the echoed deadline compares exactly, and far
        # enough out that the switch can never fire mid-suite.
        cancel_at = (datetime.now(tz=UTC) + timedelta(minutes=10)).replace(microsecond=0)
        try:
            await session.arm_auto_cancel(cancel_at=cancel_at)

            armed = await session.fetch_auto_cancel_status()
            assert armed.deadline == cancel_at
            assert armed.daily_limit > 0
        finally:
            await session.disarm_auto_cancel()

        disarmed = await session.fetch_auto_cancel_status()
        assert disarmed.deadline is None
    finally:
        await session.close()


@pytest.mark.integration
@pytest.mark.metered
async def test_resumes_existing_delegated_perps_credentials(
    deposit_wallet_client: AsyncSecureClient,
) -> None:
    initial_session = await deposit_wallet_client.open_perps_session(
        expires_in=timedelta(minutes=30)
    )
    try:
        resumed_session = await deposit_wallet_client.open_perps_session(
            credentials=initial_session.credentials
        )
        try:
            assert resumed_session.credentials == initial_session.credentials
        finally:
            await resumed_session.close()
    finally:
        await initial_session.close()


@pytest.mark.integration
@pytest.mark.metered
async def test_revokes_delegated_perps_credentials(
    deposit_wallet_client: AsyncSecureClient,
) -> None:
    session = await deposit_wallet_client.open_perps_session(expires_in=timedelta(minutes=30))
    credentials = session.credentials
    await session.close()

    await deposit_wallet_client.revoke_perps_credentials(proxy=credentials.proxy)

    with pytest.raises((RequestRejectedError, UnexpectedResponseError)):
        await deposit_wallet_client.open_perps_session(credentials=credentials)


@pytest.mark.integration
@pytest.mark.metered
async def test_rejects_delegated_perps_credentials_with_an_invalid_secret(
    deposit_wallet_client: AsyncSecureClient,
) -> None:
    session = await deposit_wallet_client.open_perps_session(expires_in=timedelta(minutes=30))
    try:
        tampered = session.credentials.model_copy(update={"secret": "invalid-secret"})
        with pytest.raises(RequestRejectedError):
            await deposit_wallet_client.open_perps_session(credentials=tampered)
    finally:
        await session.close()
