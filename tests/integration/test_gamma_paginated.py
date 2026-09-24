import asyncio

import pytest

from polymarket import (
    AsyncPublicClient,
    Comment,
    Event,
    Market,
    PublicClient,
    SearchResults,
    Series,
    Tag,
    Team,
)


@pytest.mark.integration
def test_list_events_returns_paginator() -> None:
    with PublicClient() as client:
        paginator = client.list_events(closed=False, page_size=5)
        first = paginator.first_page()

        assert first.items
        assert all(isinstance(event, Event) for event in first.items)


@pytest.mark.integration
def test_list_events_keyset_iterates_multiple_pages() -> None:
    with PublicClient() as client:
        paginator = client.list_events(closed=False, page_size=5)
        pages: list[int] = []
        for page in paginator:
            pages.append(len(page.items))
            if len(pages) >= 2:
                break

        assert len(pages) == 2
        assert all(count > 0 for count in pages)


@pytest.mark.integration
def test_async_list_events_returns_paginator() -> None:
    async def run() -> None:
        async with AsyncPublicClient() as client:
            paginator = client.list_events(closed=False, page_size=5)
            first = await paginator.first_page()

            assert first.items
            assert all(isinstance(event, Event) for event in first.items)

    asyncio.run(run())


@pytest.mark.integration
def test_list_markets_returns_paginator() -> None:
    with PublicClient() as client:
        paginator = client.list_markets(closed=False, page_size=5)
        first = paginator.first_page()

        assert first.items
        assert all(isinstance(market, Market) for market in first.items)


@pytest.mark.integration
def test_list_closed_markets_omits_legacy_multi_outcome_markets() -> None:
    with PublicClient() as client:
        first = client.list_markets(closed=True, page_size=100).first_page()

        assert first.items
        assert all(isinstance(market, Market) for market in first.items)
        assert all(market.outcomes.yes.label and market.outcomes.no.label for market in first.items)


@pytest.mark.integration
def test_async_list_markets_returns_paginator() -> None:
    async def run() -> None:
        async with AsyncPublicClient() as client:
            paginator = client.list_markets(closed=False, page_size=5)
            first = await paginator.first_page()

            assert first.items
            assert all(isinstance(market, Market) for market in first.items)

    asyncio.run(run())


@pytest.mark.integration
def test_list_series_returns_paginator() -> None:
    with PublicClient() as client:
        paginator = client.list_series(page_size=5)
        first = paginator.first_page()

        assert first.items
        assert all(isinstance(series, Series) for series in first.items)


@pytest.mark.integration
def test_async_list_series_returns_paginator() -> None:
    async def run() -> None:
        async with AsyncPublicClient() as client:
            paginator = client.list_series(page_size=5)
            first = await paginator.first_page()

            assert first.items
            assert all(isinstance(series, Series) for series in first.items)

    asyncio.run(run())


@pytest.mark.integration
def test_list_tags_returns_paginator() -> None:
    with PublicClient() as client:
        paginator = client.list_tags(page_size=5)
        first = paginator.first_page()

        assert first.items
        assert all(isinstance(tag, Tag) for tag in first.items)


@pytest.mark.integration
def test_async_list_tags_returns_paginator() -> None:
    async def run() -> None:
        async with AsyncPublicClient() as client:
            paginator = client.list_tags(page_size=5)
            first = await paginator.first_page()

            assert first.items
            assert all(isinstance(tag, Tag) for tag in first.items)

    asyncio.run(run())


@pytest.mark.integration
def test_list_teams_returns_paginator() -> None:
    with PublicClient() as client:
        paginator = client.list_teams(page_size=5)
        first = paginator.first_page()

        assert first.items
        assert all(isinstance(team, Team) for team in first.items)


@pytest.mark.integration
def test_async_list_teams_returns_paginator() -> None:
    async def run() -> None:
        async with AsyncPublicClient() as client:
            paginator = client.list_teams(page_size=5)
            first = await paginator.first_page()

            assert first.items
            assert all(isinstance(team, Team) for team in first.items)

    asyncio.run(run())


@pytest.mark.integration
def test_list_comments_returns_paginator() -> None:
    with PublicClient() as client:
        paginator = client.list_comments(
            parent_entity_id="902661",
            parent_entity_type="Event",
            page_size=5,
        )
        first = paginator.first_page()

        assert all(isinstance(comment, Comment) for comment in first.items)


