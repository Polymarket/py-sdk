import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from math import floor
from typing import Literal

from polymarket._internal.request import QueryParamValue
from polymarket.errors import UserInputError
from polymarket.models.types import to_combo_condition_id, to_condition_id, to_market_condition_id

DataParamValue = QueryParamValue | Sequence[str | int] | None


def build_data_params(
    values: Mapping[str, DataParamValue],
) -> dict[str, QueryParamValue]:
    out: dict[str, QueryParamValue] = {}
    for key, value in values.items():
        if value is None:
            continue
        if isinstance(value, str | int | float | bool):
            out[key] = value
            continue
        items = list(value)
        if not items:
            continue
        out[key] = ",".join(str(item) for item in items)
    return out


__all__ = ["DataParamValue", "build_data_params"]


def build_distinct_condition_ids(
    values: str | Sequence[str] | None,
    *,
    grammar: Literal["feed", "market", "combo"],
    max_distinct: int = 20,
) -> tuple[str, ...] | None:
    if values is None:
        return None
    items = (values,) if isinstance(values, str) else tuple(values)
    if not items:
        raise UserInputError("condition_id must be non-empty")
    parser = {
        "feed": to_condition_id,
        "market": to_market_condition_id,
        "combo": to_combo_condition_id,
    }[grammar]
    out: dict[str, str] = {}
    for value in items:
        if type(value) is not str or re.fullmatch(r"0x[0-9a-fA-F]+", value) is None:
            raise UserInputError("condition_id must be a hex string")
        try:
            parsed = parser(value)
        except TypeError as error:
            raise UserInputError(str(error)) from error
        out.setdefault(parsed.lower(), parsed)
    if len(out) > max_distinct:
        raise UserInputError(f"condition_id accepts at most {max_distinct} distinct values")
    return tuple(out.values())


def to_epoch_seconds(value: int | datetime) -> int:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise UserInputError("datetime must be timezone-aware")
        return floor(value.timestamp())
    if isinstance(value, bool) or type(value) is not int:
        raise UserInputError("Expected integer epoch seconds or a timezone-aware datetime")
    return value


def build_event_ids(values: int | Sequence[int] | None) -> tuple[int, ...] | None:
    if values is None:
        return None
    if isinstance(values, str):
        raise UserInputError("event_ids must contain positive 32-bit integers")
    items = (values,) if isinstance(values, int) else tuple(values)
    if not items or any(type(item) is not int or not 0 < item <= 2147483647 for item in items):
        raise UserInputError("event_ids must contain positive 32-bit integers")
    return tuple(dict.fromkeys(items))
