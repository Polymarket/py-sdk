import asyncio
import base64
import json

import pytest

from polymarket._internal.pagination import (
    compute_keyset_page,
    compute_offset_page,
    decode_keyset_cursor,
    decode_offset_cursor,
    decode_page_cursor,
    encode_keyset_cursor,
    encode_offset_cursor,
    encode_page_cursor,
    fingerprint_query,
)
from polymarket.errors import RequestRejectedError, UnexpectedResponseError, UserInputError
from polymarket.pagination import AsyncPaginator, Page, Paginator


def test_offset_cursor_round_trip() -> None:
    cursor = encode_offset_cursor(
        path="/positions",
        base_params={"user": "0xA"},
        offset=20,
        page_size=10,
    )
    assert decode_offset_cursor(
        cursor,
        expected_path="/positions",
        expected_base_params={"user": "0xA"},
    ) == (20, 10)


def test_offset_cursor_format_is_stable() -> None:
    cursor = encode_offset_cursor(
        path="/positions",
        base_params={"user": "0xA"},
        offset=20,
        page_size=10,
    )
    raw = base64.b64decode(cursor).decode("utf-8")
    fp = fingerprint_query({"user": "0xA"})
    assert raw == f'{{"f":"{fp}","o":20,"p":"/positions","s":10,"svc":"predictions","v":1}}'


def test_decode_rejects_path_mismatch() -> None:
    cursor = encode_offset_cursor(
        path="/positions",
        base_params={"user": "0xA"},
        offset=20,
        page_size=10,
    )
    with pytest.raises(UserInputError, match="does not belong to this endpoint"):
        decode_offset_cursor(
            cursor,
            expected_path="/trades",
            expected_base_params={"user": "0xA"},
        )


def _saved_cursor(**payload: object) -> str:
    """A cursor in the format earlier releases issued."""
    return base64.b64encode(json.dumps({"v": 1, **payload}).encode()).decode()


def test_cursor_saved_before_the_listing_moved_resumes_it() -> None:
    fingerprint = fingerprint_query({"user": "0xA"})
    saved = _saved_cursor(svc="data", p="/v2/positions", f=fingerprint, o=20, s=10)

    assert decode_offset_cursor(
        saved, expected_path="/v1/positions", expected_base_params={"user": "0xA"}
    ) == (20, 10)


def test_saved_cursor_from_another_listing_is_rejected() -> None:
    fingerprint = fingerprint_query({"user": "0xA"})
    saved = _saved_cursor(svc="data", p="/v2/trades", f=fingerprint, o=20, s=10)

    with pytest.raises(UserInputError, match="does not belong to this endpoint"):
        decode_offset_cursor(
            saved, expected_path="/v1/positions", expected_base_params={"user": "0xA"}
        )


def test_decode_rejects_query_mismatch() -> None:
    cursor = encode_offset_cursor(
        path="/positions",
        base_params={"user": "0xA"},
        offset=20,
        page_size=10,
    )
    with pytest.raises(UserInputError, match="different query parameters"):
        decode_offset_cursor(
            cursor,
            expected_path="/positions",
            expected_base_params={"user": "0xB"},
        )


def test_decode_rejects_invalid_base64() -> None:
    with pytest.raises(UserInputError, match="Invalid pagination cursor"):
        decode_offset_cursor(
            "not-base64!!!",
            expected_path="/positions",
            expected_base_params=None,
        )


def test_decode_rejects_non_json_payload() -> None:
    bad = base64.b64encode(b"not json").decode("ascii")
    with pytest.raises(UserInputError, match="Invalid pagination cursor"):
        decode_offset_cursor(
            bad,
            expected_path="/positions",
            expected_base_params=None,
        )


def test_decode_rejects_missing_fields() -> None:
    fp = fingerprint_query(None)
    bad = base64.b64encode(
        json.dumps({"v": 1, "svc": "predictions", "p": "/positions", "f": fp, "o": 5}).encode(
            "utf-8"
        )
    ).decode("ascii")
    with pytest.raises(UserInputError, match="Invalid pagination cursor"):
        decode_offset_cursor(
            bad,
            expected_path="/positions",
            expected_base_params=None,
        )


def test_decode_rejects_unsupported_version() -> None:
    bad = base64.b64encode(
        json.dumps(
            {"v": 999, "svc": "predictions", "p": "/positions", "f": "deadbeef", "o": 0, "s": 10}
        ).encode("utf-8")
    ).decode("ascii")
    with pytest.raises(UserInputError, match="Unsupported pagination cursor version"):
        decode_offset_cursor(
            bad,
            expected_path="/positions",
            expected_base_params=None,
        )


