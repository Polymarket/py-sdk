from collections.abc import Callable, Sequence
from typing import Any, TypeVar, cast

from polymarket._internal.request import KeysetPagePayload, KeysetPaginatedSpec, QueryParamValue
from polymarket.errors import UnexpectedResponseError, UserInputError
from polymarket.models import ComboMarket

_T = TypeVar("_T")


def _make_keyset_parser(
    items_key: str,
    parse_item: Callable[[object], _T],
) -> Callable[[object], KeysetPagePayload[_T]]:
    def parse(data: object) -> KeysetPagePayload[_T]:
        if not isinstance(data, dict):
            raise UnexpectedResponseError("Expected an object response for keyset pagination.")
        data_dict = cast(dict[str, Any], data)

        if items_key not in data_dict:
            raise UnexpectedResponseError(
                f"Keyset response is missing required '{items_key}' field."
            )
        raw = data_dict[items_key]
        if not isinstance(raw, list):
            raise UnexpectedResponseError(f"Expected '{items_key}' to be an array.")
        items_list = cast(list[Any], raw)
        items = tuple(parse_item(item) for item in items_list)

        if "next_cursor" not in data_dict:
            server_cursor: str | None = None
        else:
            nc = data_dict["next_cursor"]
            if nc is None:
                server_cursor = None
            elif isinstance(nc, str):
                if not nc:
                    raise UnexpectedResponseError(
                        "'next_cursor' must be a non-empty string when present."
                    )
                server_cursor = nc
            else:
                raise UnexpectedResponseError(
                    f"'next_cursor' must be a string when present, got {type(nc).__name__}."
                )

        return KeysetPagePayload(items=items, server_next_cursor=server_cursor)

    return parse


def _add_optional_comma_seq(
    params: dict[str, QueryParamValue],
    key: str,
    value: str | Sequence[str] | None,
) -> None:
    if value is None:
        return
    if isinstance(value, bytes):
        raise UserInputError(f"{key} does not accept bytes")
    if isinstance(value, str):
        if value:
            params[key] = value
        return
    coerced = tuple(value)
    if coerced:
        params[key] = ",".join(coerced)


def list_combo_markets_spec(
    *,
    exclude: str | Sequence[str] | None = None,
) -> KeysetPaginatedSpec[ComboMarket]:
    params: dict[str, QueryParamValue] = {}
    _add_optional_comma_seq(params, "exclude", exclude)

    return KeysetPaginatedSpec(
        path="/v1/combos/markets",
        parse_page=_make_keyset_parser("markets", ComboMarket.parse_response),
        base_params=params or None,
        cursor_param="cursor",
        max_page_size=100,
    )


__all__ = ["list_combo_markets_spec"]
