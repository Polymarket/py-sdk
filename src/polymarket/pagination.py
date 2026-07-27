"""Paginators and pages returned by SDK list-style endpoints."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import Any, Generic, Literal, TypeVar, cast

from polymarket._frames_bridge import frames_func as _frames_func
from polymarket.errors import UnexpectedResponseError

T = TypeVar("T")


# Frame-method returns are typed as ``Any`` because pandas/polars/pyarrow
# stubs don't survive strict-mode pyright. Drain ``limit`` is required so
# multi-page truncation can't be silent.
LimitArg = int | None
DecimalMode = Literal["decimal", "float"]


@dataclass(frozen=True, slots=True)
class Page(Generic[T]):
    items: tuple[T, ...]
    has_more: bool
    next_cursor: str | None = None
    total_count: int | None = None

    def _repr_html_(self) -> str:
        from polymarket._jupyter import card, safe_html_repr, truncate_mid

        @safe_html_repr
        def render(self: Page[T]) -> str:
            rows: list[tuple[str, str]] = []
            if self.next_cursor is not None:
                rows.append(("next_cursor", truncate_mid(self.next_cursor)))
            if self.total_count is not None:
                rows.append(("total_count", str(self.total_count)))
            title = f"Page  ·  {len(self.items)} item(s)  ·  has_more={self.has_more}"
            return card(title, rows=rows)

        return render(self)

    def to_arrow(self) -> Any:
        return _frames_func("to_arrow")(self)

    def to_pandas(
        self,
        *,
        decimal: DecimalMode = "decimal",
        explode: Sequence[str] | None = None,
    ) -> Any:
        return _frames_func("to_pandas")(self, decimal=decimal, explode=explode)

    def to_polars(
        self,
        *,
        explode: Sequence[str] | None = None,
    ) -> Any:
        return _frames_func("to_polars")(self, explode=explode)


class Paginator(Generic[T]):
    def __init__(
        self,
        fetch: Callable[[str | None], Page[T]],
        initial_cursor: str | None = None,
    ) -> None:
        self._fetch = fetch
        self._initial_cursor = initial_cursor

    def __repr__(self) -> str:
        return "Paginator(unfetched — call .first_page() or iterate)"

    def _repr_html_(self) -> str:
        from polymarket._jupyter import card

        return card("Paginator (unfetched — call .first_page() or iterate)")

    def first_page(self) -> Page[T]:
        return self._fetch(self._initial_cursor)

    def from_cursor(self, cursor: str | None) -> Paginator[T]:
        if cursor is None:
            return cast(Paginator[T], _EmptyPaginator())
        return Paginator(self._fetch, initial_cursor=cursor)

    def __iter__(self) -> Iterator[Page[T]]:
        return self._iter_pages()

    def iter_items(self) -> Iterator[T]:
        for page in self._iter_pages():
            yield from page.items

    def _iter_pages(self) -> Iterator[Page[T]]:
        cursor = self._initial_cursor
        while True:
            page = self._fetch(cursor)
            yield page
            if not page.has_more:
                return
            if page.next_cursor is None:
                raise UnexpectedResponseError(
                    "Paginated response set has_more=True without a next cursor."
                )
            cursor = page.next_cursor

    def to_arrow(self, *, limit: LimitArg) -> Any:
        items, truncated = _drain_paginator(self, limit)
        table = _frames_func("to_arrow")(tuple(items))
        return _mark_arrow_truncated(table) if truncated else table

    def to_pandas(
        self,
        *,
        limit: LimitArg,
        decimal: DecimalMode = "decimal",
        explode: Sequence[str] | None = None,
    ) -> Any:
        items, truncated = _drain_paginator(self, limit)
        df = _frames_func("to_pandas")(tuple(items), decimal=decimal, explode=explode)
        if truncated:
            df.attrs["polymarket_truncated"] = True
        return df

    def to_polars(
        self,
        *,
        limit: LimitArg,
        explode: Sequence[str] | None = None,
    ) -> Any:
        # Polars has no stable per-frame metadata surface in supported versions.
        # Keep truncation markers to pandas attrs and Arrow schema metadata.
        items, _truncated = _drain_paginator(self, limit)
        return _frames_func("to_polars")(tuple(items), explode=explode)


class AsyncPaginator(Generic[T]):
    def __init__(
        self,
        fetch: Callable[[str | None], Awaitable[Page[T]]],
        initial_cursor: str | None = None,
    ) -> None:
        self._fetch = fetch
        self._initial_cursor = initial_cursor

    def __repr__(self) -> str:
        return "AsyncPaginator(unfetched — call await .first_page() or async-iterate)"

    def _repr_html_(self) -> str:
        from polymarket._jupyter import card

        return card("AsyncPaginator (unfetched — call await .first_page() or async-iterate)")

    async def first_page(self) -> Page[T]:
        return await self._fetch(self._initial_cursor)

    def from_cursor(self, cursor: str | None) -> AsyncPaginator[T]:
        if cursor is None:
            return cast(AsyncPaginator[T], _EmptyAsyncPaginator())
        return AsyncPaginator(self._fetch, initial_cursor=cursor)

    def __aiter__(self) -> AsyncIterator[Page[T]]:
        return self._iter_pages()

    def iter_items(self) -> AsyncIterator[T]:
        return self._iter_items()

    async def _iter_pages(self) -> AsyncIterator[Page[T]]:
        cursor = self._initial_cursor
        while True:
            page = await self._fetch(cursor)
            yield page
            if not page.has_more:
                return
            if page.next_cursor is None:
                raise UnexpectedResponseError(
                    "Paginated response set has_more=True without a next cursor."
                )
            cursor = page.next_cursor

    async def _iter_items(self) -> AsyncIterator[T]:
        async for page in self._iter_pages():
            for item in page.items:
                yield item

    async def to_arrow(self, *, limit: LimitArg) -> Any:
        items, truncated = await _drain_async_paginator(self, limit)
        table = _frames_func("to_arrow")(tuple(items))
        return _mark_arrow_truncated(table) if truncated else table

    async def to_pandas(
        self,
        *,
        limit: LimitArg,
        decimal: DecimalMode = "decimal",
        explode: Sequence[str] | None = None,
    ) -> Any:
        items, truncated = await _drain_async_paginator(self, limit)
        df = _frames_func("to_pandas")(tuple(items), decimal=decimal, explode=explode)
        if truncated:
            df.attrs["polymarket_truncated"] = True
        return df

    async def to_polars(
        self,
        *,
        limit: LimitArg,
        explode: Sequence[str] | None = None,
    ) -> Any:
        items, _truncated = await _drain_async_paginator(self, limit)
        return _frames_func("to_polars")(tuple(items), explode=explode)


def _mark_arrow_truncated(table: Any) -> Any:
    # Arrow has no df.attrs equivalent; stash the marker in schema metadata.
    existing: dict[bytes, bytes] = dict(table.schema.metadata or {})
    existing[b"polymarket_truncated"] = b"true"
    return table.replace_schema_metadata(existing)


def _drain_paginator(paginator: Paginator[T], limit: int | None) -> tuple[list[T], bool]:
    if limit is None:
        return list(paginator.iter_items()), False
    if limit < 0:
        from polymarket.errors import UserInputError

        raise UserInputError(f"limit must be >= 0 or None; got {limit}.")
    if limit == 0:
        # Skip the fetch entirely; with no observation we can't claim truncation.
        return [], False
    # A full page reports has_more=True as a heuristic, so when `limit` lands
    # exactly on a page boundary the next page is fetched to decide truncation:
    # a further item proves truncation, an empty page proves completeness.
    out: list[T] = []
    for page in paginator:
        for item in page.items:
            if len(out) >= limit:
                return out, True
            out.append(item)
        if not page.has_more:
            return out, False
    return out, False


async def _drain_async_paginator(
    paginator: AsyncPaginator[T], limit: int | None
) -> tuple[list[T], bool]:
    if limit is None:
        out: list[T] = []
        async for item in paginator.iter_items():
            out.append(item)
        return out, False
    if limit < 0:
        from polymarket.errors import UserInputError

        raise UserInputError(f"limit must be >= 0 or None; got {limit}.")
    if limit == 0:
        return [], False
    out2: list[T] = []
    async for page in paginator:
        for item in page.items:
            if len(out2) >= limit:
                return out2, True
            out2.append(item)
        if not page.has_more:
            return out2, False
    return out2, False


class _EmptyPaginator(Paginator[object]):
    def __init__(self) -> None:
        super().__init__(fetch=_empty_sync_fetch, initial_cursor=None)

    def first_page(self) -> Page[object]:
        return Page(items=(), has_more=False)

    def from_cursor(self, cursor: str | None) -> Paginator[object]:
        if cursor is None:
            return self
        return Paginator(self._fetch, initial_cursor=cursor)

    def _iter_pages(self) -> Iterator[Page[object]]:
        return iter(())


class _EmptyAsyncPaginator(AsyncPaginator[object]):
    def __init__(self) -> None:
        super().__init__(fetch=_empty_async_fetch, initial_cursor=None)

    async def first_page(self) -> Page[object]:
        return Page(items=(), has_more=False)

    def from_cursor(self, cursor: str | None) -> AsyncPaginator[object]:
        if cursor is None:
            return self
        return AsyncPaginator(self._fetch, initial_cursor=cursor)

    async def _iter_pages(self) -> AsyncIterator[Page[object]]:
        return
        yield  # pragma: no cover - forces this method to be an async generator


def _empty_sync_fetch(_cursor: str | None) -> Page[object]:
    return Page(items=(), has_more=False)


async def _empty_async_fetch(_cursor: str | None) -> Page[object]:
    return Page(items=(), has_more=False)


__all__ = ["AsyncPaginator", "DecimalMode", "LimitArg", "Page", "Paginator"]