def test_decode_rejects_negative_offset() -> None:
    fp = fingerprint_query({"user": "0xA"})
    bad = base64.b64encode(
        json.dumps(
            {"v": 1, "svc": "predictions", "p": "/positions", "f": fp, "o": -1, "s": 10}
        ).encode("utf-8")
    ).decode("ascii")
    with pytest.raises(UserInputError, match="Invalid pagination cursor"):
        decode_offset_cursor(
            bad,
            expected_path="/positions",
            expected_base_params={"user": "0xA"},
        )


def test_decode_rejects_zero_page_size() -> None:
    fp = fingerprint_query({"user": "0xA"})
    bad = base64.b64encode(
        json.dumps(
            {"v": 1, "svc": "predictions", "p": "/positions", "f": fp, "o": 0, "s": 0}
        ).encode("utf-8")
    ).decode("ascii")
    with pytest.raises(UserInputError, match="Invalid pagination cursor"):
        decode_offset_cursor(
            bad,
            expected_path="/positions",
            expected_base_params={"user": "0xA"},
        )


def test_encode_rejects_empty_path() -> None:
    with pytest.raises(UserInputError, match="path"):
        encode_offset_cursor(path="", base_params=None, offset=0, page_size=10)


def test_encode_rejects_negative_offset() -> None:
    with pytest.raises(UserInputError, match="non-negative"):
        encode_offset_cursor(path="/positions", base_params=None, offset=-1, page_size=10)


def test_encode_rejects_zero_page_size() -> None:
    with pytest.raises(UserInputError, match="positive"):
        encode_offset_cursor(path="/positions", base_params=None, offset=0, page_size=0)


def test_fingerprint_is_order_independent() -> None:
    assert fingerprint_query({"a": 1, "b": 2}) == fingerprint_query({"b": 2, "a": 1})


def test_fingerprint_differentiates_values() -> None:
    assert fingerprint_query({"user": "0xA"}) != fingerprint_query({"user": "0xB"})


def test_compute_offset_page_more_when_full() -> None:
    # Requests ask for exactly page_size rows, so a full page means another
    # page may exist and pagination must continue instead of silently
    # dropping the tail.
    page = compute_offset_page(
        path="/positions",
        base_params=None,
        offset=0,
        page_size=10,
        items=tuple(range(10)),
    )
    assert page.items == tuple(range(10))
    assert page.has_more is True
    assert page.next_cursor is not None
    assert decode_offset_cursor(
        page.next_cursor,
        expected_path="/positions",
        expected_base_params=None,
    ) == (10, 10)


def test_compute_offset_page_uses_page_fill_over_item_count() -> None:
    # When the server's limit bounds a subset of the rows (roots, not their
    # replies), a page padded with extra rows is not a full page.
    page = compute_offset_page(
        path="/comments",
        base_params=None,
        offset=0,
        page_size=10,
        items=tuple(range(15)),
        page_fill=lambda items: 7,
    )
    assert page.items == tuple(range(15))
    assert page.has_more is False
    assert page.next_cursor is None

    full = compute_offset_page(
        path="/comments",
        base_params=None,
        offset=0,
        page_size=10,
        items=tuple(range(15)),
        page_fill=lambda items: 10,
    )
    assert full.has_more is True
    assert full.next_cursor is not None


def test_compute_offset_page_no_more_when_partial() -> None:
    page = compute_offset_page(
        path="/positions",
        base_params=None,
        offset=0,
        page_size=10,
        items=(1, 2, 3),
    )
    assert page.items == (1, 2, 3)
    assert page.has_more is False
    assert page.next_cursor is None


def test_paginator_first_page_returns_page() -> None:
    paginator = Paginator[int](
        fetch=lambda _cursor: Page(items=(1, 2, 3), has_more=False),
    )
    page = paginator.first_page()
    assert page.items == (1, 2, 3)
    assert page.has_more is False
    assert page.next_cursor is None


def test_paginator_preserves_rejected_cursor_without_restarting() -> None:
    rejection = RequestRejectedError("Restart this listing", status=400)
    requested: list[str | None] = []

    def fetch(cursor: str | None) -> Page[int]:
        requested.append(cursor)
        raise rejection

    paginator = Paginator[int](fetch=fetch)
    with pytest.raises(RequestRejectedError) as caught:
        paginator.from_cursor("obsolete-closed-order").first_page()
    assert caught.value is rejection
    assert requested == ["obsolete-closed-order"]


