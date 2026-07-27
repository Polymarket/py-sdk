"""Tests for the frame methods on Page / Paginator / AsyncPaginator."""

# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportUnknownParameterType=false

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from decimal import Decimal
from typing import Any

import pytest
from pydantic import BaseModel

from polymarket.errors import UserInputError
from polymarket.pagination import AsyncPaginator, Page, Paginator


class _Item(BaseModel):
    n: int
    v: Decimal


def _three_page_sync() -> tuple[Paginator[_Item], list[str | None]]:
    fetched: list[str | None] = []

    def fetch(cursor: str | None) -> Page[_Item]:
        fetched.append(cursor)
        if cursor is None:
            return Page(
                items=(_Item(n=1, v=Decimal("0.1")),),
                has_more=True,
                next_cursor="p2",
            )
        if cursor == "p2":
            return Page(
                items=(_Item(n=2, v=Decimal("0.2")),),
                has_more=True,
                next_cursor="p3",
            )
        return Page(items=(_Item(n=3, v=Decimal("0.3")),), has_more=False)

    return Paginator(fetch=fetch), fetched


def _three_page_async() -> tuple[AsyncPaginator[_Item], list[str | None]]:
    fetched: list[str | None] = []

    async def fetch(cursor: str | None) -> Page[_Item]:
        fetched.append(cursor)
        if cursor is None:
            return Page(
                items=(_Item(n=1, v=Decimal("0.1")),),
                has_more=True,
                next_cursor="p2",
            )
        if cursor == "p2":
            return Page(
                items=(_Item(n=2, v=Decimal("0.2")),),
                has_more=True,
                next_cursor="p3",
            )
        return Page(items=(_Item(n=3, v=Decimal("0.3")),), has_more=False)

    return AsyncPaginator(fetch=fetch), fetched


def test_page_to_pandas() -> None:
    page: Page[_Item] = Page(
        items=(_Item(n=1, v=Decimal("0.1")), _Item(n=2, v=Decimal("0.2"))),
        has_more=False,
    )
    df = page.to_pandas()
    assert len(df) == 2
    assert list(df.columns) == ["n", "v"]


def test_page_to_polars() -> None:
    page: Page[_Item] = Page(items=(_Item(n=1, v=Decimal("0.1")),), has_more=False)
    df = page.to_polars()
    assert df.shape == (1, 2)


def test_page_to_arrow() -> None:
    page: Page[_Item] = Page(items=(_Item(n=1, v=Decimal("0.1")),), has_more=False)
    table = page.to_arrow()
    assert table.num_rows == 1


def test_paginator_to_pandas_without_limit_raises_typeerror() -> None:
    paginator, _ = _three_page_sync()
    with pytest.raises(TypeError, match="missing.*required.*keyword.*argument.*limit"):
        paginator.to_pandas()  # type: ignore[call-arg]


def test_paginator_to_polars_without_limit_raises_typeerror() -> None:
    paginator, _ = _three_page_sync()
    with pytest.raises(TypeError, match="missing.*required.*keyword.*argument.*limit"):
        paginator.to_polars()  # type: ignore[call-arg]


def test_paginator_to_arrow_without_limit_raises_typeerror() -> None:
    paginator, _ = _three_page_sync()
    with pytest.raises(TypeError, match="missing.*required.*keyword.*argument.*limit"):
        paginator.to_arrow()  # type: ignore[call-arg]


def test_paginator_limit_int_bounded_sets_truncated_marker() -> None:
    paginator, _ = _three_page_sync()
    df = paginator.to_pandas(limit=2)
    assert len(df) == 2
    assert df.attrs.get("polymarket_truncated") is True


def test_paginator_limit_int_exact_no_truncation_marker() -> None:
    paginator, _ = _three_page_sync()
    df = paginator.to_pandas(limit=3)
    assert len(df) == 3
    assert "polymarket_truncated" not in df.attrs


def test_paginator_limit_int_larger_than_available() -> None:
    paginator, _ = _three_page_sync()
    df = paginator.to_pandas(limit=100)
    assert len(df) == 3
    assert "polymarket_truncated" not in df.attrs


def test_paginator_limit_at_page_boundary_confirms_truncation_via_next_page() -> None:
    """A full page reports has_more=True as a heuristic, so limit landing
    exactly on a page boundary fetches the next page: a further item proves
    truncation."""
    paginator, fetched = _three_page_sync()
    df = paginator.to_pandas(limit=2)
    assert len(df) == 2
    assert df.attrs.get("polymarket_truncated") is True
    assert fetched == [None, "p2", "p3"]


def test_paginator_limit_at_exhausted_boundary_omits_truncation_marker() -> None:
    """When the collection ends exactly at limit, the confirming fetch returns
    an empty page and no truncation is reported."""
    fetched: list[str | None] = []

    def fetch(cursor: str | None) -> Page[_Item]:
        fetched.append(cursor)
        if cursor is None:
            return Page(
                items=(_Item(n=1, v=Decimal("0.1")),),
                has_more=True,
                next_cursor="p2",
            )
        return Page(items=(), has_more=False)

    df = Paginator(fetch=fetch).to_pandas(limit=1)
    assert len(df) == 1
    assert "polymarket_truncated" not in df.attrs
    assert fetched == [None, "p2"]


def test_paginator_limit_zero_returns_empty_dataframe_without_fetching() -> None:
    paginator, fetched = _three_page_sync()
    df = paginator.to_pandas(limit=0)
    assert len(df) == 0
    assert "polymarket_truncated" not in df.attrs
    assert fetched == []


