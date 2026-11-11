from __future__ import annotations

from typing import TypeVar, assert_never

from polymarket._internal.context import AsyncClientContext, SyncClientContext
from polymarket._internal.pagination import (
    compute_keyset_page,
    compute_offset_page,
    compute_page_based_page,
    decode_keyset_cursor,
    decode_offset_cursor,
    decode_page_cursor,
)
from polymarket._internal.request import (
    KeysetPaginatedSpec,
    OffsetPaginatedSpec,
    PageBasedSpec,
    QueryParamValue,
    RequestSpec,
)
from polymarket.errors import PaginationLimitError, UserInputError
from polymarket.pagination import AsyncPaginator, Page, Paginator

T = TypeVar("T")


def sync_dispatch(ctx: SyncClientContext, spec: RequestSpec[T]) -> T:
    transport = ctx.predictions
    match spec.method:
        case "GET":
            payload = transport.get_json(spec.path, params=spec.params)
        case _ as unreachable:
            assert_never(unreachable)
    return spec.parse(payload)


async def async_dispatch(ctx: AsyncClientContext, spec: RequestSpec[T]) -> T:
    transport = ctx.predictions
    match spec.method:
        case "GET":
            payload = await transport.get_json(spec.path, params=spec.params)
        case _ as unreachable:
            assert_never(unreachable)
    return spec.parse(payload)


def _check_offset_window(spec: OffsetPaginatedSpec[T], offset: int, page_size: int) -> None:
    # A cursor carries the offset and page size it was minted with, so both
    # are re-checked here rather than trusting the caller-supplied page size
    # alone. The service rejects offsets past its cap; fail before the request
    # so the pages already returned stay valid and no round trip is wasted.
    if spec.max_page_size is not None and page_size > spec.max_page_size:
        raise UserInputError(f"page_size must be at most {spec.max_page_size}.")
    if spec.max_offset is not None and offset > spec.max_offset:
        raise PaginationLimitError(
            f"Pagination reached the deepest page served for {spec.path} (offset "
            f"{spec.max_offset}); whether more items exist cannot be established."
        )


def sync_paginate_offset(
    ctx: SyncClientContext,
    spec: OffsetPaginatedSpec[T],
    *,
    page_size: int,
    initial_cursor: str | None = None,
) -> Paginator[T]:
    if page_size < 1:
        raise UserInputError("page_size must be a positive integer.")
    if spec.max_page_size is not None and page_size > spec.max_page_size:
        raise UserInputError(f"page_size must be at most {spec.max_page_size}.")
    transport = ctx.predictions

    def fetch(cursor: str | None) -> Page[T]:
        offset, effective_size = (
            decode_offset_cursor(
                cursor,
                expected_path=spec.path,
                expected_base_params=spec.base_params,
            )
            if cursor is not None
            else (0, page_size)
        )
        _check_offset_window(spec, offset, effective_size)
        params: dict[str, QueryParamValue] = {
            **(spec.base_params or {}),
            "limit": effective_size,
            "offset": offset,
        }
        payload = transport.get_json(spec.path, params=params)
        items = spec.parse_items(payload)
        return compute_offset_page(
            path=spec.path,
            base_params=spec.base_params,
            offset=offset,
            page_size=effective_size,
            items=items,
            page_fill=spec.page_fill,
            max_offset=spec.max_offset,
        )

    return Paginator(fetch=fetch, initial_cursor=initial_cursor)


def async_paginate_offset(
    ctx: AsyncClientContext,
    spec: OffsetPaginatedSpec[T],
    *,
    page_size: int,
    initial_cursor: str | None = None,
) -> AsyncPaginator[T]:
    if page_size < 1:
        raise UserInputError("page_size must be a positive integer.")
    if spec.max_page_size is not None and page_size > spec.max_page_size:
        raise UserInputError(f"page_size must be at most {spec.max_page_size}.")
    transport = ctx.predictions

    async def fetch(cursor: str | None) -> Page[T]:
        offset, effective_size = (
            decode_offset_cursor(
                cursor,
                expected_path=spec.path,
                expected_base_params=spec.base_params,
            )
            if cursor is not None
            else (0, page_size)
        )
        _check_offset_window(spec, offset, effective_size)
        params: dict[str, QueryParamValue] = {
            **(spec.base_params or {}),
            "limit": effective_size,
            "offset": offset,
        }
        payload = await transport.get_json(spec.path, params=params)
        items = spec.parse_items(payload)
        return compute_offset_page(
            path=spec.path,
            base_params=spec.base_params,
            offset=offset,
            page_size=effective_size,
            items=items,
            page_fill=spec.page_fill,
            max_offset=spec.max_offset,
        )

    return AsyncPaginator(fetch=fetch, initial_cursor=initial_cursor)


