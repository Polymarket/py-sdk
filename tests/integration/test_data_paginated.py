import asyncio

import pytest

from polymarket import (
    Activity,
    AsyncPublicClient,
    ClosedPosition,
    ComboActivity,
    ComboPosition,
    ComboPositionStatus,
    LeaderboardEntry,
    MetaMarketPosition,
    Position,
    PublicClient,
    Trade,
    TraderLeaderboardEntry,
)

WALLET = "0x16c9fb76d5e12c6e35738fd92223ea603004ffa7"
COMBO_WALLET = "0x7c3db723f1d4d8cb9c550095203b686cb11e5c6b"


def _condition_ids_for_event(event_id: str = "902661") -> list[str]:
    with PublicClient() as client:
        event = client.get_event(id=event_id)
    return [m.condition_id for m in event.markets if m.condition_id is not None]


@pytest.mark.integration
def test_list_positions_first_page() -> None:
    with PublicClient() as client:
        page = client.list_positions(user=WALLET, page_size=5).first_page()
    assert all(isinstance(p, Position) for p in page.items)
    assert len(page.items) <= 5


@pytest.mark.integration
def test_list_positions_iterates_lazily() -> None:
    with PublicClient() as client:
        paginator = client.list_positions(user=WALLET, page_size=5)
        for index, page in enumerate(paginator):
            assert all(isinstance(p, Position) for p in page.items)
            if index >= 1:
                break


@pytest.mark.integration
def test_list_positions_resume_from_cursor() -> None:
    with PublicClient() as client:
        paginator = client.list_positions(user=WALLET, page_size=2)
        first = paginator.first_page()
        if first.next_cursor is None:
            pytest.skip("wallet has fewer than two pages of positions")
        second = paginator.from_cursor(first.next_cursor).first_page()
        assert all(isinstance(p, Position) for p in second.items)


@pytest.mark.integration
def test_list_closed_positions_first_page() -> None:
    with PublicClient() as client:
        page = client.list_closed_positions(user=WALLET, page_size=5).first_page()
    assert all(isinstance(p, ClosedPosition) for p in page.items)


@pytest.mark.integration
def test_list_combo_positions_first_page() -> None:
    with PublicClient() as client:
        page = client.list_combo_positions(user=COMBO_WALLET, page_size=1).first_page()
    assert all(isinstance(p, ComboPosition) for p in page.items)
    assert len(page.items) <= 1


@pytest.mark.integration
def test_list_combo_positions_filters_by_condition_id() -> None:
    with PublicClient() as client:
        first = client.list_combo_positions(user=COMBO_WALLET, page_size=1).first_page()
        if not first.items:
            pytest.skip("wallet has no combo positions")
        condition_id = first.items[0].condition_id
        filtered = client.list_combo_positions(
            user=COMBO_WALLET, condition_id=condition_id, page_size=1
        ).first_page()
    assert filtered.items
    assert filtered.items[0].condition_id == condition_id


@pytest.mark.integration
def test_list_combo_positions_filters_by_multiple_statuses() -> None:
    statuses: list[ComboPositionStatus] = ["RESOLVED_WIN", "RESOLVED_PARTIAL", "RESOLVED_LOSS"]
    with PublicClient() as client:
        paginator = client.list_combo_positions(user=COMBO_WALLET, status=statuses, page_size=1)
        first = paginator.first_page()
        pages = [first]
        if first.next_cursor is not None:
            pages.append(paginator.from_cursor(first.next_cursor).first_page())
    assert first.items
    assert all(position.status in statuses for page in pages for position in page.items)


@pytest.mark.integration
def test_list_combo_positions_filters_by_single_status() -> None:
    status: ComboPositionStatus = "RESOLVED_WIN"
    with PublicClient() as client:
        page = client.list_combo_positions(
            user=COMBO_WALLET, status=status, page_size=10
        ).first_page()
    assert page.items
    assert all(p.status == status for p in page.items)


@pytest.mark.integration
def test_list_market_positions_first_page() -> None:
    condition_ids = _condition_ids_for_event()
    if not condition_ids:
        pytest.skip("event has no condition IDs")
    with PublicClient() as client:
        page = client.list_market_positions(market=condition_ids[0], page_size=5).first_page()
    assert all(isinstance(p, MetaMarketPosition) for p in page.items)


