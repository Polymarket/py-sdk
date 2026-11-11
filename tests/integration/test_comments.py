import asyncio

import pytest

from polymarket import AsyncPublicClient, Comment, PublicClient

COMMENT_ID = "1000"


@pytest.mark.integration
def test_get_comment_thread_returns_comments() -> None:
    with PublicClient() as client:
        comments = client.get_comment_thread(COMMENT_ID)

        assert comments
        assert all(isinstance(comment, Comment) for comment in comments)
        root = comments[0]
        assert root.user_address is not None
        assert root.user_address.startswith("0x")


@pytest.mark.integration
def test_async_get_comment_thread_returns_comments() -> None:
    async def run() -> None:
        async with AsyncPublicClient() as client:
            comments = await client.get_comment_thread(COMMENT_ID)

            assert comments
            assert all(isinstance(comment, Comment) for comment in comments)

    asyncio.run(run())


@pytest.mark.integration
def test_list_comments_continues_by_cursor_without_overlap(
    sync_public_client: PublicClient,
) -> None:
    events = sync_public_client.list_events(closed=False, page_size=20).first_page().items
    for event in events:
        paginator = sync_public_client.list_comments(
            parent_entity_id=str(event.id), parent_entity_type="Event", page_size=2
        )
        first = paginator.first_page()
        if first.next_cursor is None:
            continue
        # A thread that ends exactly on the page boundary returns an empty final page.
        second = paginator.from_cursor(first.next_cursor).first_page()
        if second.items:
            break
    else:
        pytest.skip("No open event with more than one page of comments")

    assert {comment.id for comment in first.items}.isdisjoint(c.id for c in second.items)
