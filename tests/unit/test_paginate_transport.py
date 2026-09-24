# pyright: reportPrivateUsage=false
import asyncio
import dataclasses
import typing
from collections.abc import Mapping
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from polymarket._internal.dispatch import (
    async_paginate_offset,
    async_paginate_page_based,
    sync_paginate_offset,
    sync_paginate_page_based,
)
from polymarket._internal.pagination import (
    decode_keyset_cursor,
    decode_offset_cursor,
    decode_page_cursor,
    encode_keyset_cursor,
    encode_offset_cursor,
)
from polymarket._internal.request import (
    OffsetPaginatedSpec,
    PageBasedPagePayload,
    PageBasedSpec,
    QueryParamValue,
)
from polymarket.clients._transport import AsyncTransport, SyncTransport
from polymarket.clients.async_public import AsyncPublicClient
from polymarket.clients.public import PublicClient
from polymarket.errors import PaginationLimitError, UserInputError
from polymarket.models import Comment
from polymarket.pagination import Page


def _items_handler(captured: list[httpx.Request], rows: list[list[int]]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        offset = int(parse_qs(urlparse(str(request.url)).query)["offset"][0])
        empty: list[int] = []
        page = next((row for row in rows if row and row[0] == offset), empty)
        return httpx.Response(200, json=page, request=request)

    return httpx.MockTransport(handler)


def _spec(
    path: str = "/positions",
    base_params: dict[str, str] | None = None,
    max_page_size: int | None = None,
    max_offset: int | None = None,
):
    return OffsetPaginatedSpec[int](
        service="data",
        path=path,
        parse_items=lambda payload: tuple(payload),  # type: ignore[arg-type]
        base_params=base_params,
        max_page_size=max_page_size,
        max_offset=max_offset,
    )


def _full_pages_handler(captured: list[httpx.Request], page_size: int) -> httpx.MockTransport:
    # Every offset answers a full page, standing in for a listing deeper than
    # the client is allowed to page.
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        offset = int(parse_qs(urlparse(str(request.url)).query)["offset"][0])
        return httpx.Response(200, json=list(range(offset, offset + page_size)), request=request)

    return httpx.MockTransport(handler)


def _offsets(captured: list[httpx.Request]) -> list[int]:
    return [int(parse_qs(urlparse(str(r.url)).query)["offset"][0]) for r in captured]


def _install_sync_data_transport(client: PublicClient, handler: httpx.MockTransport) -> None:
    new_transport = SyncTransport(
        base_url="https://example.test",
        client=httpx.Client(base_url="https://example.test", transport=handler),
    )
    client._ctx = dataclasses.replace(client._ctx, data=new_transport)


def _install_async_data_transport(client: AsyncPublicClient, handler: httpx.MockTransport) -> None:
    new_transport = AsyncTransport(
        base_url="https://example.test",
        client=httpx.AsyncClient(base_url="https://example.test", transport=handler),
    )
    client._ctx = dataclasses.replace(client._ctx, data=new_transport)


def _install_sync_gamma_transport(client: PublicClient, handler: httpx.MockTransport) -> None:
    new_transport = SyncTransport(
        base_url="https://example.test",
        client=httpx.Client(base_url="https://example.test", transport=handler),
    )
    client._ctx = dataclasses.replace(client._ctx, gamma=new_transport)


def _install_async_gamma_transport(client: AsyncPublicClient, handler: httpx.MockTransport) -> None:
    new_transport = AsyncTransport(
        base_url="https://example.test",
        client=httpx.AsyncClient(base_url="https://example.test", transport=handler),
    )
    client._ctx = dataclasses.replace(client._ctx, gamma=new_transport)


def _page_handler(
    captured: list[httpx.Request],
    pages: dict[int, tuple[list[int], bool]],
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        page = int(parse_qs(urlparse(str(request.url)).query)["page"][0])
        items, has_more = pages.get(page, ([], False))
        return httpx.Response(
            200,
            json={"items": items, "pagination": {"hasMore": has_more, "totalResults": 42}},
            request=request,
        )

    return httpx.MockTransport(handler)


def _page_spec(
    path: str = "/public-search",
    base_params: dict[str, str] | None = None,
) -> PageBasedSpec[tuple[int, ...]]:
    def parse_page(data: object) -> PageBasedPagePayload[tuple[int, ...]]:
        assert isinstance(data, dict)
        body = typing.cast(dict[str, typing.Any], data)
        pagination = typing.cast(dict[str, typing.Any], body["pagination"])
        return PageBasedPagePayload(
            items=tuple(typing.cast(list[int], body["items"])),
            has_more=bool(pagination["hasMore"]),
            total_count=int(pagination["totalResults"]),
        )

    return PageBasedSpec[tuple[int, ...]](
        service="gamma",
        path=path,
        parse_page=parse_page,
        base_params=base_params,
    )


def test_sync_paginate_offset_sends_limit_and_offset() -> None:
    captured: list[httpx.Request] = []
    handler = _items_handler(captured, [list(range(0, 10))])
    with PublicClient() as client:
        _install_sync_data_transport(client, handler)
        page = sync_paginate_offset(
            client._ctx, _spec(base_params={"user": "0xA"}), page_size=10
        ).first_page()

    assert len(captured) == 1
    qs = parse_qs(urlparse(str(captured[0].url)).query)
    assert qs["limit"] == ["10"]
    assert qs["offset"] == ["0"]
    assert qs["user"] == ["0xA"]
    assert page.items == tuple(range(10))
    assert page.has_more is True
    assert page.next_cursor is not None


def test_sync_paginate_offset_rejects_page_size_above_spec_max() -> None:
    with (
        PublicClient() as client,
        pytest.raises(UserInputError, match="page_size must be at most 49"),
    ):
        sync_paginate_offset(client._ctx, _spec(max_page_size=49), page_size=50)


def test_async_paginate_offset_rejects_page_size_above_spec_max() -> None:
    async def run() -> None:
        async with AsyncPublicClient() as client:
            with pytest.raises(UserInputError, match="page_size must be at most 49"):
                async_paginate_offset(client._ctx, _spec(max_page_size=49), page_size=50)

    asyncio.run(run())


def test_sync_paginate_offset_continues_past_full_page() -> None:
    # A full page means another page may exist, so pagination continues to the
    # next offset and terminates on the empty page. This also protects against
    # servers that clamp the limit instead of erroring.
    captured: list[httpx.Request] = []
    handler = _items_handler(captured, [list(range(0, 10)), list(range(10, 20))])
    with PublicClient() as client:
        _install_sync_data_transport(client, handler)
        paginator = sync_paginate_offset(client._ctx, _spec(), page_size=10)
        items = [item for page in paginator for item in page.items]

    assert items == list(range(20))
    offsets = [parse_qs(urlparse(str(request.url)).query)["offset"][0] for request in captured]
    assert offsets == ["0", "10", "20"]


def test_sync_paginate_offset_no_more_when_partial() -> None:
    captured: list[httpx.Request] = []
    handler = _items_handler(captured, [list(range(3))])
    with PublicClient() as client:
        _install_sync_data_transport(client, handler)
        page = sync_paginate_offset(client._ctx, _spec(), page_size=10).first_page()

    assert page.items == (0, 1, 2)
    assert page.has_more is False
    assert page.next_cursor is None


def test_sync_paginate_offset_round_trip_next_cursor() -> None:
    captured: list[httpx.Request] = []
    handler = _items_handler(
        captured,
        [list(range(0, 10)), list(range(10, 13))],
    )
    with PublicClient() as client:
        _install_sync_data_transport(client, handler)
        spec = _spec(base_params={"user": "0xA"})
        paginator = sync_paginate_offset(client._ctx, spec, page_size=10)
        all_items = list(paginator.iter_items())

    assert all_items == list(range(13))
    assert len(captured) == 2
    qs1 = parse_qs(urlparse(str(captured[1].url)).query)
    assert qs1["offset"] == ["10"]
    assert qs1["limit"] == ["10"]


def test_sync_paginate_offset_cursor_rejects_different_endpoint() -> None:
    captured: list[httpx.Request] = []
    handler = _items_handler(captured, [list(range(10))])
    with PublicClient() as client:
        _install_sync_data_transport(client, handler)
        paginator = sync_paginate_offset(client._ctx, _spec(path="/positions"), page_size=10)
        first = paginator.first_page()
        assert first.next_cursor is not None
        other_spec_paginator = sync_paginate_offset(
            client._ctx, _spec(path="/trades"), page_size=10
        )
        with pytest.raises(UserInputError, match="does not belong"):
            other_spec_paginator.from_cursor(first.next_cursor).first_page()


def test_sync_paginate_offset_cursor_rejects_different_query() -> None:
    captured: list[httpx.Request] = []
    handler = _items_handler(captured, [list(range(10))])
    with PublicClient() as client:
        _install_sync_data_transport(client, handler)
        a_paginator = sync_paginate_offset(
            client._ctx, _spec(base_params={"user": "0xA"}), page_size=10
        )
        first = a_paginator.first_page()
        assert first.next_cursor is not None
        b_paginator = sync_paginate_offset(
            client._ctx, _spec(base_params={"user": "0xB"}), page_size=10
        )
        with pytest.raises(UserInputError, match="different query parameters"):
            b_paginator.from_cursor(first.next_cursor).first_page()


def test_sync_paginate_offset_next_cursor_decodes_to_expected_offset() -> None:
    captured: list[httpx.Request] = []
    handler = _items_handler(captured, [list(range(10))])
    with PublicClient() as client:
        _install_sync_data_transport(client, handler)
        spec = _spec(base_params={"user": "0xA"})
        page = sync_paginate_offset(client._ctx, spec, page_size=10).first_page()

    assert page.next_cursor is not None
    assert decode_offset_cursor(
        page.next_cursor,
        expected_service="data",
        expected_path="/positions",
        expected_base_params={"user": "0xA"},
    ) == (10, 10)


def test_async_paginate_offset_sends_limit_and_offset() -> None:
    async def run() -> None:
        captured: list[httpx.Request] = []
        handler = _items_handler(captured, [list(range(0, 10))])
        async with AsyncPublicClient() as client:
            _install_async_data_transport(client, handler)
            page = await async_paginate_offset(
                client._ctx, _spec(base_params={"user": "0xA"}), page_size=10
            ).first_page()

        assert len(captured) == 1
        qs = parse_qs(urlparse(str(captured[0].url)).query)
        assert qs["limit"] == ["10"]
        assert qs["offset"] == ["0"]
        assert qs["user"] == ["0xA"]
        assert page.items == tuple(range(10))
        assert page.has_more is True

    asyncio.run(run())


def test_async_paginate_offset_round_trip_next_cursor() -> None:
    async def run() -> None:
        captured: list[httpx.Request] = []
        handler = _items_handler(
            captured,
            [list(range(0, 10)), list(range(10, 13))],
        )
        async with AsyncPublicClient() as client:
            _install_async_data_transport(client, handler)
            paginator = async_paginate_offset(client._ctx, _spec(), page_size=10)
            collected: list[int] = []
            async for page in paginator:
                collected.extend(page.items)

        assert collected == list(range(13))
        assert len(captured) == 2
        qs1 = parse_qs(urlparse(str(captured[1].url)).query)
        assert qs1["offset"] == ["10"]
        assert qs1["limit"] == ["10"]

    asyncio.run(run())


def test_async_paginate_offset_cursor_rejects_different_endpoint() -> None:
    async def run() -> None:
        captured: list[httpx.Request] = []
        handler = _items_handler(captured, [list(range(10))])
        async with AsyncPublicClient() as client:
            _install_async_data_transport(client, handler)
            paginator = async_paginate_offset(client._ctx, _spec(path="/positions"), page_size=10)
            first = await paginator.first_page()
            assert first.next_cursor is not None
            other = async_paginate_offset(client._ctx, _spec(path="/trades"), page_size=10)
            with pytest.raises(UserInputError, match="does not belong"):
                await other.from_cursor(first.next_cursor).first_page()

    asyncio.run(run())


def test_async_paginate_offset_cursor_rejects_different_query() -> None:
    async def run() -> None:
        captured: list[httpx.Request] = []
        handler = _items_handler(captured, [list(range(10))])
        async with AsyncPublicClient() as client:
            _install_async_data_transport(client, handler)
            a_paginator = async_paginate_offset(
                client._ctx, _spec(base_params={"user": "0xA"}), page_size=10
            )
            first = await a_paginator.first_page()
            assert first.next_cursor is not None
            b_paginator = async_paginate_offset(
                client._ctx, _spec(base_params={"user": "0xB"}), page_size=10
            )
            with pytest.raises(UserInputError, match="different query parameters"):
                await b_paginator.from_cursor(first.next_cursor).first_page()

    asyncio.run(run())


def test_sync_paginate_page_based_sends_page_and_limit_per_type() -> None:
    captured: list[httpx.Request] = []
    handler = _page_handler(captured, {1: ([1, 2, 3], True)})
    with PublicClient() as client:
        _install_sync_gamma_transport(client, handler)
        page = sync_paginate_page_based(
            client._ctx, _page_spec(base_params={"q": "x"}), page_size=10
        ).first_page()

    assert len(captured) == 1
    qs = parse_qs(urlparse(str(captured[0].url)).query)
    assert qs["page"] == ["1"]
    assert qs["limit_per_type"] == ["10"]
    assert qs["q"] == ["x"]
    assert page.items == ((1, 2, 3),)
    assert page.has_more is True
    assert page.total_count == 42
    assert page.next_cursor is not None


def test_sync_paginate_page_based_terminal_page_has_no_cursor() -> None:
    captured: list[httpx.Request] = []
    handler = _page_handler(captured, {1: ([1, 2], False)})
    with PublicClient() as client:
        _install_sync_gamma_transport(client, handler)
        page = sync_paginate_page_based(client._ctx, _page_spec(), page_size=10).first_page()

    assert page.has_more is False
    assert page.next_cursor is None


def test_sync_paginate_page_based_round_trip_next_cursor() -> None:
    captured: list[httpx.Request] = []
    handler = _page_handler(
        captured,
        {1: ([1, 2], True), 2: ([3, 4], False)},
    )
    with PublicClient() as client:
        _install_sync_gamma_transport(client, handler)
        paginator = sync_paginate_page_based(
            client._ctx, _page_spec(base_params={"q": "x"}), page_size=10
        )
        collected: list[tuple[int, ...]] = []
        for page in paginator:
            collected.extend(page.items)

    assert collected == [(1, 2), (3, 4)]
    assert len(captured) == 2
    qs2 = parse_qs(urlparse(str(captured[1].url)).query)
    assert qs2["page"] == ["2"]


def test_sync_paginate_page_based_next_cursor_decodes_to_next_page() -> None:
    captured: list[httpx.Request] = []
    handler = _page_handler(captured, {1: ([1], True)})
    with PublicClient() as client:
        _install_sync_gamma_transport(client, handler)
        spec = _page_spec(base_params={"q": "x"})
        page = sync_paginate_page_based(client._ctx, spec, page_size=10).first_page()

    assert page.next_cursor is not None
    assert decode_page_cursor(
        page.next_cursor,
        expected_service="gamma",
        expected_path="/public-search",
        expected_base_params={"q": "x"},
    ) == (2, 10)


def test_sync_paginate_page_based_cursor_rejects_different_endpoint() -> None:
    captured: list[httpx.Request] = []
    handler = _page_handler(captured, {1: ([1], True)})
    with PublicClient() as client:
        _install_sync_gamma_transport(client, handler)
        a = sync_paginate_page_based(client._ctx, _page_spec(path="/public-search"), page_size=10)
        first = a.first_page()
        assert first.next_cursor is not None
        b = sync_paginate_page_based(client._ctx, _page_spec(path="/other"), page_size=10)
        with pytest.raises(UserInputError, match="does not belong"):
            b.from_cursor(first.next_cursor).first_page()


def test_async_paginate_page_based_round_trip_next_cursor() -> None:
    async def run() -> None:
        captured: list[httpx.Request] = []
        handler = _page_handler(
            captured,
            {1: ([1, 2], True), 2: ([3], False)},
        )
        async with AsyncPublicClient() as client:
            _install_async_gamma_transport(client, handler)
            paginator = async_paginate_page_based(client._ctx, _page_spec(), page_size=10)
            collected: list[tuple[int, ...]] = []
            async for page in paginator:
                collected.extend(page.items)

        assert collected == [(1, 2), (3,)]
        assert len(captured) == 2
        qs2 = parse_qs(urlparse(str(captured[1].url)).query)
        assert qs2["page"] == ["2"]

    asyncio.run(run())


def test_sync_paginate_offset_serves_the_page_at_the_cap_then_raises() -> None:
    # The cap is on the starting offset: offset 200 is served, the cursor it
    # mints is minted normally, and following it raises before any request.
    captured: list[httpx.Request] = []
    handler = _full_pages_handler(captured, 100)
    with PublicClient() as client:
        _install_sync_data_transport(client, handler)
        paginator = sync_paginate_offset(client._ctx, _spec(max_offset=200), page_size=100)
        pages: list[Page[int]] = []
        with pytest.raises(PaginationLimitError, match="deepest page served for /positions"):
            for page in paginator:
                pages.append(page)

    assert _offsets(captured) == [0, 100, 200]
    assert len(pages) == 3
    assert pages[-1].has_more is True
    assert pages[-1].next_cursor is not None
    assert pages[-1].items == tuple(range(200, 300))


def test_sync_paginate_offset_default_page_size_stops_after_offset_200() -> None:
    captured: list[httpx.Request] = []
    handler = _full_pages_handler(captured, 20)
    with PublicClient() as client:
        _install_sync_data_transport(client, handler)
        paginator = sync_paginate_offset(client._ctx, _spec(max_offset=200), page_size=20)
        with pytest.raises(PaginationLimitError):
            for _ in paginator:
                pass

    assert _offsets(captured) == list(range(0, 201, 20))


def test_sync_paginate_offset_never_clamps_a_non_divisor_page_size() -> None:
    # 0 -> 75 -> 150 -> 225: the next offset past the cap is refused, not
    # pulled back to 200, which would re-read 25 rows.
    captured: list[httpx.Request] = []
    handler = _full_pages_handler(captured, 75)
    with PublicClient() as client:
        _install_sync_data_transport(client, handler)
        paginator = sync_paginate_offset(client._ctx, _spec(max_offset=200), page_size=75)
        with pytest.raises(PaginationLimitError):
            for _ in paginator:
                pass

    assert _offsets(captured) == [0, 75, 150]


def test_sync_paginate_offset_short_page_at_the_cap_finishes_normally() -> None:
    captured: list[httpx.Request] = []
    handler = _items_handler(captured, [list(range(200, 203))])
    with PublicClient() as client:
        _install_sync_data_transport(client, handler)
        cursor = encode_offset_cursor(
            service="data", path="/positions", base_params=None, offset=200, page_size=100
        )
        page = (
            sync_paginate_offset(client._ctx, _spec(max_offset=200), page_size=100)
            .from_cursor(cursor)
            .first_page()
        )

    assert _offsets(captured) == [200]
    assert page.items == (200, 201, 202)
    assert page.has_more is False
    assert page.next_cursor is None


def test_sync_paginate_offset_rejects_a_saved_cursor_past_the_cap_before_any_request() -> None:
    captured: list[httpx.Request] = []
    handler = _full_pages_handler(captured, 20)
    with PublicClient() as client:
        _install_sync_data_transport(client, handler)
        cursor = encode_offset_cursor(
            service="data", path="/positions", base_params=None, offset=201, page_size=20
        )
        paginator = sync_paginate_offset(client._ctx, _spec(max_offset=200), page_size=20)
        with pytest.raises(PaginationLimitError):
            paginator.from_cursor(cursor).first_page()

    assert captured == []


def test_sync_paginate_offset_rejects_a_saved_cursor_with_an_oversized_page_size() -> None:
    captured: list[httpx.Request] = []
    handler = _full_pages_handler(captured, 20)
    with PublicClient() as client:
        _install_sync_data_transport(client, handler)
        cursor = encode_offset_cursor(
            service="data", path="/positions", base_params=None, offset=0, page_size=101
        )
        paginator = sync_paginate_offset(client._ctx, _spec(max_page_size=100), page_size=20)
        with pytest.raises(UserInputError, match="page_size must be at most 100"):
            paginator.from_cursor(cursor).first_page()

    assert captured == []


def test_sync_paginate_offset_without_a_cap_keeps_walking() -> None:
    captured: list[httpx.Request] = []
    handler = _items_handler(captured, [list(range(o, o + 20)) for o in range(0, 300, 20)])
    with PublicClient() as client:
        _install_sync_data_transport(client, handler)
        items = list(sync_paginate_offset(client._ctx, _spec(), page_size=20).iter_items())

    assert len(items) == 300
    assert _offsets(captured)[-1] == 300


def test_async_paginate_offset_serves_the_page_at_the_cap_then_raises() -> None:
    async def run() -> None:
        captured: list[httpx.Request] = []
        handler = _full_pages_handler(captured, 100)
        async with AsyncPublicClient() as client:
            _install_async_data_transport(client, handler)
            paginator = async_paginate_offset(client._ctx, _spec(max_offset=200), page_size=100)
            pages: list[Page[int]] = []
            with pytest.raises(PaginationLimitError):
                async for page in paginator:
                    pages.append(page)

        assert _offsets(captured) == [0, 100, 200]
        assert len(pages) == 3
        assert pages[-1].has_more is True

    asyncio.run(run())


def test_async_paginate_offset_rejects_a_saved_cursor_past_the_cap_before_any_request() -> None:
    async def run() -> None:
        captured: list[httpx.Request] = []
        handler = _full_pages_handler(captured, 20)
        async with AsyncPublicClient() as client:
            _install_async_data_transport(client, handler)
            cursor = encode_offset_cursor(
                service="data", path="/positions", base_params=None, offset=220, page_size=20
            )
            paginator = async_paginate_offset(client._ctx, _spec(max_offset=200), page_size=20)
            with pytest.raises(PaginationLimitError):
                await paginator.from_cursor(cursor).first_page()

        assert captured == []

    asyncio.run(run())


def _comments_handler(
    captured: list[httpx.Request], roots_per_page: int, replies_per_root: int
) -> httpx.MockTransport:
    # Each root comment is followed by its replies, the shape the comments
    # listing returns; the server's limit bounds the roots only.
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        qs = parse_qs(urlparse(str(request.url)).query)
        offset = int(qs["offset"][0])
        rows: list[dict[str, str]] = []
        for i in range(roots_per_page):
            root_id = str(offset + i + 1)
            rows.append({"id": root_id, "body": "root"})
            for j in range(replies_per_root):
                rows.append({"id": f"{root_id}-{j}", "body": "reply", "parentCommentID": root_id})
        return httpx.Response(200, json=rows, request=request)

    return httpx.MockTransport(handler)


def test_list_comments_walks_to_the_cap_and_raises_on_the_next_page() -> None:
    # Holder filtering is served on offset pages only, so this read cannot
    # switch to server cursors and the offset cap still applies.
    captured: list[httpx.Request] = []
    with PublicClient() as client:
        _install_sync_gamma_transport(client, _comments_handler(captured, 20, 2))
        paginator = client.list_comments(
            parent_entity_id="1", parent_entity_type="Event", holders_only=True
        )
        pages: list[Page[Comment]] = []
        with pytest.raises(PaginationLimitError, match="/comments"):
            for page in paginator:
                pages.append(page)

    assert _offsets(captured) == list(range(0, 201, 20))
    assert len(pages) == 11
    assert all(len(page.items) == 60 for page in pages)
    assert pages[-1].has_more is True


def test_list_comments_short_root_page_with_many_replies_finishes() -> None:
    # 8 roots with 4 replies each is 40 rows for a page size of 20, but only 8
    # roots were served, so the listing is exhausted and no cap error fires.
    captured: list[httpx.Request] = []
    with PublicClient() as client:
        _install_sync_gamma_transport(client, _comments_handler(captured, 8, 4))
        cursor = encode_offset_cursor(
            service="gamma",
            path="/comments",
            base_params={"parent_entity_id": "1", "parent_entity_type": "Event"},
            offset=200,
            page_size=20,
        )
        page = (
            client.list_comments(parent_entity_id="1", parent_entity_type="Event")
            .from_cursor(cursor)
            .first_page()
        )

    assert _offsets(captured) == [200]
    assert len(page.items) == 40
    assert page.has_more is False
    assert page.next_cursor is None


def test_list_comments_by_user_address_counts_every_row_and_stops_at_the_cap() -> None:
    captured: list[httpx.Request] = []
    with PublicClient() as client:
        _install_sync_gamma_transport(client, _comments_handler(captured, 10, 1))
        paginator = client.list_comments_by_user_address(address="0x" + "a" * 40)
        with pytest.raises(PaginationLimitError, match="/comments/user_address/"):
            for _ in paginator:
                pass

    assert _offsets(captured) == list(range(0, 201, 20))


def test_list_comments_to_pandas_without_a_limit_raises_at_the_cap() -> None:
    captured: list[httpx.Request] = []
    with PublicClient() as client:
        _install_sync_gamma_transport(client, _comments_handler(captured, 100, 0))
        paginator = client.list_comments(
            parent_entity_id="1",
            parent_entity_type="Event",
            holders_only=True,
            page_size=100,
        )
        with pytest.raises(PaginationLimitError):
            paginator.to_pandas(limit=None)

    assert _offsets(captured) == [0, 100, 200]


_COMMENTS_KEYSET_DEFAULTS: dict[str, QueryParamValue] = {
    "parent_entity_id": "1",
    "parent_entity_type": "Event",
    "order": "createdAt",
    "ascending": False,
}


def _keyset_comments_handler(
    captured: list[httpx.Request],
    pages: dict[str | None, tuple[list[dict[str, str]], str | None]],
) -> httpx.MockTransport:
    # Pages are keyed by the `after_cursor` they answer to; the terminal page
    # omits `next_cursor`, as the service does.
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        assert urlparse(str(request.url)).path == "/comments/keyset"
        qs = parse_qs(urlparse(str(request.url)).query)
        after = qs.get("after_cursor", [None])[0]
        rows, next_cursor = pages[after]
        body: dict[str, object] = {"$schema": "x", "comments": rows}
        if next_cursor is not None:
            body["next_cursor"] = next_cursor
        return httpx.Response(200, json=body, request=request)

    return httpx.MockTransport(handler)


_TWO_KEYSET_PAGES: dict[str | None, tuple[list[dict[str, str]], str | None]] = {
    None: ([{"id": "3", "body": "newest"}, {"id": "2", "body": "older"}], "tok1"),
    "tok1": ([{"id": "1", "body": "oldest"}], None),
}


def _query(request: httpx.Request) -> dict[str, list[str]]:
    return parse_qs(urlparse(str(request.url)).query, keep_blank_values=True)


def _server_cursor(cursor: str | None, base_params: Mapping[str, QueryParamValue]) -> str:
    assert cursor is not None
    return decode_keyset_cursor(
        cursor,
        expected_service="gamma",
        expected_path="/comments/keyset",
        expected_base_params=base_params,
    )


def test_list_comments_walks_by_server_cursor_with_pinned_defaults() -> None:
    captured: list[httpx.Request] = []
    with PublicClient() as client:
        _install_sync_gamma_transport(client, _keyset_comments_handler(captured, _TWO_KEYSET_PAGES))
        pages = list(client.list_comments(parent_entity_id="1", parent_entity_type="Event"))

    assert len(captured) == 2
    first = _query(captured[0])
    assert first == {
        "parent_entity_id": ["1"],
        "parent_entity_type": ["Event"],
        "order": ["createdAt"],
        "ascending": ["false"],
        "limit": ["20"],
    }
    assert _query(captured[1])["after_cursor"] == ["tok1"]
    assert "offset" not in _query(captured[1])

    assert len(pages) == 2
    assert pages[0].has_more is True
    assert _server_cursor(pages[0].next_cursor, _COMMENTS_KEYSET_DEFAULTS) == "tok1"
    assert pages[1].has_more is False
    assert pages[1].next_cursor is None
    assert [comment.id for page in pages for comment in page.items] == ["3", "2", "1"]


def test_list_comments_re_encodes_the_new_server_cursor_on_every_page() -> None:
    captured: list[httpx.Request] = []
    pages: dict[str | None, tuple[list[dict[str, str]], str | None]] = {
        None: ([{"id": "3"}], "tok1"),
        "tok1": ([{"id": "2"}], "tok2"),
        "tok2": ([{"id": "1"}], None),
    }
    with PublicClient() as client:
        _install_sync_gamma_transport(client, _keyset_comments_handler(captured, pages))
        walked = list(client.list_comments(parent_entity_id="1", parent_entity_type="Event"))

    assert _server_cursor(walked[0].next_cursor, _COMMENTS_KEYSET_DEFAULTS) == "tok1"
    assert _server_cursor(walked[1].next_cursor, _COMMENTS_KEYSET_DEFAULTS) == "tok2"
    assert [_query(r).get("after_cursor", [None])[0] for r in captured] == [None, "tok1", "tok2"]


@pytest.mark.parametrize(
    ("kwargs", "expected_order", "expected_ascending"),
    [
        ({"order": "id"}, "id", "true"),
        ({"order": "createdAt", "ascending": False}, "createdAt", "false"),
        ({"ascending": True}, "createdAt", "false"),
    ],
)
def test_list_comments_sends_the_direction_rule(
    kwargs: dict[str, object], expected_order: str, expected_ascending: str
) -> None:
    captured: list[httpx.Request] = []
    with PublicClient() as client:
        _install_sync_gamma_transport(client, _keyset_comments_handler(captured, _TWO_KEYSET_PAGES))
        client.list_comments(
            parent_entity_id="1",
            parent_entity_type="Event",
            **kwargs,  # type: ignore[arg-type]
        ).first_page()

    qs = _query(captured[0])
    assert qs["order"] == [expected_order]
    assert qs["ascending"] == [expected_ascending]


def test_list_comments_cursor_continues_the_same_query_under_equivalent_arguments() -> None:
    captured: list[httpx.Request] = []
    with PublicClient() as client:
        _install_sync_gamma_transport(client, _keyset_comments_handler(captured, _TWO_KEYSET_PAGES))
        first = client.list_comments(parent_entity_id="1", parent_entity_type="Event").first_page()

        for kwargs in ({"order": "createdAt", "ascending": False}, {"ascending": True}):
            page = (
                client.list_comments(
                    parent_entity_id="1",
                    parent_entity_type="Event",
                    **kwargs,  # type: ignore[arg-type]
                )
                .from_cursor(first.next_cursor)
                .first_page()
            )
            assert [comment.id for comment in page.items] == ["1"]

    assert [_query(r).get("after_cursor", [None])[0] for r in captured] == [None, "tok1", "tok1"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"order": "id"},
        {"order": "createdAt", "ascending": True},
        {"parent_entity_id": "2"},
        {"parent_entity_type": "Series"},
    ],
)
def test_list_comments_cursor_refuses_a_different_query_before_any_request(
    kwargs: dict[str, object],
) -> None:
    captured: list[httpx.Request] = []
    with PublicClient() as client:
        _install_sync_gamma_transport(client, _keyset_comments_handler(captured, _TWO_KEYSET_PAGES))
        first = client.list_comments(parent_entity_id="1", parent_entity_type="Event").first_page()
        del captured[:]

        request_kwargs: dict[str, object] = {"parent_entity_id": "1", "parent_entity_type": "Event"}
        request_kwargs.update(kwargs)
        paginator = client.list_comments(**request_kwargs)  # type: ignore[arg-type]
        with pytest.raises(UserInputError, match="different query parameters"):
            paginator.from_cursor(first.next_cursor).first_page()

    assert captured == []


