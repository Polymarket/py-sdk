"""Live collateral return integration tests.

Mirrors the TypeScript SDK collateral-return integration suite so both SDKs
assert the same production behavior.

Metered side effects:
- ``test_collateral_return_round_trip_live`` seeds the wallet by splitting
  1.000000 collateral into two combo positions when nothing is returnable,
  then executes collateral return plans until the seeded value is merged back
  (net-zero on the wallet by construction).
"""

import asyncio
import time
from decimal import Decimal

import pytest

from polymarket import (
    AsyncSecureClient,
    CollateralReturnPlan,
    CollateralReturnPlanRejectedError,
    RequestRejectedError,
    TransactionHandle,
)

pytestmark = pytest.mark.anyio

_PLAN_RETRY_ATTEMPTS = 5
_PLAN_RETRY_DELAY_S = 5.0
_SEED_AMOUNT = 1_000_000
_SEED_PLAN_TIMEOUT_S = 120.0
_SEED_PLAN_POLL_S = 5.0
_ROUND_TRIP_TIMEOUT_S = 600.0
_REPLAN_ATTEMPTS = 3


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


async def _execute_plan(client: AsyncSecureClient, plan: CollateralReturnPlan) -> TransactionHandle:
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


@pytest.mark.integration
@pytest.mark.metered
async def test_collateral_return_round_trip_live(deposit_wallet_client: AsyncSecureClient) -> None:
    # Live side effects: may split 1.000000 collateral into two combo positions
    # to seed the wallet, then submits collateral return transactions that merge
    # the seeded value back to collateral.
    client = deposit_wallet_client

    async def run() -> None:
        plan = await _fetch_plan(client)
        if plan.collateral_returned <= 0:
            plan = await _seed_returnable_positions(client, plan)

        executed = 0
        rejections = 0
        while plan.collateral_returned > 0:
            try:
                handle = await _execute_plan(client, plan)
            except CollateralReturnPlanRejectedError:
                # Documented recovery: state moved between plan and submit.
                rejections += 1
                assert rejections <= _REPLAN_ATTEMPTS
                plan = await _fetch_plan(client)
                continue
            outcome = await handle.wait()
            assert outcome.transaction_hash
            executed += 1
            if not plan.truncated:
                break
            plan = await _fetch_plan(client)
        assert executed > 0

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
