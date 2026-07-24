from typing import cast

from pydantic import TypeAdapter, ValidationError

from polymarket._internal.actions._cursor import (
    next_cursor_or_none,
    validate_cursor,
)
from polymarket._internal.request import QueryParamValue
from polymarket._internal.validation import require_nonempty, validate_builder_code
from polymarket.errors import UnexpectedResponseError
from polymarket.models.clob import BuilderTrade
from polymarket.pagination import Page

_BuilderTradesAdapter = TypeAdapter(tuple[BuilderTrade, ...])


def build_list_builder_trades_request(
    *,
    builder_code: str,
    market: str | None = None,
    token_id: str | None = None,
    id: str | None = None,
    after: str | None = None,
    before: str | None = None,
    cursor: str | None = None,
) -> tuple[str, dict[str, QueryParamValue]]:
    params: dict[str, QueryParamValue] = {
        "builder_code": validate_builder_code(builder_code),
    }
    if market is not None:
        params["market"] = require_nonempty("market", market)
    if token_id is not None:
        params["asset_id"] = require_nonempty("token_id", token_id)
    if id is not None:
        params["id"] = require_nonempty("id", id)
    if after is not None:
        params["after"] = require_nonempty("after", after)
    if before is not None:
        params["before"] = require_nonempty("before", before)
    validated_cursor = validate_cursor(cursor)
    if validated_cursor is not None:
        params["next_cursor"] = validated_cursor
    return "/builder/trades", params


def parse_builder_trades_page(data: object) -> Page[BuilderTrade]:
    if not isinstance(data, dict):
        raise UnexpectedResponseError("builder trades response did not match expected shape")
    payload = cast(dict[str, object], data)
    try:
        items = _BuilderTradesAdapter.validate_python(payload.get("data"))
    except ValidationError as error:
        raise UnexpectedResponseError("builder trades response items malformed") from error
    raw_next_cursor = payload.get("next_cursor")
    if not isinstance(raw_next_cursor, str):
        raise UnexpectedResponseError("builder trades response missing next_cursor")
    next_cursor = next_cursor_or_none(raw_next_cursor)
    return Page(
        items=items,
        has_more=next_cursor is not None,
        next_cursor=next_cursor,
    )


__all__ = ["build_list_builder_trades_request", "parse_builder_trades_page"]