def test_paginator_negative_limit_rejected() -> None:
    paginator, _ = _three_page_sync()
    with pytest.raises(UserInputError, match="limit must be >= 0"):
        paginator.to_pandas(limit=-1)


def test_paginator_limit_none_drains_all() -> None:
    paginator, fetched = _three_page_sync()
    df = paginator.to_pandas(limit=None)
    assert len(df) == 3
    assert "polymarket_truncated" not in df.attrs
    assert fetched == [None, "p2", "p3"]


def test_paginator_to_polars_limit_int() -> None:
    paginator, _ = _three_page_sync()
    df = paginator.to_polars(limit=2)
    assert df.shape == (2, 2)


def test_paginator_to_polars_limit_none() -> None:
    paginator, _ = _three_page_sync()
    df = paginator.to_polars(limit=None)
    assert df.shape == (3, 2)


def test_paginator_to_arrow_limit_int() -> None:
    paginator, _ = _three_page_sync()
    table = paginator.to_arrow(limit=1)
    assert table.num_rows == 1


def test_paginator_to_arrow_limit_none() -> None:
    paginator, _ = _three_page_sync()
    table = paginator.to_arrow(limit=None)
    assert table.num_rows == 3


def test_paginator_to_arrow_truncated_sets_schema_metadata() -> None:
    paginator, _ = _three_page_sync()
    table = paginator.to_arrow(limit=2)
    md = table.schema.metadata or {}
    assert md.get(b"polymarket_truncated") == b"true"


def test_paginator_to_arrow_not_truncated_omits_metadata() -> None:
    paginator, _ = _three_page_sync()
    table = paginator.to_arrow(limit=None)
    md = table.schema.metadata or {}
    assert b"polymarket_truncated" not in md


def _run(coro: Coroutine[Any, Any, object]) -> object:
    return asyncio.run(coro)


def test_async_paginator_without_limit_raises_typeerror() -> None:
    async def go() -> None:
        paginator, _ = _three_page_async()
        with pytest.raises(TypeError, match="missing.*required.*keyword.*argument.*limit"):
            await paginator.to_pandas()  # type: ignore[call-arg]

    _run(go())


def test_async_paginator_limit_int_truncated() -> None:
    async def go() -> None:
        paginator, _ = _three_page_async()
        df = await paginator.to_pandas(limit=2)
        assert len(df) == 2
        assert df.attrs.get("polymarket_truncated") is True

    _run(go())


def test_async_paginator_limit_at_page_boundary_confirms_truncation_via_next_page() -> None:
    async def go() -> None:
        paginator, fetched = _three_page_async()
        df = await paginator.to_pandas(limit=1)
        assert len(df) == 1
        assert df.attrs.get("polymarket_truncated") is True
        assert fetched == [None, "p2"]

    _run(go())


def test_async_paginator_limit_at_exhausted_boundary_omits_truncation_marker() -> None:
    async def go() -> None:
        fetched: list[str | None] = []

        async def fetch(cursor: str | None) -> Page[_Item]:
            fetched.append(cursor)
            if cursor is None:
                return Page(
                    items=(_Item(n=1, v=Decimal("0.1")),),
                    has_more=True,
                    next_cursor="p2",
                )
            return Page(items=(), has_more=False)

        df = await AsyncPaginator(fetch=fetch).to_pandas(limit=1)
        assert len(df) == 1
        assert "polymarket_truncated" not in df.attrs
        assert fetched == [None, "p2"]

    _run(go())


def test_async_paginator_limit_none_drains() -> None:
    async def go() -> None:
        paginator, fetched = _three_page_async()
        df = await paginator.to_pandas(limit=None)
        assert len(df) == 3
        assert fetched == [None, "p2", "p3"]

    _run(go())


def test_async_paginator_to_arrow_truncated_sets_schema_metadata() -> None:
    async def go() -> None:
        paginator, _ = _three_page_async()
        table = await paginator.to_arrow(limit=1)
        md = table.schema.metadata or {}
        assert md.get(b"polymarket_truncated") == b"true"

    _run(go())


def test_async_paginator_to_polars_and_arrow() -> None:
    async def go() -> None:
        paginator, _ = _three_page_async()
        polars_df = await paginator.to_polars(limit=None)
        assert polars_df.shape == (3, 2)

        paginator2, _ = _three_page_async()
        arrow_table = await paginator2.to_arrow(limit=None)
        assert arrow_table.num_rows == 3

    _run(go())


def test_async_paginator_negative_limit_rejected() -> None:
    async def go() -> None:
        paginator, _ = _three_page_async()
        with pytest.raises(UserInputError, match="limit must be >= 0"):
            await paginator.to_pandas(limit=-5)

    _run(go())


def test_async_paginator_limit_zero_does_not_fetch() -> None:
    async def go() -> None:
        paginator, fetched = _three_page_async()
        df = await paginator.to_pandas(limit=0)
        assert len(df) == 0
        assert "polymarket_truncated" not in df.attrs
        assert fetched == []

    _run(go())


def test_async_paginator_handles_cancellation_during_drain() -> None:
    drained: list[int] = []

    async def slow_fetch(cursor: str | None) -> Page[_Item]:
        if cursor is None:
            return Page(
                items=(_Item(n=1, v=Decimal("0.1")),),
                has_more=True,
                next_cursor="p2",
            )
        await asyncio.sleep(10)
        return Page(items=(), has_more=False)

    async def go() -> None:
        paginator: AsyncPaginator[_Item] = AsyncPaginator(fetch=slow_fetch)

        async def drain() -> None:
            df = await paginator.to_pandas(limit=None)
            drained.append(len(df))

        task = asyncio.create_task(drain())
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert drained == []

    _run(go())
