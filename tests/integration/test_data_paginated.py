from typing import TypeVar

import pytest

from polymarket import AsyncPublicClient, ComboBiggestWinner, PublicClient, TradeActivity
from polymarket.pagination import Page, Paginator

pytestmark = pytest.mark.integration
CONDITION = "0xe546672750517f62c45a5a00067481981e62b9c20fa8220203232c9dc8fd2093"
T = TypeVar("T")


def two_pages(paginator: Paginator[T]) -> tuple[Page[T], Page[T]]:
    first = paginator.first_page()
    if not first.items:
        pytest.skip("reference query no longer has rows")
    if first.next_cursor is None:
        pytest.skip("reference query no longer has a second page")
    second = paginator.from_cursor(first.next_cursor).first_page()
    assert second.items
    assert second.next_cursor != first.next_cursor
    return first, second


def test_trade_cursor_walk(sync_public_client: PublicClient) -> None:
    paginator = sync_public_client.list_trades(side="BUY", page_size=5)
    first, second = two_pages(paginator)
    assert second.next_cursor is not None
    third = paginator.from_cursor(second.next_cursor).first_page()
    assert len({p.next_cursor for p in (first, second, third)}) == 3
    for page in (first, second, third):
        assert len(page.items) == 5 and page.has_more
        assert all(row.side == "BUY" for row in page.items)
    timestamps = [row.timestamp for p in (first, second, third) for row in p.items]
    assert timestamps == sorted(timestamps, reverse=True)
    replay = paginator.from_cursor(first.next_cursor).first_page()
    assert replay.items[0].timestamp <= first.items[-1].timestamp


def test_activity_and_combo_activity(
    sync_public_client: PublicClient, data_reference_wallet: str
) -> None:
    page = sync_public_client.list_activity(
        user=data_reference_wallet, activity_types=["TRADE"]
    ).first_page()
    if not page.items:
        pytest.skip("reference wallet no longer has trade activity")
    assert all(p.type == "TRADE" and p.wallet == data_reference_wallet for p in page.items)
    first, second = two_pages(
        sync_public_client.list_combo_activity(user=data_reference_wallet, page_size=1)
    )
    for row in first.items + second.items:
        assert row.position_id and row.block_number > 0
        assert row.legs and row.legs[0].market and row.legs[0].market.question
        assert ("payout" in type(row).model_fields) == (row.type == "REDEEM")


def test_positions_and_market_anchor(
    sync_public_client: PublicClient, data_reference_wallet: str
) -> None:
    two_pages(sync_public_client.list_positions(user=data_reference_wallet, page_size=100))
    closed = sync_public_client.list_positions(
        user=data_reference_wallet, status="CLOSED"
    ).first_page()
    if not closed.items:
        pytest.skip("reference wallet no longer has closed positions")
    assert all(row.status == "CLOSED" for row in closed.items)
    market = sync_public_client.list_positions(condition_id=CONDITION).first_page()
    assert len({row.wallet for row in market.items}) > 1


def test_combo_positions_and_filters(
    sync_public_client: PublicClient, data_reference_wallet: str
) -> None:
    first, second = two_pages(
        sync_public_client.list_combo_positions(user=data_reference_wallet, page_size=1)
    )
    for row in first.items + second.items:
        assert row.current_size >= 0 and row.gross_entry_cost_usdc >= 0 and row.entry_fees_usdc >= 0
    condition = first.items[0].condition_id
    selected = sync_public_client.list_combo_positions(
        user=data_reference_wallet, condition_id=condition
    ).first_page()
    assert selected.items and all(row.condition_id == condition for row in selected.items)
    resolved = two_pages(
        sync_public_client.list_combo_positions(
            user=data_reference_wallet,
            status=["RESOLVED_WIN", "RESOLVED_PARTIAL", "RESOLVED_LOSS"],
            page_size=1,
        )
    )
    assert all(
        row.status in ("RESOLVED_WIN", "RESOLVED_PARTIAL", "RESOLVED_LOSS")
        for p in resolved
        for row in p.items
    )


def test_holders_pagination(sync_public_client: PublicClient) -> None:
    first, second = two_pages(
        sync_public_client.list_market_holders(
            condition_ids=CONDITION, include_pnl=True, min_balance=0, page_size=1
        )
    )
    for group in first.items + second.items:
        assert len(group.holders) <= 1
        assert all(h.asset_id == group.asset_id and h.total_pnl is not None for h in group.holders)


def test_price_history_pages(sync_public_client: PublicClient, active_clob_token: str) -> None:
    first, second = two_pages(
        sync_public_client.list_price_history(
            asset_id=active_clob_token, interval="1d", page_size=2
        )
    )
    assert second.items[0].timestamp > first.items[-1].timestamp
    assert all(p.resolution_seconds >= 0 for p in first.items + second.items)


def test_leaderboards_and_standing(sync_public_client: PublicClient) -> None:
    first, second = two_pages(
        sync_public_client.list_trader_leaderboard(
            category="sports", window="week", sort_by="VOLUME", page_size=1
        )
    )
    assert first.items[0].rank <= second.items[0].rank
    top = sync_public_client.list_trader_leaderboard(
        category="combos", window="all", page_size=1
    ).first_page()
    if not top.items:
        pytest.skip("no combo leaderboard rows available")
    standing = sync_public_client.get_trader_leaderboard_standing(
        user=top.items[0].wallet, category="combos", window="all"
    )
    assert standing is not None and standing.pnl_rank is not None
    winners = sync_public_client.list_biggest_winners(category="combos", page_size=2).first_page()
    assert winners.items and all(isinstance(row, ComboBiggestWinner) for row in winners.items)
    builders = two_pages(sync_public_client.list_builder_leaderboard(window="all", page_size=1))
    assert all(
        len(row.builder_code) == 66 and row.builder_code.startswith("0x")
        for p in builders
        for row in p.items
    )


@pytest.mark.anyio
async def test_async_trade_pages(
    public_client: AsyncPublicClient, data_reference_wallet: str
) -> None:
    paginator = public_client.list_activity(
        user=data_reference_wallet, activity_types=["TRADE"], page_size=2
    )
    first = await paginator.first_page()
    if not first.items or first.next_cursor is None:
        pytest.skip("reference wallet has insufficient activity")
    second = await paginator.from_cursor(first.next_cursor).first_page()
    assert second.items
    assert all(
        isinstance(row, TradeActivity) and row.wallet == data_reference_wallet
        for row in first.items + second.items
    )


def test_frames_on_live_data(sync_public_client: PublicClient, data_reference_wallet: str) -> None:
    positions = sync_public_client.list_positions(user=data_reference_wallet).first_page()
    if not positions.items:
        pytest.skip("reference wallet has no positions")
    assert "current_size" in positions.to_pandas().columns
    frame = sync_public_client.list_trades().to_polars(limit=50)
    assert len(frame) == 50 and "asset_id" in frame.columns