def test_list_comments_cursor_refuses_a_read_served_on_offset_pages() -> None:
    captured: list[httpx.Request] = []
    with PublicClient() as client:
        _install_sync_gamma_transport(client, _keyset_comments_handler(captured, _TWO_KEYSET_PAGES))
        first = client.list_comments(parent_entity_id="1", parent_entity_type="Event").first_page()
        del captured[:]

        paginator = client.list_comments(
            parent_entity_id="1", parent_entity_type="Event", holders_only=True
        )
        with pytest.raises(UserInputError, match="does not belong to this endpoint"):
            paginator.from_cursor(first.next_cursor).first_page()

    assert captured == []


def test_list_comments_resumes_a_saved_offset_cursor_on_offset_pages() -> None:
    # A cursor minted before cursor pagination existed finishes its walk on
    # offset pages, where the offset cap still applies.
    captured: list[httpx.Request] = []
    with PublicClient() as client:
        _install_sync_gamma_transport(client, _comments_handler(captured, 20, 2))
        legacy = encode_offset_cursor(
            service="gamma",
            path="/comments",
            base_params={"parent_entity_id": "1", "parent_entity_type": "Event"},
            offset=180,
            page_size=20,
        )
        paginator = client.list_comments(parent_entity_id="1", parent_entity_type="Event")
        pages: list[Page[Comment]] = []
        with pytest.raises(PaginationLimitError):
            for page in paginator.from_cursor(legacy):
                pages.append(page)

    assert _offsets(captured) == [180, 200]
    assert all("after_cursor" not in _query(r) for r in captured)
    assert len(pages) == 2
    assert pages[0].next_cursor is not None
    assert decode_offset_cursor(
        pages[0].next_cursor,
        expected_service="gamma",
        expected_path="/comments",
        expected_base_params={"parent_entity_id": "1", "parent_entity_type": "Event"},
    ) == (200, 20)