def test_paginator_keeps_pages_before_rejected_continuation() -> None:
    rejection = RequestRejectedError("Restart this listing", status=400)
    requested: list[str | None] = []

    def fetch(cursor: str | None) -> Page[int]:
        requested.append(cursor)
        if cursor is not None:
            raise rejection
        return Page(items=(1,), has_more=True, next_cursor="obsolete-closed-order")

    pages: list[Page[int]] = []
    with pytest.raises(RequestRejectedError) as caught:
        for page in Paginator[int](fetch=fetch):
            pages.append(page)
    assert caught.value is rejection
    assert [page.items for page in pages] == [(1,)]
    assert requested == [None, "obsolete-closed-order"]


def test_async_paginator_preserves_rejected_cursor_without_restarting() -> None:
    rejection = RequestRejectedError("Restart this listing", status=400)
    requested: list[str | None] = []

    async def fetch(cursor: str | None) -> Page[int]:
        requested.append(cursor)
        raise rejection

    async def run() -> None:
        paginator = AsyncPaginator[int](fetch=fetch)
        with pytest.raises(RequestRejectedError) as caught:
            await paginator.from_cursor("obsolete-closed-order").first_page()
        assert caught.value is rejection

    asyncio.run(run())
    assert requested == ["obsolete-closed-order"]


def test_async_paginator_keeps_pages_before_rejected_continuation() -> None:
    rejection = RequestRejectedError("Restart this listing", status=400)
    requested: list[str | None] = []

    async def fetch(cursor: str | None) -> Page[int]:
        requested.append(cursor)
        if cursor is not None:
            raise rejection
        return Page(items=(1,), has_more=True, next_cursor="obsolete-closed-order")

    async def run() -> list[Page[int]]:
        pages: list[Page[int]] = []
        with pytest.raises(RequestRejectedError) as caught:
            async for page in AsyncPaginator[int](fetch=fetch):
                pages.append(page)
        assert caught.value is rejection
        return pages

    assert [page.items for page in asyncio.run(run())] == [(1,)]
    assert requested == [None, "obsolete-closed-order"]


def test_paginator_iteration_walks_all_pages() -> None:
    pages = [
        Page(items=(1, 2), has_more=True, next_cursor="c1"),
        Page(items=(3, 4), has_more=True, next_cursor="c2"),
        Page(items=(5,), has_more=False),
    ]
    seen_cursors: list[str | None] = []

    def fetch(cursor: str | None) -> Page[int]:
        seen_cursors.append(cursor)
        return pages[len(seen_cursors) - 1]

    paginator = Paginator[int](fetch=fetch)
    collected = [page.items for page in paginator]
    assert collected == [(1, 2), (3, 4), (5,)]
    assert seen_cursors == [None, "c1", "c2"]


def test_paginator_raises_when_has_more_without_cursor() -> None:
    def fetch(_cursor: str | None) -> Page[int]:
        return Page(items=(1,), has_more=True, next_cursor=None)

    paginator = Paginator[int](fetch=fetch)
    with pytest.raises(UnexpectedResponseError, match="without a next cursor"):
        list(paginator)


@pytest.mark.parametrize(
    ("initial_cursor", "next_cursors"),
    [
        (None, ["a", "a"]),
        (None, ["a", "b", "a"]),
        ("a", ["a"]),
    ],
    ids=["immediate-repeat", "two-cursor-cycle", "resume-at-repeated-cursor"],
)
def test_paginator_raises_on_repeated_cursor(
    initial_cursor: str | None, next_cursors: list[str]
) -> None:
    requested: list[str | None] = []

    def fetch(cursor: str | None) -> Page[int]:
        requested.append(cursor)
        return Page(
            items=(len(requested),), has_more=True, next_cursor=next_cursors[len(requested) - 1]
        )

    paginator = (
        Paginator[int](fetch=fetch).from_cursor(initial_cursor)
        if initial_cursor
        else Paginator[int](fetch=fetch)
    )
    pages: list[Page[int]] = []
    with pytest.raises(UnexpectedResponseError, match="already requested"):
        for page in paginator:
            pages.append(page)

    assert len(pages) == len(next_cursors)
    assert requested == [initial_cursor, *next_cursors[:-1]]


