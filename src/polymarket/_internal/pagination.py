from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections.abc import Mapping
from typing import TypeVar, cast

from polymarket._internal.request import PageBasedPagePayload, QueryParamValue, Service
from polymarket.errors import UserInputError
from polymarket.pagination import Page

T = TypeVar("T")

_CURSOR_VERSION = 1
_FINGERPRINT_LEN = 12


def fingerprint_query(base_params: Mapping[str, QueryParamValue] | None) -> str:
    canonical = json.dumps(
        dict(base_params or {}),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:_FINGERPRINT_LEN]


def encode_offset_cursor(
    *,
    service: Service,
    path: str,
    base_params: Mapping[str, QueryParamValue] | None,
    offset: int,
    page_size: int,
) -> str:
    if not path:
        raise UserInputError("path must be a non-empty string.")
    if offset < 0:
        raise UserInputError("offset must be non-negative.")
    if page_size < 1:
        raise UserInputError("page_size must be a positive integer.")
    payload = json.dumps(
        {
            "v": _CURSOR_VERSION,
            "svc": service,
            "p": path,
            "f": fingerprint_query(base_params),
            "o": offset,
            "s": page_size,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return base64.b64encode(payload.encode("utf-8")).decode("ascii")


def decode_offset_cursor(
    cursor: str,
    *,
    expected_service: Service,
    expected_path: str,
    expected_base_params: Mapping[str, QueryParamValue] | None,
) -> tuple[int, int]:
    try:
        decoded = base64.b64decode(cursor, validate=True).decode("utf-8")
        parsed = json.loads(decoded)
    except (binascii.Error, ValueError, UnicodeDecodeError) as error:
        raise UserInputError("Invalid pagination cursor.") from error

    if not isinstance(parsed, dict):
        raise UserInputError("Invalid pagination cursor.")
    payload = cast(dict[str, object], parsed)

    version = payload.get("v")
    if version != _CURSOR_VERSION:
        raise UserInputError(
            f"Unsupported pagination cursor version: {version!r}. Expected {_CURSOR_VERSION}."
        )

    raw_service = payload.get("svc")
    if not isinstance(raw_service, str) or raw_service != expected_service:
        raise UserInputError("Pagination cursor does not belong to this service.")

    raw_path = payload.get("p")
    if not isinstance(raw_path, str) or raw_path != expected_path:
        raise UserInputError("Pagination cursor does not belong to this endpoint.")

    expected_fingerprint = fingerprint_query(expected_base_params)
    raw_fingerprint = payload.get("f")
    if not isinstance(raw_fingerprint, str) or raw_fingerprint != expected_fingerprint:
        raise UserInputError("Pagination cursor was created with different query parameters.")

    raw_offset = payload.get("o")
    raw_page_size = payload.get("s")
    if not isinstance(raw_offset, int) or isinstance(raw_offset, bool) or raw_offset < 0:
        raise UserInputError("Invalid pagination cursor.")
    if not isinstance(raw_page_size, int) or isinstance(raw_page_size, bool) or raw_page_size < 1:
        raise UserInputError("Invalid pagination cursor.")
    return raw_offset, raw_page_size


def compute_offset_page(
    *,
    service: Service,
    path: str,
    base_params: Mapping[str, QueryParamValue] | None,
    offset: int,
    page_size: int,
    items: tuple[T, ...],
) -> Page[T]:
    # Requests ask for exactly page_size rows, so a full page means another
    # page may exist. This costs one extra empty-page request when the total
    # count is an exact multiple of page_size, but cannot silently drop the
    # tail when a server caps or clamps the limit.
    has_more = len(items) >= page_size
    next_cursor = (
        encode_offset_cursor(
            service=service,
            path=path,
            base_params=base_params,
            offset=offset + page_size,
            page_size=page_size,
        )
        if has_more
        else None
    )
    return Page(items=items, has_more=has_more, next_cursor=next_cursor)


def encode_keyset_cursor(
    *,
    service: Service,
    path: str,
    base_params: Mapping[str, QueryParamValue] | None,
    server_cursor: str,
) -> str:
    if not path:
        raise UserInputError("path must be a non-empty string.")
    if not server_cursor:
        raise UserInputError("server_cursor must be a non-empty string.")
    payload = json.dumps(
        {
            "v": _CURSOR_VERSION,
            "svc": service,
            "p": path,
            "f": fingerprint_query(base_params),
            "k": server_cursor,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return base64.b64encode(payload.encode("utf-8")).decode("ascii")


def decode_keyset_cursor(
    cursor: str,
    *,
    expected_service: Service,
    expected_path: str,
    expected_base_params: Mapping[str, QueryParamValue] | None,
) -> str:
    try:
        decoded = base64.b64decode(cursor, validate=True).decode("utf-8")
        parsed = json.loads(decoded)
    except (binascii.Error, ValueError, UnicodeDecodeError) as error:
        raise UserInputError("Invalid pagination cursor.") from error

    if not isinstance(parsed, dict):
        raise UserInputError("Invalid pagination cursor.")
    payload = cast(dict[str, object], parsed)

    version = payload.get("v")
    if version != _CURSOR_VERSION:
        raise UserInputError(
            f"Unsupported pagination cursor version: {version!r}. Expected {_CURSOR_VERSION}."
        )

    raw_service = payload.get("svc")
    if not isinstance(raw_service, str) or raw_service != expected_service:
        raise UserInputError("Pagination cursor does not belong to this service.")

    raw_path = payload.get("p")
    if not isinstance(raw_path, str) or raw_path != expected_path:
        raise UserInputError("Pagination cursor does not belong to this endpoint.")

    expected_fingerprint = fingerprint_query(expected_base_params)
    raw_fingerprint = payload.get("f")
    if not isinstance(raw_fingerprint, str) or raw_fingerprint != expected_fingerprint:
        raise UserInputError("Pagination cursor was created with different query parameters.")

    raw_server = payload.get("k")
    if not isinstance(raw_server, str) or not raw_server:
        raise UserInputError("Invalid pagination cursor.")
    return raw_server


def compute_keyset_page(
    *,
    service: Service,
    path: str,
    base_params: Mapping[str, QueryParamValue] | None,
    items: tuple[T, ...],
    server_next_cursor: str | None,
) -> Page[T]:
    next_cursor = (
        encode_keyset_cursor(
            service=service,
            path=path,
            base_params=base_params,
            server_cursor=server_next_cursor,
        )
        if server_next_cursor is not None
        else None
    )
    return Page(items=items, has_more=next_cursor is not None, next_cursor=next_cursor)


def encode_page_cursor(
    *,
    service: Service,
    path: str,
    base_params: Mapping[str, QueryParamValue] | None,
    page: int,
    page_size: int,
) -> str:
    if not path:
        raise UserInputError("path must be a non-empty string.")
    if page < 1:
        raise UserInputError("page must be a positive integer.")
    if page_size < 1:
        raise UserInputError("page_size must be a positive integer.")
    payload = json.dumps(
        {
            "v": _CURSOR_VERSION,
            "svc": service,
            "p": path,
            "f": fingerprint_query(base_params),
            "pg": page,
            "s": page_size,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return base64.b64encode(payload.encode("utf-8")).decode("ascii")


def decode_page_cursor(
    cursor: str,
    *,
    expected_service: Service,
    expected_path: str,
    expected_base_params: Mapping[str, QueryParamValue] | None,
) -> tuple[int, int]:
    try:
        decoded = base64.b64decode(cursor, validate=True).decode("utf-8")
        parsed = json.loads(decoded)
    except (binascii.Error, ValueError, UnicodeDecodeError) as error:
        raise UserInputError("Invalid pagination cursor.") from error

    if not isinstance(parsed, dict):
        raise UserInputError("Invalid pagination cursor.")
    payload = cast(dict[str, object], parsed)

    version = payload.get("v")
    if version != _CURSOR_VERSION:
        raise UserInputError(
            f"Unsupported pagination cursor version: {version!r}. Expected {_CURSOR_VERSION}."
        )

    raw_service = payload.get("svc")
    if not isinstance(raw_service, str) or raw_service != expected_service:
        raise UserInputError("Pagination cursor does not belong to this service.")

    raw_path = payload.get("p")
    if not isinstance(raw_path, str) or raw_path != expected_path:
        raise UserInputError("Pagination cursor does not belong to this endpoint.")

    expected_fingerprint = fingerprint_query(expected_base_params)
    raw_fingerprint = payload.get("f")
    if not isinstance(raw_fingerprint, str) or raw_fingerprint != expected_fingerprint:
        raise UserInputError("Pagination cursor was created with different query parameters.")

    raw_page = payload.get("pg")
    raw_page_size = payload.get("s")
    if not isinstance(raw_page, int) or isinstance(raw_page, bool) or raw_page < 1:
        raise UserInputError("Invalid pagination cursor.")
    if not isinstance(raw_page_size, int) or isinstance(raw_page_size, bool) or raw_page_size < 1:
        raise UserInputError("Invalid pagination cursor.")
    return raw_page, raw_page_size


def compute_page_based_page(
    *,
    service: Service,
    path: str,
    base_params: Mapping[str, QueryParamValue] | None,
    page: int,
    page_size: int,
    payload: PageBasedPagePayload[T],
) -> Page[T]:
    next_cursor = (
        encode_page_cursor(
            service=service,
            path=path,
            base_params=base_params,
            page=page + 1,
            page_size=page_size,
        )
        if payload.has_more
        else None
    )
    return Page(
        items=(payload.items,),
        has_more=payload.has_more,
        next_cursor=next_cursor,
        total_count=payload.total_count,
    )


__all__ = [
    "compute_keyset_page",
    "compute_offset_page",
    "compute_page_based_page",
    "decode_keyset_cursor",
    "decode_offset_cursor",
    "decode_page_cursor",
    "encode_keyset_cursor",
    "encode_offset_cursor",
    "encode_page_cursor",
    "fingerprint_query",
]