@pytest.mark.parametrize(
    ("offset", "page_size", "error", "match"),
    [
        (220, 20, PaginationLimitError, "deepest page served"),
        (0, 101, UserInputError, "at most 100"),
    ],
)
def test_list_comments_refuses_a_saved_offset_cursor_outside_the_window(
    offset: int, page_size: int, error: type[Exception], match: str
) -> None:
    captured: list[httpx.Request] = []
    with PublicClient() as client:
        _install_sync_gamma_transport(client, _comments_handler(captured, 20, 2))
        legacy = encode_offset_cursor(
            service="gamma",
            path="/comments",
            base_params={"parent_entity_id": "1", "parent_entity_type": "Event"},
            offset=offset,
            page_size=page_size,
        )
        paginator = client.list_comments(parent_entity_id="1", parent_entity_type="Event")
        with pytest.raises(error, match=match):
            paginator.from_cursor(legacy).first_page()

    assert captured == []


def test_list_comments_refuses_a_saved_offset_cursor_for_another_parent() -> None:
    captured: list[httpx.Request] = []
    with PublicClient() as client:
        _install_sync_gamma_transport(client, _comments_handler(captured, 20, 2))
        legacy = encode_offset_cursor(
            service="gamma",
            path="/comments",
            base_params={"parent_entity_id": "9", "parent_entity_type": "Event"},
            offset=20,
            page_size=20,
        )
        paginator = client.list_comments(parent_entity_id="1", parent_entity_type="Event")
        with pytest.raises(UserInputError, match="different query parameters"):
            paginator.from_cursor(legacy).first_page()

    assert captured == []


