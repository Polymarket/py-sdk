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
from polymarket.errors import UnexpectedResponseError, UserInputError
from polymarket.pagination import AsyncPaginator, Page, Paginator


def test_offset_cursor_round_trip() -> None:
    cursor = encode_offset_cursor(
        service="data",
        path="/positions",
        base_params={"user": "0xA"},
        offset=20,
        page_size=10,
    )
    assert decode_offset_cursor(
        cursor,
        expected_service="data",
        expected_path="/positions",
        expected_base_params={"user": "0xA"},
    ) == (20, 10)


def test_offset_cursor_format_is_stable() -> None:
    cursor = encode_offset_cursor(
        service="data",
        path="/positions",
        base_params={"user": "0xA"},
        offset=20,
        page_size=10,
    )
    raw = base64.b64decode(cursor).decode("utf-8")
    fp = fingerprint_query({"user": "0xA"})
    assert raw == f'{{"f":"{fp}","o":20,"p":"/positions","s":10,"svc":"data","v":1}}'


def test_decode_rejects_path_mismatch() -> None:
    cursor = encode_offset_cursor(
        service="data",
        path="/positions",
        base_params={"user": "0xA"},
        offset=20,
        page_size=10,
    )
    with pytest.raises(UserInputError, match="does not belong to this endpoint"):
        decode_offset_cursor(
            cursor,
            expected_service="data",
            expected_path="/trades",
            expected_base_params={"user": "0xA"},
        )


def test_decode_rejects_service_mismatch() -> None:
    cursor = encode_offset_cursor(
        service="data",
        path="/positions",
        base_params={"user": "0xA"},
        offset=20,
        page_size=10,
    )
    with pytest.raises(UserInputError, match="does not belong to this service"):
        decode_offset_cursor(
            cursor,
            expected_service="gamma",
            expected_path="/positions",
            expected_base_params={"user": "0xA"},
        )


def test_decode_rejects_query_mismatch() -> None:
    cursor = encode_offset_cursor(
        service="data",
        path="/positions",
        base_params={"user": "0xA"},
        offset=20,
        page_size=10,
    )
    with pytest.raises(UserInputError, match="different query parameters"):
        decode_offset_cursor(
            cursor,
            expected_service="data",
            expected_path="/positions",
            expected_base_params={"user": "0xB"},
        )


def test_decode_rejects_invalid_base64() -> None:
    with pytest.raises(UserInputError, match="Invalid pagination cursor"):
        decode_offset_cursor(
            "not-base64!!!",
            expected_service="data",
            expected_path="/positions",
            expected_base_params=None,
        )


def test_decode_rejects_non_json_payload() -> None:
    bad = base64.b64encode(b"not json").decode("ascii")
    with pytest.raises(UserInputError, match="Invalid pagination cursor"):
        decode_offset_cursor(
            bad,
            expected_service="data",
            expected_path="/positions",
            expected_base_params=None,
        )


def test_decode_rejects_missing_fields() -> None:
    fp = fingerprint_query(None)
    bad = base64.b64encode(
        json.dumps({"v": 1, "svc": "data", "p": "/positions", "f": fp, "o": 5}).encode("utf-8")
    ).decode("ascii")
    with pytest.raises(UserInputError, match="Invalid pagination cursor"):
        decode_offset_cursor(
            bad,
            expected_service="data",
            expected_path="/positions",
            expected_base_params=None,
        )


def test_decode_rejects_unsupported_version() -> None:
    bad = base64.b64encode(
        json.dumps(
            {"v": 999, "svc": "data", "p": "/positions", "f": "deadbeef", "o": 0, "s": 10}
        ).encode("utf-8")
    ).decode("ascii")
    with pytest.raises(UserInputError, match="Unsupported pagination cursor version"):
        decode_offset_cursor(
            bad,
            expected_service="data",
            expected_path="/positions",
            expected_base_params=None,
        )


