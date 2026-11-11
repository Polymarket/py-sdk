from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from collections.abc import Mapping
from typing import TypeVar, cast

from polymarket._internal.request import PageBasedPagePayload, QueryParamValue
from polymarket.errors import UserInputError
from polymarket.pagination import Page

T = TypeVar("T")

_CURSOR_VERSION = 1
_FINGERPRINT_LEN = 12
_CURSOR_SERVICE = "predictions"

# Cursors saved before every listing was served from one endpoint resume the
# same listing. Keys are current listing paths; values are the earlier
# (service, path) a cursor carries.
_LEGACY_CURSOR_ENDPOINTS: Mapping[str, tuple[str, str]] = {
    "/v1/trades": ("data", "/v2/trades"),
    "/v1/activity": ("data", "/v2/activity"),
    "/v1/activity/combos": ("data", "/v2/activity/combos"),
    "/v1/positions": ("data", "/v2/positions"),
    "/v1/positions/combos": ("data", "/v2/positions/combos"),
    "/v1/markets/holders": ("data", "/v2/holders"),
    "/v1/pricing/history/aggregated": ("data", "/v2/prices-history"),
    "/v1/leaderboards/traders": ("data", "/v2/leaderboard"),
    "/v1/leaderboards/biggest-winners": ("data", "/v2/biggest-winners"),
    "/v1/builders/leaderboard": ("data", "/v2/builders/leaderboard"),
    "/v1/events": ("gamma", "/events/keyset"),
    "/v1/markets": ("gamma", "/markets/keyset"),
    "/v1/comments": ("gamma", "/comments/keyset"),
    "/v1/series": ("gamma", "/series"),
    "/v1/tags": ("gamma", "/tags"),
    "/v1/teams": ("gamma", "/teams"),
    "/v1/public-search": ("gamma", "/public-search"),
    "/v1/combos/markets": ("rfq", "/v1/rfq/combo-markets"),
}
_USER_COMMENTS_PATH = re.compile(r"^/v1/users/([^/]+)/comments$")


def _legacy_cursor_endpoint(path: str) -> tuple[str, str] | None:
    user_comments = _USER_COMMENTS_PATH.match(path)
    if user_comments is not None:
        return ("gamma", f"/comments/user_address/{user_comments.group(1)}")
    return _LEGACY_CURSOR_ENDPOINTS.get(path)


def _check_cursor_endpoint(payload: Mapping[str, object], expected_path: str) -> None:
    endpoint = (payload.get("svc"), payload.get("p"))
    if endpoint == (_CURSOR_SERVICE, expected_path):
        return
    if endpoint == _legacy_cursor_endpoint(expected_path):
        return
    raise UserInputError("Pagination cursor does not belong to this endpoint.")


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
            "svc": _CURSOR_SERVICE,
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

    _check_cursor_endpoint(payload, expected_path)

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
    path: str,
    base_params: Mapping[str, QueryParamValue] | None,
    offset: int,
    page_size: int,
    items: tuple[T, ...],
    max_offset: int | None = None,
) -> Page[T]:
    # Requests ask for exactly page_size rows, so a full page means another
    # page may exist. This costs one extra empty-page request when the total
    # count is an exact multiple of page_size, but cannot silently drop the
    # tail when a server caps or clamps the limit.
    has_more = len(items) >= page_size
    next_cursor = (
        encode_offset_cursor(
            path=path,
            base_params=base_params,
            offset=offset + page_size,
            page_size=page_size,
        )
        if has_more
        else None
    )
    return Page(
        items=items,
        has_more=has_more,
        next_cursor=next_cursor,
        limit_reached=has_more and max_offset is not None and offset + page_size > max_offset,
    )


def encode_keyset_cursor(
    *,
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
            "svc": _CURSOR_SERVICE,
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

    _check_cursor_endpoint(payload, expected_path)

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
    path: str,
    base_params: Mapping[str, QueryParamValue] | None,
    items: tuple[T, ...],
    server_next_cursor: str | None,
) -> Page[T]:
    next_cursor = (
        encode_keyset_cursor(
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
            "svc": _CURSOR_SERVICE,
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

    _check_cursor_endpoint(payload, expected_path)

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
    path: str,
    base_params: Mapping[str, QueryParamValue] | None,
    page: int,
    page_size: int,
    payload: PageBasedPagePayload[T],
) -> Page[T]:
    next_cursor = (
        encode_page_cursor(
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