@pytest.mark.parametrize(
    ("cursor", "match"),
    [
        ("not-a-cursor", "Invalid pagination cursor"),
        ("", "Invalid pagination cursor"),
        (
            encode_keyset_cursor(
                service="gamma", path="/events/keyset", base_params=None, server_cursor="x"
            ),
            "does not belong to this endpoint",
        ),
    ],
)
def test_list_comments_rejects_foreign_cursors_before_any_request(cursor: str, match: str) -> None:
    captured: list[httpx.Request] = []
    with PublicClient() as client:
        _install_sync_gamma_transport(client, _keyset_comments_handler(captured, _TWO_KEYSET_PAGES))
        paginator = client.list_comments(parent_entity_id="1", parent_entity_type="Event")
        with pytest.raises(UserInputError, match=match):
            paginator.from_cursor(cursor).first_page()

    assert captured == []


@pytest.mark.parametrize(
    ("kwargs", "flag", "value"),
    [
        ({"get_positions": True}, "get_positions", "true"),
        ({"holders_only": True}, "holders_only", "true"),
        ({"order": "reactionCount"}, "order", "reactionCount"),
        ({"order": ""}, "order", ""),
    ],
)
def test_list_comments_keeps_unsupported_reads_on_offset_pages(
    kwargs: dict[str, object], flag: str, value: str
) -> None:
    captured: list[httpx.Request] = []
    with PublicClient() as client:
        _install_sync_gamma_transport(client, _comments_handler(captured, 20, 2))
        paginator = client.list_comments(
            parent_entity_id="1",
            parent_entity_type="Event",
            **kwargs,  # type: ignore[arg-type]
        )
        with pytest.raises(PaginationLimitError):
            for _ in paginator:
                pass

    assert _offsets(captured) == list(range(0, 201, 20))
    assert _query(captured[0])[flag] == [value]


