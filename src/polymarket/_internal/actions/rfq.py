from collections.abc import Sequence
from typing import cast

from polymarket._internal.request import KeysetPagePayload, KeysetPaginatedSpec, QueryParamValue
from polymarket.errors import UnexpectedResponseError, UserInputError
from polymarket.models.rfq import ComboMarket
from polymarket.models.types import validate_ctf_condition_id

_MAX_COMBO_MARKETS_PAGE_SIZE = 100


def list_combo_markets_spec(
    *,
    exclude: str | Sequence[str] | None = None,
) -> KeysetPaginatedSpec[ComboMarket]:
    params: dict[str, QueryParamValue] = {}
    excluded = _coerce_excluded_condition_ids(exclude)
    if excluded:
        params["exclude"] = ",".join(excluded)

    return KeysetPaginatedSpec(
        service="rfq",
        path="/v1/rfq/combo-markets",
        parse_page=_parse_combo_markets_page,
        base_params=params or None,
        cursor_param="cursor",
    )


def validate_combo_markets_page_size(page_size: int) -> None:
    if type(page_size) is not int:
        raise UserInputError("page_size must be an int.")
    if page_size < 1 or page_size > _MAX_COMBO_MARKETS_PAGE_SIZE:
        raise UserInputError(f"page_size must be between 1 and {_MAX_COMBO_MARKETS_PAGE_SIZE}.")


def _parse_combo_markets_page(data: object) -> KeysetPagePayload[ComboMarket]:
    if not isinstance(data, dict):
        raise UnexpectedResponseError("Combo market response did not match expected shape")
    payload = cast(dict[str, object], data)

    raw_markets = payload.get("markets")
    if not isinstance(raw_markets, list):
        raise UnexpectedResponseError("Combo market response is missing markets array")
    market_items = cast(list[object], raw_markets)
    markets = tuple(ComboMarket.parse_response(item) for item in market_items)

    raw_cursor = payload.get("next_cursor")
    if raw_cursor is None:
        next_cursor = None
    elif isinstance(raw_cursor, str) and raw_cursor:
        next_cursor = raw_cursor
    else:
        raise UnexpectedResponseError("Combo market next_cursor did not match expected shape")

    return KeysetPagePayload(items=markets, server_next_cursor=next_cursor)


def _coerce_excluded_condition_ids(exclude: str | Sequence[str] | None) -> tuple[str, ...]:
    if exclude is None:
        return ()
    if isinstance(exclude, str):
        return (validate_ctf_condition_id(exclude),)
    if isinstance(exclude, bytes):
        raise UserInputError("exclude does not accept bytes")
    return tuple(validate_ctf_condition_id(value) for value in exclude)


__all__ = ["list_combo_markets_spec", "validate_combo_markets_page_size"]