@pytest.mark.integration
def test_async_list_comments_returns_paginator() -> None:
    async def run() -> None:
        async with AsyncPublicClient() as client:
            paginator = client.list_comments(
                parent_entity_id="902661",
                parent_entity_type="Event",
                page_size=5,
            )
            first = await paginator.first_page()

            assert all(isinstance(comment, Comment) for comment in first.items)

    asyncio.run(run())


@pytest.mark.integration
def test_list_comments_by_user_address_returns_paginator() -> None:
    with PublicClient() as client:
        paginator = client.list_comments_by_user_address(
            address="0x16c9fb76d5e12c6e35738fd92223ea603004ffa7",
            page_size=5,
        )
        first = paginator.first_page()

        assert all(isinstance(comment, Comment) for comment in first.items)


@pytest.mark.integration
def test_async_list_comments_by_user_address_returns_paginator() -> None:
    async def run() -> None:
        async with AsyncPublicClient() as client:
            paginator = client.list_comments_by_user_address(
                address="0x16c9fb76d5e12c6e35738fd92223ea603004ffa7",
                page_size=5,
            )
            first = await paginator.first_page()

            assert all(isinstance(comment, Comment) for comment in first.items)

    asyncio.run(run())


@pytest.mark.integration
def test_search_returns_search_results() -> None:
    with PublicClient() as client:
        first_page = client.search(q="election").first_page()
        bundle = first_page.items[0]

        assert isinstance(bundle, SearchResults)
        assert bundle.events or bundle.tags or bundle.profiles


@pytest.mark.integration
def test_async_search_returns_search_results() -> None:
    async def run() -> None:
        async with AsyncPublicClient() as client:
            first_page = await client.search(q="election").first_page()
            bundle = first_page.items[0]

            assert isinstance(bundle, SearchResults)
            assert bundle.events or bundle.tags or bundle.profiles

    asyncio.run(run())


@pytest.mark.integration
def test_search_cursor_advances_to_next_page() -> None:
    with PublicClient() as client:
        paginator = client.search(q="election", page_size=2)
        page_one = paginator.first_page()

        if not page_one.has_more:
            pytest.skip("search returned only one page; cannot verify cursor advance")

        assert page_one.next_cursor is not None
        page_two = paginator.from_cursor(page_one.next_cursor).first_page()

        bundle_one = page_one.items[0]
        bundle_two = page_two.items[0]
        assert isinstance(bundle_two, SearchResults)
        page_one_ids = {event.id for event in bundle_one.events}
        page_two_ids = {event.id for event in bundle_two.events}
        assert page_one_ids != page_two_ids or not bundle_one.events


def _root_created_at(page_items: tuple[Comment, ...]) -> list[float]:
    return [
        comment.created_at.timestamp()
        for comment in page_items
        if comment.parent_comment_id is None and comment.created_at is not None
    ]


@pytest.mark.integration
def test_list_comments_continues_a_long_thread_by_server_cursor() -> None:
    # A long-running thread; each page carries `page_size` top-level comments
    # plus their replies, so assertions are on the top-level comments only.
    with PublicClient() as client:
        paginator = client.list_comments(
            parent_entity_id="45915", parent_entity_type="Event", page_size=5
        )
        first = paginator.first_page()
        second = paginator.from_cursor(first.next_cursor).first_page()

        assert first.has_more is True
        assert first.next_cursor and first.next_cursor != second.next_cursor
        assert all(isinstance(comment, Comment) for comment in (*first.items, *second.items))

        first_roots = {c.id for c in first.items if c.parent_comment_id is None}
        second_roots = {c.id for c in second.items if c.parent_comment_id is None}
        assert len(first_roots) == 5
        assert first_roots.isdisjoint(second_roots)

        created_at = _root_created_at(first.items) + _root_created_at(second.items)
        assert created_at == sorted(created_at, reverse=True)


@pytest.mark.integration
def test_async_list_comments_continues_a_long_thread_by_server_cursor() -> None:
    async def run() -> None:
        async with AsyncPublicClient() as client:
            paginator = client.list_comments(
                parent_entity_id="45915", parent_entity_type="Event", page_size=5
            )
            first = await paginator.first_page()
            second = await paginator.from_cursor(first.next_cursor).first_page()

            first_roots = {c.id for c in first.items if c.parent_comment_id is None}
            second_roots = {c.id for c in second.items if c.parent_comment_id is None}
            assert first.has_more is True
            assert first_roots.isdisjoint(second_roots)

    asyncio.run(run())