@pytest.mark.parametrize(("page_size", "match"), [(101, "at most 100"), (0, "positive integer")])
def test_list_comments_validates_page_size_at_call_time(page_size: int, match: str) -> None:
    with PublicClient() as client, pytest.raises(UserInputError, match=match):
        client.list_comments(parent_entity_id="1", parent_entity_type="Event", page_size=page_size)


def test_list_comments_to_pandas_drains_a_cursor_walk() -> None:
    captured: list[httpx.Request] = []
    pages: dict[str | None, tuple[list[dict[str, str]], str | None]] = {
        None: ([{"id": "3"}], "tok1"),
        "tok1": ([{"id": "2"}], "tok2"),
        "tok2": ([{"id": "1"}], None),
    }
    with PublicClient() as client:
        _install_sync_gamma_transport(client, _keyset_comments_handler(captured, pages))
        frame = client.list_comments(parent_entity_id="1", parent_entity_type="Event").to_pandas(
            limit=None
        )

    assert len(captured) == 3
    assert len(frame) == 3


def test_async_list_comments_walks_by_server_cursor() -> None:
    async def run() -> None:
        captured: list[httpx.Request] = []
        async with AsyncPublicClient() as client:
            _install_async_gamma_transport(
                client, _keyset_comments_handler(captured, _TWO_KEYSET_PAGES)
            )
            paginator = client.list_comments(parent_entity_id="1", parent_entity_type="Event")
            pages = [page async for page in paginator]

        assert _query(captured[0])["ascending"] == ["false"]
        assert _query(captured[1])["after_cursor"] == ["tok1"]
        assert [comment.id for page in pages for comment in page.items] == ["3", "2", "1"]
        assert pages[-1].has_more is False

    asyncio.run(run())


def test_async_list_comments_resumes_and_refuses_saved_offset_cursors() -> None:
    async def run() -> None:
        captured: list[httpx.Request] = []
        base_params = {"parent_entity_id": "1", "parent_entity_type": "Event"}
        async with AsyncPublicClient() as client:
            _install_async_gamma_transport(client, _comments_handler(captured, 20, 2))
            paginator = client.list_comments(parent_entity_id="1", parent_entity_type="Event")

            within = encode_offset_cursor(
                service="gamma", path="/comments", base_params=base_params, offset=180, page_size=20
            )
            page = await paginator.from_cursor(within).first_page()
            assert _offsets(captured) == [180]
            assert page.has_more is True

            beyond = encode_offset_cursor(
                service="gamma", path="/comments", base_params=base_params, offset=220, page_size=20
            )
            with pytest.raises(PaginationLimitError):
                await paginator.from_cursor(beyond).first_page()
            assert _offsets(captured) == [180]

    asyncio.run(run())
