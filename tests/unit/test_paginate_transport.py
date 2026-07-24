# pyright: reportPrivateUsage=false
import asyncio
import dataclasses
import typing
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from polymarket._internal.dispatch import (
    async_paginate_offset,
    async_paginate_page_based,
    sync_paginate_offset,
    sync_paginate_page_based,
)
from polymarket._internal.pagination import decode_offset_cursor, decode_page_cursor
from polymarket._internal.request import OffsetPaginatedSpec, PageBasedPagePayload, PageBasedSpec
from polymarket.clients._transport import AsyncTransport, SyncTransport
from polymarket.clients.async_public import AsyncPublicClient
from polymarket.clients.public import PublicClient
from polymarket.errors import UserInputError


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
):
    return OffsetPaginatedSpec[int](
        service="data",
        path=path,
        parse_items=lambda payload: tuple(payload),  # type: ignore[arg-type]
        base_params=base_params,
        max_page_size=max_page_size,
    )


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