@pytest.mark.parametrize(
    "terminal",
    [
        Page(items=(2,), has_more=False, next_cursor="a"),
        Page(items=(2,), has_more=True, next_cursor="a", limit_reached=True),
    ],
    ids=["has-more-false", "limit-reached"],
)
def test_paginator_stops_normally_on_terminal_page_with_repeated_cursor(
    terminal: Page[int],
) -> None:
    def fetch(cursor: str | None) -> Page[int]:
        return Page(items=(1,), has_more=True, next_cursor="a") if cursor is None else terminal

    paginator = Paginator[int](fetch=fetch)
    assert [page.items for page in paginator] == [(1,), (2,)]


def test_paginator_walks_do_not_share_requested_cursors() -> None:
    requested: list[str | None] = []

    def fetch(cursor: str | None) -> Page[int]:
        requested.append(cursor)
        return (
            Page(items=(1,), has_more=True, next_cursor="a")
            if cursor is None
            else Page(items=(2,), has_more=False)
        )

    paginator = Paginator[int](fetch=fetch)
    assert list(paginator) == list(paginator)
    assert requested == [None, "a", None, "a"]


def test_paginator_is_reusable() -> None:
    fetch_count = [0]

    def fetch(_cursor: str | None) -> Page[int]:
        fetch_count[0] += 1
        return Page(items=(1, 2), has_more=False)

    paginator = Paginator[int](fetch=fetch)
    first = list(paginator)
    second = list(paginator)
    assert first == second
    assert fetch_count[0] == 2


def test_paginator_iter_items_flattens_pages() -> None:
    pages = [
        Page(items=(1, 2), has_more=True, next_cursor="c1"),
        Page(items=(3, 4), has_more=False),
    ]
    paginator = Paginator[int](fetch=lambda cursor: pages[0] if cursor is None else pages[1])
    assert list(paginator.iter_items()) == [1, 2, 3, 4]


def test_paginator_from_cursor_returns_new_paginator() -> None:
    seen: list[str | None] = []

    def fetch(cursor: str | None) -> Page[int]:
        seen.append(cursor)
        return Page(items=(1,), has_more=False)

    paginator = Paginator[int](fetch=fetch)
    paginator.from_cursor("ABC").first_page()
    assert seen == ["ABC"]


def test_paginator_from_cursor_none_yields_empty() -> None:
    fetch_count = [0]

    def fetch(_cursor: str | None) -> Page[int]:
        fetch_count[0] += 1
        return Page(items=(1,), has_more=False)

    paginator = Paginator[int](fetch=fetch)
    empty = paginator.from_cursor(None)
    assert empty.first_page().items == ()
    assert list(empty) == []
    assert fetch_count[0] == 0


def test_async_paginator_iteration_walks_all_pages() -> None:
    pages = [
        Page(items=(1, 2), has_more=True, next_cursor="c1"),
        Page(items=(3,), has_more=False),
    ]
    seen: list[str | None] = []

    async def fetch(cursor: str | None) -> Page[int]:
        seen.append(cursor)
        return pages[len(seen) - 1]

    async def run() -> list[tuple[int, ...]]:
        paginator = AsyncPaginator[int](fetch=fetch)
        collected: list[tuple[int, ...]] = []
        async for page in paginator:
            collected.append(page.items)
        return collected

    assert asyncio.run(run()) == [(1, 2), (3,)]
    assert seen == [None, "c1"]


def test_async_paginator_raises_when_has_more_without_cursor() -> None:
    async def fetch(_cursor: str | None) -> Page[int]:
        return Page(items=(1,), has_more=True, next_cursor=None)

    async def run() -> None:
        paginator = AsyncPaginator[int](fetch=fetch)
        async for _page in paginator:
            pass

    with pytest.raises(UnexpectedResponseError, match="without a next cursor"):
        asyncio.run(run())