def test_decode_rejects_negative_offset() -> None:
    fp = fingerprint_query({"user": "0xA"})
    bad = base64.b64encode(
        json.dumps({"v": 1, "svc": "data", "p": "/positions", "f": fp, "o": -1, "s": 10}).encode(
            "utf-8"
        )
    ).decode("ascii")
    with pytest.raises(UserInputError, match="Invalid pagination cursor"):
        decode_offset_cursor(
            bad,
            expected_service="data",
            expected_path="/positions",
            expected_base_params={"user": "0xA"},
        )


def test_decode_rejects_zero_page_size() -> None:
    fp = fingerprint_query({"user": "0xA"})
    bad = base64.b64encode(
        json.dumps({"v": 1, "svc": "data", "p": "/positions", "f": fp, "o": 0, "s": 0}).encode(
            "utf-8"
        )
    ).decode("ascii")
    with pytest.raises(UserInputError, match="Invalid pagination cursor"):
        decode_offset_cursor(
            bad,
            expected_service="data",
            expected_path="/positions",
            expected_base_params={"user": "0xA"},
        )


def test_encode_rejects_empty_path() -> None:
    with pytest.raises(UserInputError, match="path"):
        encode_offset_cursor(service="data", path="", base_params=None, offset=0, page_size=10)


def test_encode_rejects_negative_offset() -> None:
    with pytest.raises(UserInputError, match="non-negative"):
        encode_offset_cursor(
            service="data", path="/positions", base_params=None, offset=-1, page_size=10
        )


def test_encode_rejects_zero_page_size() -> None:
    with pytest.raises(UserInputError, match="positive"):
        encode_offset_cursor(
            service="data", path="/positions", base_params=None, offset=0, page_size=0
        )


def test_fingerprint_is_order_independent() -> None:
    assert fingerprint_query({"a": 1, "b": 2}) == fingerprint_query({"b": 2, "a": 1})


def test_fingerprint_differentiates_values() -> None:
    assert fingerprint_query({"user": "0xA"}) != fingerprint_query({"user": "0xB"})


def test_compute_offset_page_more_when_full() -> None:
    # Requests ask for exactly page_size rows, so a full page means another
    # page may exist and pagination must continue instead of silently
    # dropping the tail.
    page = compute_offset_page(
        service="data",
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
        expected_service="data",
        expected_path="/positions",
        expected_base_params=None,
    ) == (10, 10)


def test_compute_offset_page_no_more_when_partial() -> None:
    page = compute_offset_page(
        service="data",
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
        service="gamma",
        path="/events/keyset",
        base_params={"closed": False},
        server_cursor="opaque-server-token",
    )
    assert (
        decode_keyset_cursor(
            cursor,
            expected_service="gamma",
            expected_path="/events/keyset",
            expected_base_params={"closed": False},
        )
        == "opaque-server-token"
    )


def test_keyset_cursor_format_is_stable() -> None:
    cursor = encode_keyset_cursor(
        service="gamma",
        path="/markets/keyset",
        base_params={"closed": False},
        server_cursor="ABC",
    )
    raw = base64.b64decode(cursor).decode("utf-8")
    fp = fingerprint_query({"closed": False})
    assert raw == f'{{"f":"{fp}","k":"ABC","p":"/markets/keyset","svc":"gamma","v":1}}'


def test_keyset_decode_rejects_path_mismatch() -> None:
    cursor = encode_keyset_cursor(
        service="gamma",
        path="/events/keyset",
        base_params={"closed": False},
        server_cursor="X",
    )
    with pytest.raises(UserInputError, match="does not belong to this endpoint"):
        decode_keyset_cursor(
            cursor,
            expected_service="gamma",
            expected_path="/markets/keyset",
            expected_base_params={"closed": False},
        )


