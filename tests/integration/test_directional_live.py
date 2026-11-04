"""Metered staging round trip: spends 2 pUSD to seed line inventory, merges one
pair, reverses it, then merges the original complete sets to restore balances.
Approvals persist. Uses a dedicated wallet and never retries a submission.
"""

# pyright: reportPrivateUsage=false
import asyncio
import time
from collections.abc import Callable, Sequence
from typing import cast

import pytest

from polymarket import (
    ActivityType,
    AsyncSecureClient,
    DirectionalMergeActivity,
    UserInputError,
    derive_directional_bucket_positions,
    derive_directional_threshold_positions,
)
from polymarket._internal.actions.relayer.calls import (
    decode_erc20_balance_of_result,
    decode_erc1155_balance_of_batch_result,
    erc20_balance_of_call,
    erc1155_balance_of_batch_call,
)
from polymarket._internal.environment import PRODUCTION_CONFIG, get_environment_config
from polymarket.types import EvmAddress


async def _balances(client: AsyncSecureClient, ids: Sequence[str]) -> tuple[int, tuple[int, ...]]:
    config = get_environment_config(client.environment)
    collateral = erc20_balance_of_call(
        token_address=cast(EvmAddress, config.collateral_token), owner=client.wallet
    )
    positions = erc1155_balance_of_batch_call(
        token_address=cast(EvmAddress, config.position_manager),
        owners=[client.wallet] * len(ids),
        token_ids=list(ids),
    )
    values = await client._ctx.rpc.eth_call_batch(
        [(str(collateral.to), collateral.data), (str(positions.to), positions.data)]
    )
    return decode_erc20_balance_of_result(values[0]), decode_erc1155_balance_of_batch_result(
        values[1]
    )


@pytest.mark.integration
@pytest.mark.metered
@pytest.mark.anyio
async def test_directional_merge_reverse_live(
    deposit_wallet_client: AsyncSecureClient, require_env: Callable[[str], str]
) -> None:
    client = deposit_wallet_client
    event_id = require_env("POLYMARKET_DCR_EVENT_ID")
    config = get_environment_config(client.environment)
    if client.environment.name == "production" or config.rpc_url == PRODUCTION_CONFIG.rpc_url:
        pytest.fail("Directional round trips require an explicit staging environment and RPC")
    low = derive_directional_threshold_positions(event_id=event_id, line=1)
    high = derive_directional_threshold_positions(event_id=event_id, line=2)
    middle = derive_directional_bucket_positions(event_id=event_id, bucket_index=1)
    ids = [
        low.above_position_id,
        low.below_position_id,
        high.above_position_id,
        high.below_position_id,
        middle.yes_position_id,
    ]
    baseline = await _balances(client, ids)
    assert baseline[1] == (0,) * len(ids), "Use a dedicated wallet with no inventory in this pair"
    assert baseline[0] >= 2_000_000
    with pytest.raises(UserInputError):
        await client.prepare_merge_directional(low.above_position_id, low.below_position_id)
    await client.setup_trading_approvals()

    amount = 1_000_000
    seeded: list[str] = []
    merged = False
    errors: list[Exception] = []
    try:
        for condition in [low.condition_id, high.condition_id]:
            handle = await client.split_position(condition_id=condition, amount=amount)
            await handle.wait()
            seeded.append(condition)
        handle = await client.merge_directional(high.below_position_id, low.above_position_id)
        outcome = await handle.wait()
        merged = True
        assert await _balances(client, ids) == (
            baseline[0] - amount,
            (0, amount, amount, 0, amount),
        )
        deadline = time.monotonic() + 30
        while True:
            page = await client.list_activity(
                activity_types=[ActivityType.DIRECTIONAL_MERGE]
            ).first_page()
            rows = [row for row in page.items if row.transaction_hash == outcome.transaction_hash]
            if rows:
                assert len(rows) == 1 and isinstance(rows[0], DirectionalMergeActivity)
                assert rows[0].pairs == 1 and rows[0].amount == 1
                break
            if time.monotonic() >= deadline:
                pytest.fail("Confirmed merge has no activity row after 30 seconds")
            await asyncio.sleep(1)
        positions = await client.list_positions(condition_id=middle.condition_id).first_page()
        assert any(p.asset_id == middle.yes_position_id for p in positions.items)
    except Exception as error:
        errors.append(error)
    finally:
        if merged:
            try:
                reverse = await client.split_directional(
                    low.above_position_id, high.below_position_id, amount=amount
                )
                await reverse.wait()
                merged = False
                assert await _balances(client, ids) == (
                    baseline[0] - 2 * amount,
                    (amount, amount, amount, amount, 0),
                )
            except Exception as error:
                errors.append(error)
        if not merged:
            for condition in seeded:
                try:
                    cleanup = await client.merge_positions(condition_id=condition, amount=amount)
                    await cleanup.wait()
                except Exception as error:
                    errors.append(error)
    if errors:
        raise ExceptionGroup("Directional round trip or cleanup failed", errors)
    assert await _balances(client, ids) == baseline
