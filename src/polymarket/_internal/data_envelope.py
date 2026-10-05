from collections.abc import Callable
from typing import TypeVar, cast

from polymarket._internal.request import KeysetPagePayload
from polymarket.errors import UnexpectedResponseError

T = TypeVar("T")


def parse_data_envelope(payload: object, parse: Callable[[object], T]) -> T:
    if not isinstance(payload, dict) or "data" not in payload:
        raise UnexpectedResponseError("Response is missing data")
    return parse(cast(dict[str, object], payload)["data"])


def parse_optional_data_envelope(payload: object, parse: Callable[[object], T]) -> T | None:
    return parse_data_envelope(payload, lambda data: None if data is None else parse(data))


def parse_data_page(
    payload: object, parse_items: Callable[[object], tuple[T, ...]]
) -> KeysetPagePayload[T]:
    if not isinstance(payload, dict):
        raise UnexpectedResponseError("Paginated response must be an object")
    data = cast(dict[str, object], payload)
    pagination = data.get("pagination")
    if not isinstance(data.get("data"), list) or not isinstance(pagination, dict):
        raise UnexpectedResponseError("Paginated response requires data and pagination")
    page = cast(dict[str, object], pagination)
    has_more = page.get("has_more")
    cursor = page.get("next_cursor")
    if not isinstance(has_more, bool) or "next_cursor" not in page:
        raise UnexpectedResponseError("Invalid pagination metadata")
    if cursor is not None and (not isinstance(cursor, str) or not cursor):
        raise UnexpectedResponseError("Invalid next_cursor")
    if has_more != (cursor is not None):
        raise UnexpectedResponseError("has_more and next_cursor disagree")
    return KeysetPagePayload(items=parse_items(data["data"]), server_next_cursor=cursor)
