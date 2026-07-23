"""Live collateral return integration tests.

Mirrors the TypeScript SDK collateral-return integration suite so both SDKs
assert the same production behavior.

Metered side effects:
- ``test_collateral_return_round_trip_live`` seeds the wallet by splitting
  1.000000 collateral into two combo positions when nothing is returnable,
  then executes collateral return plans until the seeded value is merged back
  (net-zero on the wallet by construction), and finally re-submits the
  executed plan expecting the service to reject it (no additional state).
"""

import asyncio
import time
from collections.abc import AsyncGenerator
from decimal import Decimal

import pytest
from eth_account import Account

from polymarket import (
    AsyncSecureClient,
    CollateralReturnPlan,
    CollateralReturnPlanRejectedError,
    RelayerApiKey,
    RequestRejectedError,
    UserInputError,
)

pytestmark = pytest.mark.anyio

_PLAN_RETRY_ATTEMPTS = 3
_PLAN_RETRY_DELAY_S = 5.0
_SEED_AMOUNT = 1_000_000
_SEED_PLAN_TIMEOUT_S = 120.0
_SEED_PLAN_POLL_S = 5.0
_ROUND_TRIP_TIMEOUT_S = 600.0
_REPLAN_ATTEMPTS = 3
_PLAN_HASH_LENGTH = 66  # 0x-prefixed 32-byte hex


@pytest.fixture
async def collateral_client(
    deposit_wallet_private_key: str,
    deposit_wallet_address: str,
    relayer_api_key: RelayerApiKey,
) -> AsyncGenerator[AsyncSecureClient, None]:
    client = await AsyncSecureClient.create(
        private_key=deposit_wallet_private_key,
        wallet=deposit_wallet_address,
        api_key=relayer_api_key,
    )
    try:
        yield client
    finally:
        await client.close()


async def _fetch_plan(client: AsyncSecureClient) -> CollateralReturnPlan:
    """Fetch a plan, retrying the occasional transient edge 5xx."""
    for attempt in range(_PLAN_RETRY_ATTEMPTS):
        try:
            return await client.plan_collateral_return()
        except RequestRejectedError as error:
            if error.status < 500 or attempt == _PLAN_RETRY_ATTEMPTS - 1:
                raise
            await asyncio.sleep(_PLAN_RETRY_DELAY_S)
    raise AssertionError("unreachable")


def _assert_plan_hash(plan: CollateralReturnPlan) -> None:
    assert plan.plan_hash.startswith("0x")
    assert len(plan.plan_hash) == _PLAN_HASH_LENGTH
    int(plan.plan_hash, 16)


@pytest.mark.integration
async def test_plan_collateral_return_live(collateral_client: AsyncSecureClient) -> None:
    assert collateral_client.wallet_type == "DEPOSIT_WALLET"

    plan = await _fetch_plan(collateral_client)
    environment = collateral_client.environment

    assert plan.wallet.lower() == str(collateral_client.wallet).lower()
    _assert_plan_hash(plan)
    assert plan.chain_id == environment.chain_id
    assert plan.block_number > 0
    assert plan.router_call.to.lower() == environment.protocol_v2_router.lower()
    assert plan.router_call.data.startswith("0x")

    for amount in (
        plan.starting_collateral,
        plan.collateral_returned,
        plan.final_collateral,
        plan.required_collateral,
    ):
        assert isinstance(amount, Decimal)
    assert isinstance(plan.position_summary.consumed, tuple)
    assert isinstance(plan.position_summary.created, tuple)
    for operation in plan.operations:
        assert operation.kind
        assert isinstance(operation.amount, Decimal)
        assert operation.amount >= 0


@pytest.mark.integration
async def test_plan_collateral_return_safe_wallet_live(
    safe_wallet_private_key: str,
    safe_wallet_address: str,
) -> None:
    client = await AsyncSecureClient.create(
        private_key=safe_wallet_private_key,
        wallet=safe_wallet_address,
    )
    try:
        assert client.wallet_type == "GNOSIS_SAFE"
        plan = await _fetch_plan(client)
        assert plan.wallet.lower() == safe_wallet_address.lower()
        _assert_plan_hash(plan)
    finally:
        await client.close()


@pytest.mark.integration
async def test_plan_collateral_return_proxy_wallet_live(
    proxy_wallet_private_key: str,
    proxy_wallet_address: str,
) -> None:
    client = await AsyncSecureClient.create(
        private_key=proxy_wallet_private_key,
        wallet=proxy_wallet_address,
    )
    try:
        assert client.wallet_type == "POLY_PROXY"
        plan = await _fetch_plan(client)
        assert plan.wallet.lower() == proxy_wallet_address.lower()
        _assert_plan_hash(plan)
    finally:
        await client.close()


