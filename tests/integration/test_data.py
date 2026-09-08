from datetime import UTC, datetime
from decimal import Decimal

import pytest

from polymarket import AsyncPublicClient, AsyncSecureClient, PublicClient

pytestmark = pytest.mark.integration
WALLET = "0x7c3db723f1d4d8cb9c550095203b686cb11e5c6b"
CONDITION = "0xe546672750517f62c45a5a00067481981e62b9c20fa8220203232c9dc8fd2093"


def test_portfolio_and_metrics(sync_public_client: PublicClient) -> None:
    client = sync_public_client
    portfolio = client.get_portfolio_value(user=WALLET)
    assert portfolio.wallet == WALLET and isinstance(portfolio.value, Decimal)
    stats = client.get_user_stats(user=WALLET)
    if stats is None:
        pytest.skip("reference wallet no longer has statistics")
    assert stats.traded_market_count > 0 and stats.all_time_pnl is not None
    assert client.get_user_stats(user="0x00000000000000000000000000000000000000aa") is None
    pnl = client.get_user_pnl(user=WALLET, interval="1w", fidelity="1h")
    assert pnl.interval == "1w" and pnl.fidelity == "1h" and pnl.source_fidelity
    assert pnl.points
    volume = client.get_user_volume(
        user=WALLET, start=datetime(2026, 9, 1, tzinfo=UTC), end=datetime(2026, 9, 2, tzinfo=UTC)
    )
    assert volume.volume >= 0 and volume.volume_usdc >= 0 and volume.trade_count >= 0


def test_market_analytics_and_resolutions(sync_public_client: PublicClient) -> None:
    client = sync_public_client
    global_oi = client.get_open_interests()
    assert len(global_oi) == 1 and global_oi[0].condition_id is None
    named = client.get_open_interests(condition_ids=CONDITION)
    if not named:
        pytest.skip("reference condition has no open interest row")
    assert len(named) == 1 and named[0].condition_id == CONDITION
    volume = client.get_event_live_volume(event_ids=[106884])
    assert isinstance(volume.taker_volume_total, Decimal) and isinstance(volume.markets, tuple)
    rows = client.get_resolutions(event_ids=[106884])
    if not rows:
        pytest.skip("reference event no longer has resolution rows")
    condition = rows[0].condition_id
    assert condition is not None
    selected = client.get_resolutions(condition_ids=condition)
    assert selected and selected[0] == rows[0]


def test_builder_volume_counts_buckets(sync_public_client: PublicClient) -> None:
    points = sync_public_client.get_builder_volumes(interval="day", bucket_limit=2)
    if not points:
        pytest.skip("no builder volume buckets available")
    assert len({p.bucket_date for p in points}) == 2
    assert len(points) > 2


def test_accounting_snapshot(sync_public_client: PublicClient) -> None:
    archive = sync_public_client.download_accounting_snapshot(user=WALLET)
    assert archive.startswith(b"PK") and len(archive) > 100


@pytest.mark.anyio
async def test_async_portfolio(public_client: AsyncPublicClient) -> None:
    value = await public_client.get_portfolio_value(user=WALLET)
    assert value.wallet == WALLET and value.value >= 0
    assert (await public_client.get_user_pnl(user=WALLET)).wallet == WALLET


@pytest.mark.anyio
async def test_authenticated_wallet_defaults(
    deposit_wallet_client: AsyncSecureClient, deposit_wallet_address: str
) -> None:
    client = deposit_wallet_client
    value = await client.get_portfolio_value()
    assert value.wallet.lower() == deposit_wallet_address.lower()
    positions = await client.list_positions().first_page()
    assert all(p.wallet.lower() == deposit_wallet_address.lower() for p in positions.items)
    activity = await client.list_activity().first_page()
    assert all(
        p.wallet and p.wallet.lower() == deposit_wallet_address.lower() for p in activity.items
    )
    standing = await client.get_trader_leaderboard_standing()
    if standing is not None:
        assert standing.wallet.lower() == deposit_wallet_address.lower()