def sync_paginate_keyset(
    ctx: SyncClientContext,
    spec: KeysetPaginatedSpec[T],
    *,
    page_size: int,
    initial_cursor: str | None = None,
) -> Paginator[T]:
    if type(page_size) is not int or page_size < 1:
        raise UserInputError("page_size must be a positive integer.")
    if spec.max_page_size is not None and page_size > spec.max_page_size:
        raise UserInputError(f"page_size must be at most {spec.max_page_size}.")
    transport = ctx.predictions

    def fetch(cursor: str | None) -> Page[T]:
        server_cursor = (
            decode_keyset_cursor(
                cursor,
                expected_path=spec.path,
                expected_base_params=spec.base_params,
            )
            if cursor is not None
            else None
        )
        params: dict[str, QueryParamValue] = {
            **(spec.base_params or {}),
            "limit": page_size,
        }
        if server_cursor is not None:
            params[spec.cursor_param] = server_cursor
        payload = transport.get_json(spec.path, params=params)
        keyset_page = spec.parse_page(payload)
        return compute_keyset_page(
            path=spec.path,
            base_params=spec.base_params,
            items=keyset_page.items,
            server_next_cursor=keyset_page.server_next_cursor,
        )

    return Paginator(fetch=fetch, initial_cursor=initial_cursor)


def async_paginate_keyset(
    ctx: AsyncClientContext,
    spec: KeysetPaginatedSpec[T],
    *,
    page_size: int,
    initial_cursor: str | None = None,
) -> AsyncPaginator[T]:
    if type(page_size) is not int or page_size < 1:
        raise UserInputError("page_size must be a positive integer.")
    if spec.max_page_size is not None and page_size > spec.max_page_size:
        raise UserInputError(f"page_size must be at most {spec.max_page_size}.")
    transport = ctx.predictions

    async def fetch(cursor: str | None) -> Page[T]:
        server_cursor = (
            decode_keyset_cursor(
                cursor,
                expected_path=spec.path,
                expected_base_params=spec.base_params,
            )
            if cursor is not None
            else None
        )
        params: dict[str, QueryParamValue] = {
            **(spec.base_params or {}),
            "limit": page_size,
        }
        if server_cursor is not None:
            params[spec.cursor_param] = server_cursor
        payload = await transport.get_json(spec.path, params=params)
        keyset_page = spec.parse_page(payload)
        return compute_keyset_page(
            path=spec.path,
            base_params=spec.base_params,
            items=keyset_page.items,
            server_next_cursor=keyset_page.server_next_cursor,
        )

    return AsyncPaginator(fetch=fetch, initial_cursor=initial_cursor)


def sync_paginate_page_based(
    ctx: SyncClientContext,
    spec: PageBasedSpec[T],
    *,
    page_size: int,
    initial_page: int = 1,
    initial_cursor: str | None = None,
) -> Paginator[T]:
    if page_size < 1:
        raise UserInputError("page_size must be a positive integer.")
    if initial_page < 1:
        raise UserInputError("page must be a positive integer.")
    transport = ctx.predictions

    def fetch(cursor: str | None) -> Page[T]:
        page, effective_size = (
            decode_page_cursor(
                cursor,
                expected_path=spec.path,
                expected_base_params=spec.base_params,
            )
            if cursor is not None
            else (initial_page, page_size)
        )
        params: dict[str, QueryParamValue] = {
            **(spec.base_params or {}),
            "page": page,
            "limit_per_type": effective_size,
        }
        payload = transport.get_json(spec.path, params=params)
        page_payload = spec.parse_page(payload)
        return compute_page_based_page(
            path=spec.path,
            base_params=spec.base_params,
            page=page,
            page_size=effective_size,
            payload=page_payload,
        )

    return Paginator(fetch=fetch, initial_cursor=initial_cursor)


def async_paginate_page_based(
    ctx: AsyncClientContext,
    spec: PageBasedSpec[T],
    *,
    page_size: int,
    initial_page: int = 1,
    initial_cursor: str | None = None,
) -> AsyncPaginator[T]:
    if page_size < 1:
        raise UserInputError("page_size must be a positive integer.")
    if initial_page < 1:
        raise UserInputError("page must be a positive integer.")
    transport = ctx.predictions

    async def fetch(cursor: str | None) -> Page[T]:
        page, effective_size = (
            decode_page_cursor(
                cursor,
                expected_path=spec.path,
                expected_base_params=spec.base_params,
            )
            if cursor is not None
            else (initial_page, page_size)
        )
        params: dict[str, QueryParamValue] = {
            **(spec.base_params or {}),
            "page": page,
            "limit_per_type": effective_size,
        }
        payload = await transport.get_json(spec.path, params=params)
        page_payload = spec.parse_page(payload)
        return compute_page_based_page(
            path=spec.path,
            base_params=spec.base_params,
            page=page,
            page_size=effective_size,
            payload=page_payload,
        )

    return AsyncPaginator(fetch=fetch, initial_cursor=initial_cursor)


__all__ = [
    "async_dispatch",
    "async_paginate_keyset",
    "async_paginate_offset",
    "async_paginate_page_based",
    "sync_dispatch",
    "sync_paginate_keyset",
    "sync_paginate_offset",
    "sync_paginate_page_based",
]