@pytest.mark.parametrize(
    ("initial_cursor", "next_cursors"),
    [
        (None, ["a", "a"]),
        (None, ["a", "b", "a"]),
        ("a", ["a"]),
    ],
    ids=["immediate-repeat", "two-cursor-cycle", "resume-at-repeated-cursor"],
)
def test_async_paginator_raises_on_repeated_cursor(
    initial_cursor: str | None, next_cursors: list[str]
) -> None:
    requested: list[str | None] = []
    pages: list[Page[int]] = []

    async def fetch(cursor: str | None) -> Page[int]:
        requested.append(cursor)
        return Page(
            items=(len(requested),), has_more=True, next_cursor=next_cursors[len(requested) - 1]
        )

    async def run() -> None:
        paginator = AsyncPaginator[int](fetch=fetch)
        if initial_cursor:
            paginator = paginator.from_cursor(initial_cursor)
        async for page in paginator:
            pages.append(page)

    with pytest.raises(UnexpectedResponseError, match="already requested"):
        asyncio.run(run())

    assert len(pages) == len(next_cursors)
    assert requested == [initial_cursor, *next_cursors[:-1]]


@pytest.mark.parametrize(
    "terminal",
    [
        Page(items=(2,), has_more=False, next_cursor="a"),
        Page(items=(2,), has_more=True, next_cursor="a", limit_reached=True),
    ],
    ids=["has-more-false", "limit-reached"],
)
def test_async_paginator_stops_normally_on_terminal_page_with_repeated_cursor(
    terminal: Page[int],
) -> None:
    async def fetch(cursor: str | None) -> Page[int]:
        return Page(items=(1,), has_more=True, next_cursor="a") if cursor is None else terminal

    async def run() -> list[tuple[int, ...]]:
        return [page.items async for page in AsyncPaginator[int](fetch=fetch)]

    assert asyncio.run(run()) == [(1,), (2,)]


def test_async_paginator_walks_do_not_share_requested_cursors() -> None:
    requested: list[str | None] = []

    async def fetch(cursor: str | None) -> Page[int]:
        requested.append(cursor)
        return (
            Page(items=(1,), has_more=True, next_cursor="a")
            if cursor is None
            else Page(items=(2,), has_more=False)
        )

    async def run() -> list[list[tuple[int, ...]]]:
        paginator = AsyncPaginator[int](fetch=fetch)
        first = [page.items async for page in paginator]
        second = [page.items async for page in paginator]
        return [first, second]

    first, second = asyncio.run(run())
    assert first == second
    assert requested == [None, "a", None, "a"]


def test_async_paginator_iter_items_flattens_pages() -> None:
    pages = [
        Page(items=(1, 2), has_more=True, next_cursor="c1"),
        Page(items=(3, 4), has_more=False),
    ]

    async def fetch(cursor: str | None) -> Page[int]:
        return pages[0] if cursor is None else pages[1]

    async def run() -> list[int]:
        paginator = AsyncPaginator[int](fetch=fetch)
        collected: list[int] = []
        async for item in paginator.iter_items():
            collected.append(item)
        return collected

    assert asyncio.run(run()) == [1, 2, 3, 4]


def test_async_paginator_from_cursor_none_yields_empty() -> None:
    fetch_count = [0]

    async def fetch(_cursor: str | None) -> Page[int]:
        fetch_count[0] += 1
        return Page(items=(1,), has_more=False)

    async def run() -> Page[int]:
        paginator = AsyncPaginator[int](fetch=fetch)
        empty = paginator.from_cursor(None)
        return await empty.first_page()

    page = asyncio.run(run())
    assert page.items == ()
    assert page.has_more is False
    assert fetch_count[0] == 0


def test_keyset_cursor_round_trip() -> None:
    cursor = encode_keyset_cursor(
        path="/v1/events",
        base_params={"closed": False},
        server_cursor="opaque-server-token",
    )
    assert (
        decode_keyset_cursor(
            cursor,
            expected_path="/v1/events",
            expected_base_params={"closed": False},
        )
        == "opaque-server-token"
    )


def test_keyset_cursor_format_is_stable() -> None:
    cursor = encode_keyset_cursor(
        path="/v1/markets",
        base_params={"closed": False},
        server_cursor="ABC",
    )
    raw = base64.b64decode(cursor).decode("utf-8")
    fp = fingerprint_query({"closed": False})
    assert raw == f'{{"f":"{fp}","k":"ABC","p":"/v1/markets","svc":"predictions","v":1}}'


def test_keyset_decode_rejects_path_mismatch() -> None:
    cursor = encode_keyset_cursor(
        path="/v1/events",
        base_params={"closed": False},
        server_cursor="X",
    )
    with pytest.raises(UserInputError, match="does not belong to this endpoint"):
        decode_keyset_cursor(
            cursor,
            expected_path="/v1/markets",
            expected_base_params={"closed": False},
        )


