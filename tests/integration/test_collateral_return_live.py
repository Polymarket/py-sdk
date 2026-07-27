"""Live collateral return integration tests.

Mirrors the TypeScript SDK collateral-return integration suite so both SDKs
assert the same production behavior.

Metered side effects:
- ``test_collateral_return_round_trip_live`` seeds the wallet by splitting
  1.000000 collateral into two combo positions when nothing is returnable,
  then executes collateral return plans until the seeded value is merged back
  (net-zero on the wallet by construction), and finally re-submits the
  executed plan expecting the service to reject it (no additional state).
- ``test_empty_plan_matches_contract_and_rejects_execution`` signs and
  submits an empty plan that the service rejects at re-validation (no state
  changes).
"""

import asyncio
import time
from decimal import Decimal

import pytest
from eth_account import Account

from polymarket import (
    AsyncSecureClient,
    CollateralReturnPlanResponse,
    RequestRejectedError,
    TransactionHandle,
    UserInputError,
)

pytestmark = pytest.mark.anyio

_PLAN_RETRY_ATTEMPTS = 5
_PLAN_RETRY_DELAY_S = 5.0
_SEED_AMOUNT = 1_000_000
_SEED_PLAN_TIMEOUT_S = 120.0
_SEED_PLAN_POLL_S = 5.0
_ROUND_TRIP_TIMEOUT_S = 600.0
_REPLAN_ATTEMPTS = 3
_PLAN_HASH_LENGTH = 66  # 0x-prefixed 32-byte hex


async def _fetch_plan(client: AsyncSecureClient) -> CollateralReturnPlanResponse:
    """Fetch a plan, retrying the occasional transient edge 5xx."""
    for attempt in range(_PLAN_RETRY_ATTEMPTS):
        try:
            return await client.plan_collateral_return()
        except RequestRejectedError as error:
            if error.status < 500 or attempt == _PLAN_RETRY_ATTEMPTS - 1:
                raise
            await asyncio.sleep(_PLAN_RETRY_DELAY_S)
    raise AssertionError("unreachable")


async def _execute_plan(
    client: AsyncSecureClient, plan: CollateralReturnPlanResponse
) -> TransactionHandle:
    """Execute a plan, retrying the occasional transient edge 5xx.

    A retry after a masked successful submission is safe: the service
    re-validates the plan hash and rejects it with the documented 409.
    """
    for attempt in range(_PLAN_RETRY_ATTEMPTS):
        try:
            return await client.execute_collateral_return_plan(plan=plan)
        except RequestRejectedError as error:
            if error.status < 500 or attempt == _PLAN_RETRY_ATTEMPTS - 1:
                raise
            await asyncio.sleep(_PLAN_RETRY_DELAY_S)
    raise AssertionError("unreachable")


def _assert_plan_hash(plan: CollateralReturnPlanResponse) -> None:
    assert plan.plan_hash.startswith("0x")
    assert len(plan.plan_hash) == _PLAN_HASH_LENGTH
    int(plan.plan_hash, 16)


@pytest.mark.integration
async def test_plan_collateral_return_live(deposit_wallet_client: AsyncSecureClient) -> None:
    assert deposit_wallet_client.wallet_type == "DEPOSIT_WALLET"

    plan = await _fetch_plan(deposit_wallet_client)
    environment = deposit_wallet_client.environment

    assert plan.wallet.lower() == str(deposit_wallet_client.wallet).lower()
    _assert_plan_hash(plan)
    assert plan.chain_id == environment.chain_id
    assert plan.block_number > 0
    assert plan.router_call.to.lower() == environment.protocol_v2_router.lower()
    assert plan.router_call.data.startswith("0x")


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
@pytest.mark.metered
async def test_empty_plan_matches_contract_and_rejects_execution(
    deposit_wallet_client: AsyncSecureClient,
) -> None:
    # Live side effects: signs and submits the empty plan, which the service
    # rejects at re-validation without changing wallet state.
    # Mirrors the ts-sdk empty-plan scenario. The account holds no returnable
    # inventory between metered runs; skip while inventory is pending.
    plan = await _fetch_plan(deposit_wallet_client)

    if plan.net_pusd_out > 0:
        pytest.skip("account holds returnable inventory; empty plan unavailable")

    assert plan.operations == ()

    # A plan that returns no collateral is re-validated and rejected by the
    # service at submission.
    with pytest.raises(RequestRejectedError):
        await deposit_wallet_client.execute_collateral_return_plan(plan=plan)


@pytest.mark.integration
@pytest.mark.metered
async def test_collateral_return_round_trip_live(deposit_wallet_client: AsyncSecureClient) -> None:
    # Live side effects: may split 1.000000 collateral into two combo positions
    # to seed the wallet, then submits collateral return transactions that merge
    # the seeded value back to collateral. The final stale re-submission is
    # rejected by the service and adds no further state.
    client = deposit_wallet_client

    async def run() -> None:
        plan = await _fetch_plan(client)
        if plan.net_pusd_out <= 0:
            plan = await _seed_returnable_positions(client, plan)

        executed_plan: CollateralReturnPlanResponse | None = None
        rejections = 0
        while plan.net_pusd_out > 0:
            try:
                handle = await _execute_plan(client, plan)
            except RequestRejectedError as error:
                # Documented recovery: state moved between plan and submit,
                # so the service rejects the stale plan with a 409.
                if error.status != 409:
                    raise
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
        with pytest.raises(RequestRejectedError):
            await _execute_plan(client, executed_plan)

    await asyncio.wait_for(run(), timeout=_ROUND_TRIP_TIMEOUT_S)


async def _seed_returnable_positions(
    client: AsyncSecureClient, plan: CollateralReturnPlanResponse
) -> CollateralReturnPlanResponse:
    if plan.starting_pusd < 1:
        pytest.skip("wallet needs at least 1.000000 collateral to seed a returnable position")
    legs = await _pick_combo_legs(client)
    handle = await client.split_position(amount=_SEED_AMOUNT, legs=legs)
    await handle.wait()

    deadline = time.monotonic() + _SEED_PLAN_TIMEOUT_S
    while True:
        refreshed = await _fetch_plan(client)
        if refreshed.net_pusd_out > 0:
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
