from __future__ import annotations

from collections.abc import Callable

import pytest

from polymarket import (
    AsyncSecureClient,
    BuilderApiKey,
    RfqRequestRejectedError,
    RfqStatus,
)

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


@pytest.fixture
async def builder_client(
    deposit_wallet_private_key: str,
    deposit_wallet_address: str,
    builder_api_key: BuilderApiKey,
):
    client = await AsyncSecureClient.create(
        private_key=deposit_wallet_private_key,
        wallet=deposit_wallet_address,
        api_key=builder_api_key,
    )
    try:
        yield client
    finally:
        await client.close()


async def test_fetch_rfq_status_rejects_unknown_rfq(
    builder_client: AsyncSecureClient,
) -> None:
    with pytest.raises(RfqRequestRejectedError):
        await builder_client.fetch_rfq_status(rfq_id="rfq-00000000-0000-0000-0000-000000000000")


# Metered: an accepted combo quote executes a live trade with real funds.
@pytest.mark.metered
async def test_combo_quote_request_accept_and_fill(
    builder_client: AsyncSecureClient,
    require_env: Callable[[str], str],
) -> None:
    legs = [
        leg.strip()
        for leg in require_env("POLYMARKET_COMBO_LEG_POSITION_IDS").split(",")
        if leg.strip()
    ]
    if len(legs) < 2:
        pytest.skip("POLYMARKET_COMBO_LEG_POSITION_IDS must list at least 2 position IDs")

    result = await builder_client.request_combo_quote(
        leg_position_ids=legs, direction="BUY", amount=1
    )

    if result.quote is None:
        pytest.skip(f"No combo quote available: {result.reason}")

    acceptance = await builder_client.accept_combo_quote(result)

    if acceptance.status == "failed":
        pytest.skip(f"Combo acceptance did not execute: {acceptance.reason}")

    fill = await builder_client.wait_for_combo_fill(rfq_id=acceptance.rfq_id, timeout=120.0)

    assert fill.rfq_id == acceptance.rfq_id
    if fill.status is RfqStatus.FILLED:
        assert fill.tx_hash is not None
