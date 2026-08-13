from __future__ import annotations

from decimal import Decimal

import pytest

from polymarket import (
    AsyncSecureClient,
    BuilderApiKey,
    ComboAcceptFailureReason,
    ComboMarket,
    RfqDirection,
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


# Combo-enabled markets churn as games resolve, so fixed legs go stale. Pick
# two unrelated, liquid, mid-priced markets from the live catalog unless the
# operator provides an explicit override.
async def _discover_combo_leg_position_ids(client: AsyncSecureClient) -> list[str] | None:
    page = await client.list_combo_markets(page_size=100).first_page()
    picked: list[ComboMarket] = []
    for market in page.items:
        price = market.outcomes.yes.price
        if price < Decimal("0.05") or price > Decimal("0.95") or market.volume <= 0:
            continue
        if any(
            market.slug.startswith(other.slug) or other.slug.startswith(market.slug)
            for other in picked
        ):
            continue
        picked.append(market)
        if len(picked) == 2:
            return [str(item.outcomes.yes.position_id) for item in picked]
    return None


# Metered: creates a live combo RFQ, but does not accept it or execute an order.
@pytest.mark.metered
async def test_combo_sell_quote_returns_exact_net_proceeds(
    builder_client: AsyncSecureClient,
    combo_leg_position_ids: list[str] | None,
) -> None:
    legs = combo_leg_position_ids or await _discover_combo_leg_position_ids(builder_client)
    if legs is None:
        pytest.skip(
            "No combo legs discoverable; set POLYMARKET_COMBO_LEG_POSITION_IDS to override."
        )

    result = await builder_client.request_combo_quote(
        leg_position_ids=legs, direction="SELL", size=1
    )

    if result.quote is None:
        pytest.skip(f"No SELL combo quote available: {result.reason}")

    assert result.quote.direction is RfqDirection.SELL
    assert result.quote.net_receive is not None
    assert result.quote.net_receive > 0


# Metered: an accepted combo quote executes a live trade with real funds.
@pytest.mark.metered
async def test_combo_quote_request_accept_and_fill(
    builder_client: AsyncSecureClient,
    combo_leg_position_ids: list[str] | None,
) -> None:
    legs = combo_leg_position_ids or await _discover_combo_leg_position_ids(builder_client)
    if legs is None:
        pytest.skip(
            "No combo legs discoverable; set POLYMARKET_COMBO_LEG_POSITION_IDS to override."
        )

    result = await builder_client.request_combo_quote(
        leg_position_ids=legs, direction="BUY", amount=1
    )

    if result.quote is None:
        pytest.skip(f"No combo quote available: {result.reason}")

    acceptance = await builder_client.accept_combo_quote(result.quote)

    if acceptance.status == "failed":
        if acceptance.reason is ComboAcceptFailureReason.EXECUTION_FAILED:
            pytest.fail(
                f"Acceptance of RFQ {acceptance.rfq_id} failed to execute: {acceptance.error}"
            )
        pytest.skip(f"Combo acceptance did not execute: {acceptance.reason}")

    fill = await builder_client.wait_for_combo_fill(rfq_id=acceptance.rfq_id, timeout=120.0)

    assert fill.rfq_id == acceptance.rfq_id
    if fill.status is not RfqStatus.FILLED:
        pytest.fail(
            f"RFQ {acceptance.rfq_id} was handed off for execution but ended "
            f"{fill.status}: {fill.error}"
        )
    assert fill.tx_hash is not None