@pytest.mark.integration
def test_list_trades_first_page() -> None:
    with PublicClient() as client:
        page = client.list_trades(user=WALLET, page_size=5).first_page()
    assert all(isinstance(t, Trade) for t in page.items)


@pytest.mark.integration
def test_list_activity_first_page() -> None:
    with PublicClient() as client:
        page = client.list_activity(user=WALLET, page_size=5).first_page()
    valid_activity = (Activity.__args__) if hasattr(Activity, "__args__") else ()
    assert all(isinstance(a, valid_activity) for a in page.items) if valid_activity else True


@pytest.mark.integration
def test_list_combo_activity_first_page() -> None:
    with PublicClient() as client:
        page = client.list_combo_activity(user=COMBO_WALLET, page_size=1).first_page()
    valid_activity = (ComboActivity.__args__) if hasattr(ComboActivity, "__args__") else ()
    assert all(isinstance(a, valid_activity) for a in page.items) if valid_activity else True
    assert len(page.items) <= 1


@pytest.mark.integration
def test_list_builder_leaderboard_first_page_has_results() -> None:
    with PublicClient() as client:
        page = client.list_builder_leaderboard(time_period="DAY", page_size=5).first_page()
    assert len(page.items) > 0
    assert all(isinstance(entry, LeaderboardEntry) for entry in page.items)


@pytest.mark.integration
def test_list_trader_leaderboard_first_page_has_results() -> None:
    with PublicClient() as client:
        page = client.list_trader_leaderboard(
            category="OVERALL",
            time_period="DAY",
            order_by="VOL",
            page_size=5,
        ).first_page()
    assert len(page.items) > 0
    assert all(isinstance(entry, TraderLeaderboardEntry) for entry in page.items)


@pytest.mark.integration
def test_async_list_positions_iterates_lazily() -> None:
    async def run() -> None:
        async with AsyncPublicClient() as client:
            paginator = client.list_positions(user=WALLET, page_size=5)
            count = 0
            async for page in paginator:
                assert all(isinstance(p, Position) for p in page.items)
                count += 1
                if count >= 2:
                    break

    asyncio.run(run())


@pytest.mark.integration
def test_async_list_trades_first_page() -> None:
    async def run() -> None:
        async with AsyncPublicClient() as client:
            page = await client.list_trades(user=WALLET, page_size=5).first_page()
        assert all(isinstance(t, Trade) for t in page.items)

    asyncio.run(run())


@pytest.mark.integration
def test_async_list_activity_first_page() -> None:
    async def run() -> None:
        async with AsyncPublicClient() as client:
            page = await client.list_activity(user=WALLET, page_size=5).first_page()
        assert isinstance(page.items, tuple)

    asyncio.run(run())


@pytest.mark.integration
def test_async_list_builder_leaderboard_first_page() -> None:
    async def run() -> None:
        async with AsyncPublicClient() as client:
            page = await client.list_builder_leaderboard(
                time_period="DAY", page_size=5
            ).first_page()
        assert len(page.items) > 0
        assert all(isinstance(entry, LeaderboardEntry) for entry in page.items)

    asyncio.run(run())


@pytest.mark.integration
def test_async_list_trader_leaderboard_first_page() -> None:
    async def run() -> None:
        async with AsyncPublicClient() as client:
            page = await client.list_trader_leaderboard(
                category="OVERALL", time_period="DAY", order_by="VOL", page_size=5
            ).first_page()
        assert len(page.items) > 0
        assert all(isinstance(entry, TraderLeaderboardEntry) for entry in page.items)

    asyncio.run(run())


@pytest.mark.integration
def test_async_list_market_positions_first_page() -> None:
    condition_ids = _condition_ids_for_event()
    if not condition_ids:
        pytest.skip("event has no condition IDs")

    async def run() -> None:
        async with AsyncPublicClient() as client:
            page = await client.list_market_positions(
                market=condition_ids[0], page_size=5
            ).first_page()
        assert all(isinstance(p, MetaMarketPosition) for p in page.items)

    asyncio.run(run())


@pytest.mark.integration
def test_async_list_closed_positions_first_page() -> None:
    async def run() -> None:
        async with AsyncPublicClient() as client:
            page = await client.list_closed_positions(user=WALLET, page_size=5).first_page()
        assert all(isinstance(p, ClosedPosition) for p in page.items)

    asyncio.run(run())