def test_keyset_decode_rejects_service_mismatch() -> None:
    cursor = encode_keyset_cursor(
        service="gamma",
        path="/events/keyset",
        base_params={"closed": False},
        server_cursor="X",
    )
    with pytest.raises(UserInputError, match="does not belong to this service"):
        decode_keyset_cursor(
            cursor,
            expected_service="data",
            expected_path="/events/keyset",
            expected_base_params={"closed": False},
        )


def test_keyset_decode_rejects_query_mismatch() -> None:
    cursor = encode_keyset_cursor(
        service="gamma",
        path="/events/keyset",
        base_params={"closed": False},
        server_cursor="X",
    )
    with pytest.raises(UserInputError, match="different query parameters"):
        decode_keyset_cursor(
            cursor,
            expected_service="gamma",
            expected_path="/events/keyset",
            expected_base_params={"closed": True},
        )


def test_keyset_decode_rejects_malformed() -> None:
    with pytest.raises(UserInputError, match="Invalid pagination cursor"):
        decode_keyset_cursor(
            "not-base64!!",
            expected_service="gamma",
            expected_path="/events/keyset",
            expected_base_params=None,
        )


def test_keyset_decode_rejects_empty_server_cursor() -> None:
    payload = json.dumps(
        {
            "v": 1,
            "svc": "gamma",
            "p": "/events/keyset",
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
            expected_service="gamma",
            expected_path="/events/keyset",
            expected_base_params=None,
        )


def test_encode_keyset_rejects_empty_inputs() -> None:
    with pytest.raises(UserInputError, match="path"):
        encode_keyset_cursor(service="gamma", path="", base_params=None, server_cursor="X")
    with pytest.raises(UserInputError, match="server_cursor"):
        encode_keyset_cursor(service="gamma", path="/x", base_params=None, server_cursor="")


def test_compute_keyset_page_with_more() -> None:
    page = compute_keyset_page(
        service="gamma",
        path="/events/keyset",
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
            expected_service="gamma",
            expected_path="/events/keyset",
            expected_base_params={"closed": False},
        )
        == "next-token"
    )


def test_compute_keyset_page_terminal() -> None:
    page = compute_keyset_page(
        service="gamma",
        path="/events/keyset",
        base_params=None,
        items=(1, 2),
        server_next_cursor=None,
    )
    assert page.items == (1, 2)
    assert page.has_more is False
    assert page.next_cursor is None


def test_page_cursor_round_trip() -> None:
    cursor = encode_page_cursor(
        service="gamma",
        path="/public-search",
        base_params={"q": "x"},
        page=2,
        page_size=10,
    )
    assert decode_page_cursor(
        cursor,
        expected_service="gamma",
        expected_path="/public-search",
        expected_base_params={"q": "x"},
    ) == (2, 10)


def test_page_cursor_rejects_invalid_page() -> None:
    with pytest.raises(UserInputError, match="page must be a positive integer"):
        encode_page_cursor(
            service="gamma", path="/public-search", base_params=None, page=0, page_size=10
        )


def test_page_cursor_rejects_invalid_page_size() -> None:
    with pytest.raises(UserInputError, match="page_size must be a positive integer"):
        encode_page_cursor(
            service="gamma", path="/public-search", base_params=None, page=1, page_size=0
        )


def test_page_decode_rejects_path_mismatch() -> None:
    cursor = encode_page_cursor(
        service="gamma", path="/public-search", base_params=None, page=1, page_size=10
    )
    with pytest.raises(UserInputError, match="does not belong to this endpoint"):
        decode_page_cursor(
            cursor,
            expected_service="gamma",
            expected_path="/other",
            expected_base_params=None,
        )


def test_page_decode_rejects_query_mismatch() -> None:
    cursor = encode_page_cursor(
        service="gamma",
        path="/public-search",
        base_params={"q": "x"},
        page=1,
        page_size=10,
    )
    with pytest.raises(UserInputError, match="different query parameters"):
        decode_page_cursor(
            cursor,
            expected_service="gamma",
            expected_path="/public-search",
            expected_base_params={"q": "y"},
        )
