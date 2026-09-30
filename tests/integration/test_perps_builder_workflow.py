"""Live builder reads. Session creation is metered; no fee consent is changed."""

from collections.abc import Callable
from datetime import timedelta

import pytest

from polymarket import AsyncPublicClient, AsyncSecureClient

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


async def test_builder_status(
    public_client: AsyncPublicClient, require_env: Callable[[str], str]
) -> None:
    address = require_env("POLYMARKET_PERPS_BUILDER_ADDRESS")
    status = await public_client.fetch_perps_builder_status(address=address)
    assert status.address.lower() == address.lower()
    assert status.max_fee_rate >= 0


@pytest.mark.metered
async def test_builder_consent_restoration(
    deposit_wallet_client: AsyncSecureClient, require_env: Callable[[str], str]
) -> None:
    # Live side effect: creates delegated credentials valid for five minutes.
    # Existing consent is read only; no fees are approved and no orders are placed.
    builder_address = require_env("POLYMARKET_PERPS_BUILDER_ADDRESS")
    async with await deposit_wallet_client.open_perps_session(
        expires_in=timedelta(minutes=5)
    ) as session:
        approvals = await session.fetch_builder_approvals(builder=builder_address)
        approval = next(
            (a for a in approvals if a.builder.lower() == builder_address.lower()), None
        )
        if approval is None or approval.max_fee_rate <= 0:
            pytest.skip("Builder restoration requires existing positive fee consent")
        status = await deposit_wallet_client.fetch_perps_builder_status(address=builder_address)
        if not status.registered or not status.enabled or not status.admission_enabled:
            pytest.skip("Builder restoration requires an active builder")
        async with await deposit_wallet_client.open_perps_session(
            credentials=session.credentials, builder_attribution=builder_address
        ) as restored:
            assert restored.builder_attribution is not None
            assert restored.builder_attribution.address.lower() == builder_address.lower()
            assert restored.builder_attribution.fee_rate == min(
                status.max_fee_rate, approval.max_fee_rate
            )
            assert await restored.fetch_builder_approvals(builder=builder_address) == approvals


@pytest.mark.metered
async def test_builder_reporting_snapshot(deposit_wallet_client: AsyncSecureClient) -> None:
    # Live side effect: creates delegated credentials valid for five minutes.
    # Reads receipts/consent only; does not approve fees or place orders.
    async with await deposit_wallet_client.open_perps_session(
        expires_in=timedelta(minutes=5)
    ) as session:
        page = await session.list_builder_earnings().first_page()
        snapshot = page.snapshot
        assert snapshot is not None
        summary = await session.fetch_builder_earnings_summary(
            start=snapshot.start, end=snapshot.end, as_of_sequence=snapshot.as_of_sequence
        )
        assert summary.snapshot == snapshot
        if not page.has_more:
            assert sum(asset.fill_count for asset in summary.assets) == len(page.items)
        approvals = await session.fetch_builder_approvals()
        assert all(a.trader.lower() == deposit_wallet_client.signer.lower() for a in approvals)