@pytest.mark.integration
async def test_plan_collateral_return_rejects_eoa_account() -> None:
    account = Account.create()
    client = await AsyncSecureClient.create(
        private_key="0x" + account.key.hex().removeprefix("0x"),
        wallet=account.address,
    )
    try:
        assert client.wallet_type == "EOA"
        with pytest.raises(UserInputError, match="EOA"):
            await client.plan_collateral_return()
    finally:
        await client.close()


@pytest.mark.integration
async def test_empty_plan_matches_contract_and_rejects_execution(
    collateral_client: AsyncSecureClient,
) -> None:
    # Mirrors the ts-sdk empty-plan scenario. The account holds no returnable
    # inventory between metered runs; skip while inventory is pending.
    plan = await _fetch_plan(collateral_client)

    if plan.collateral_returned > 0:
        pytest.skip("account holds returnable inventory; empty plan unavailable")

    assert plan.collateral_returned == Decimal("0")
    assert plan.required_collateral == Decimal("0")
    # The wire carries decimal-6 strings ("0.000000"), matching the unit
    # fixtures; the parsed Decimal keeps that exponent.
    assert plan.collateral_returned.as_tuple().exponent == -6
    assert plan.operations == ()
    assert plan.required_positions == ()
    assert plan.position_summary.consumed == ()
    assert plan.position_summary.created == ()
    assert plan.truncated is False
    assert plan.starting_collateral == plan.final_collateral
    _assert_plan_hash(plan)
    assert plan.router_call.data.startswith("0x")

    # ts-sdk submits an empty plan and relies on the service rejecting it at
    # re-validation; this SDK fails fast client-side before anything is signed.
    with pytest.raises(UserInputError, match="no operations"):
        await collateral_client.execute_collateral_return_plan(plan=plan)


@pytest.mark.integration
@pytest.mark.metered
async def test_collateral_return_round_trip_live(collateral_client: AsyncSecureClient) -> None:
    # Live side effects: may split 1.000000 collateral into two combo positions
    # to seed the wallet, then submits collateral return transactions that merge
    # the seeded value back to collateral. The final stale re-submission is
    # rejected by the service and adds no further state.
    client = collateral_client

    async def run() -> None:
        plan = await _fetch_plan(client)
        if plan.collateral_returned <= 0:
            plan = await _seed_returnable_positions(client, plan)

        executed_plan: CollateralReturnPlan | None = None
        rejections = 0
        while plan.collateral_returned > 0:
            try:
                handle = await client.execute_collateral_return_plan(plan=plan)
            except CollateralReturnPlanRejectedError:
                # Documented recovery: state moved between plan and submit.
                rejections += 1
                assert rejections <= _REPLAN_ATTEMPTS
                plan = await _fetch_plan(client)
                continue
            outcome = await handle.wait()
            assert outcome.transaction_hash
            executed_plan = plan
            if not plan.truncated:
                break
            plan = await _fetch_plan(client)
        assert executed_plan is not None

        # The executed plan no longer matches wallet state; re-submitting it
        # must be rejected in favor of a fresh plan (the same 409 contract the
        # unit tests assert against a mocked service).
        with pytest.raises(CollateralReturnPlanRejectedError):
            await client.execute_collateral_return_plan(plan=executed_plan)

    await asyncio.wait_for(run(), timeout=_ROUND_TRIP_TIMEOUT_S)


async def _seed_returnable_positions(
    client: AsyncSecureClient, plan: CollateralReturnPlan
) -> CollateralReturnPlan:
    if plan.starting_collateral < 1:
        pytest.skip("wallet needs at least 1.000000 collateral to seed a returnable position")
    legs = await _pick_combo_legs(client)
    handle = await client.split_position(amount=_SEED_AMOUNT, legs=legs)
    await handle.wait()

    deadline = time.monotonic() + _SEED_PLAN_TIMEOUT_S
    while True:
        refreshed = await _fetch_plan(client)
        if refreshed.collateral_returned > 0:
            return refreshed
        if time.monotonic() >= deadline:
            pytest.fail("seeded split did not become returnable in time")
        await asyncio.sleep(_SEED_PLAN_POLL_S)


async def _pick_combo_legs(client: AsyncSecureClient) -> list[str]:
    page = await client.list_combo_markets(page_size=10).first_page()
    legs: list[str] = []
    for market in page.items:
        # Skip effectively-resolved markets so the seeding split cannot fail.
        if not Decimal(0) < market.outcomes.yes.price < Decimal(1):
            continue
        legs.append(str(market.outcomes.yes.position_id))
        if len(legs) == 2:
            return legs
    pytest.skip("not enough tradable combo markets available to seed a combo position")