def test_saved_keyset_cursors_resume_moved_listings() -> None:
    markets = _saved_cursor(
        svc="gamma", p="/markets/keyset", f=fingerprint_query({"closed": False}), k="X"
    )
    comments = _saved_cursor(
        svc="gamma", p="/comments/user_address/0xabc", f=fingerprint_query(None), k="Y"
    )

    assert (
        decode_keyset_cursor(
            markets, expected_path="/v1/markets", expected_base_params={"closed": False}
        )
        == "X"
    )
    assert (
        decode_keyset_cursor(
            comments, expected_path="/v1/users/0xabc/comments", expected_base_params=None
        )
        == "Y"
    )


def test_keyset_decode_rejects_query_mismatch() -> None:
    cursor = encode_keyset_cursor(
        path="/v1/events",
        base_params={"closed": False},
        server_cursor="X",
    )
    with pytest.raises(UserInputError, match="different query parameters"):
        decode_keyset_cursor(
            cursor,
            expected_path="/v1/events",
            expected_base_params={"closed": True},
        )


def test_keyset_decode_rejects_malformed() -> None:
    with pytest.raises(UserInputError, match="Invalid pagination cursor"):
        decode_keyset_cursor(
            "not-base64!!",
            expected_path="/v1/events",
            expected_base_params=None,
        )


def test_keyset_decode_rejects_empty_server_cursor() -> None:
    payload = json.dumps(
        {
            "v": 1,
            "svc": "predictions",
            "p": "/v1/events",
            "f": fingerprint_query(None),
            "k": "",
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    cursor = base64.b64encode(payload.encode("utf-8")).decode("ascii")
    with pytest.raises(UserInputError, match="Invalid pagination cursor"):
        decode_keyset_cursor(
            cursor,
            expected_path="/v1/events",
            expected_base_params=None,
        )


def test_encode_keyset_rejects_empty_inputs() -> None:
    with pytest.raises(UserInputError, match="path"):
        encode_keyset_cursor(path="", base_params=None, server_cursor="X")
    with pytest.raises(UserInputError, match="server_cursor"):
        encode_keyset_cursor(path="/x", base_params=None, server_cursor="")


def test_compute_keyset_page_with_more() -> None:
    page = compute_keyset_page(
        path="/v1/events",
        base_params={"closed": False},
        items=(1, 2, 3),
        server_next_cursor="next-token",
    )
    assert page.items == (1, 2, 3)
    assert page.has_more is True
    assert page.next_cursor is not None
    assert (
        decode_keyset_cursor(
            page.next_cursor,
            expected_path="/v1/events",
            expected_base_params={"closed": False},
        )
        == "next-token"
    )


def test_compute_keyset_page_terminal() -> None:
    page = compute_keyset_page(
        path="/v1/events",
        base_params=None,
        items=(1, 2),
        server_next_cursor=None,
    )
    assert page.items == (1, 2)
    assert page.has_more is False
    assert page.next_cursor is None


def test_page_cursor_round_trip() -> None:
    cursor = encode_page_cursor(
        path="/v1/public-search",
        base_params={"q": "x"},
        page=2,
        page_size=10,
    )
    assert decode_page_cursor(
        cursor,
        expected_path="/v1/public-search",
        expected_base_params={"q": "x"},
    ) == (2, 10)


def test_page_cursor_rejects_invalid_page() -> None:
    with pytest.raises(UserInputError, match="page must be a positive integer"):
        encode_page_cursor(path="/v1/public-search", base_params=None, page=0, page_size=10)


def test_page_cursor_rejects_invalid_page_size() -> None:
    with pytest.raises(UserInputError, match="page_size must be a positive integer"):
        encode_page_cursor(path="/v1/public-search", base_params=None, page=1, page_size=0)


def test_page_decode_rejects_path_mismatch() -> None:
    cursor = encode_page_cursor(path="/v1/public-search", base_params=None, page=1, page_size=10)
    with pytest.raises(UserInputError, match="does not belong to this endpoint"):
        decode_page_cursor(
            cursor,
            expected_path="/other",
            expected_base_params=None,
        )


def test_page_decode_rejects_query_mismatch() -> None:
    cursor = encode_page_cursor(
        path="/v1/public-search",
        base_params={"q": "x"},
        page=1,
        page_size=10,
    )
    with pytest.raises(UserInputError, match="different query parameters"):
        decode_page_cursor(
            cursor,
            expected_path="/v1/public-search",
            expected_base_params={"q": "y"},
        )
