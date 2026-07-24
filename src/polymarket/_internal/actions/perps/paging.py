"""Cursor and timestamp helpers for Perps pagination."""

import base64
import binascii
import json
from collections.abc import Collection
from datetime import datetime
from typing import Any, cast

from polymarket.errors import UserInputError

ONE_DAY_MS = 24 * 60 * 60 * 1000
NINETY_DAYS_MS = 90 * ONE_DAY_MS

_INTERVAL_MS: dict[str, int] = {
    "1s": 1000,
    "1m": 60 * 1000,
    "5m": 5 * 60 * 1000,
    "15m": 15 * 60 * 1000,
    "1h": 60 * 60 * 1000,
    "4h": 4 * 60 * 60 * 1000,
    "1d": ONE_DAY_MS,
    "1w": 7 * ONE_DAY_MS,
}

_INVALID_CURSOR = "Invalid Perps pagination cursor"


def interval_ms(interval: str) -> int:
    return _INTERVAL_MS[interval]


def to_epoch_ms(name: str, value: datetime | int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return int(value.timestamp() * 1000)
    if isinstance(value, bool) or not isinstance(value, int):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise UserInputError(f"{name} must be a datetime or epoch-ms int")
    if value < 0:
        raise UserInputError(f"{name} must be non-negative")
    return value


def encode_perps_cursor(state: dict[str, Any]) -> str:
    return base64.b64encode(json.dumps(state, separators=(",", ":")).encode("utf-8")).decode(
        "ascii"
    )


def as_json_dict(value: object) -> dict[str, Any] | None:
    """Return the value as a JSON object dict, or None when it is not one."""
    if isinstance(value, dict):
        return cast("dict[str, Any]", value)
    return None


def _invalid_cursor() -> UserInputError:
    return UserInputError(_INVALID_CURSOR)


def decode_perps_cursor(cursor: str, *, kind: str) -> dict[str, Any]:
    try:
        decoded = json.loads(base64.b64decode(cursor, validate=True))
    except (binascii.Error, TypeError, ValueError, UnicodeDecodeError) as error:
        raise _invalid_cursor() from error
    state = as_json_dict(decoded)
    if state is None or state.get("kind") != kind:
        raise _invalid_cursor()
    return state


def decode_perps_candles_cursor(cursor: str, *, intervals: Collection[str]) -> dict[str, Any]:
    state = decode_perps_cursor(cursor, kind="perpsCandles")
    _require_non_negative_int(state, "instrument_id")
    _require_allowed_str(state, "interval", intervals)
    _require_non_negative_int(state, "start_timestamp")
    _require_non_negative_int(state, "end_timestamp")
    return state


def decode_perps_funding_cursor(cursor: str) -> dict[str, Any]:
    state = decode_perps_cursor(cursor, kind="perpsFundingHistory")
    _require_non_negative_int(state, "instrument_id")
    _require_non_negative_int(state, "start_timestamp")
    _require_non_negative_int(state, "end_timestamp")
    return state


def decode_perps_trades_cursor(cursor: str) -> dict[str, Any]:
    state = decode_perps_cursor(cursor, kind="perpsTrades")
    _require_non_negative_int(state, "instrument_id")
    _require_non_negative_int(state, "start_timestamp")
    _require_non_negative_int(state, "end_timestamp")
    _require_non_negative_int_list(state, "seen_trade_ids")
    return state


def decode_perps_descending_account_cursor(
    cursor: str, *, kind: str, fund_statuses: Collection[str]
) -> dict[str, Any]:
    state = decode_perps_cursor(cursor, kind=kind)
    _require_non_negative_int(state, "start_timestamp")
    _require_non_negative_int(state, "end_timestamp")
    _require_str_list(state, "seen_keys")
    _allow_optional_non_negative_int(state, "instrument_id")
    _allow_optional_allowed_str(state, "deposit_status", fund_statuses)
    _allow_optional_allowed_str(state, "withdrawal_status", fund_statuses)
    _allow_optional_str(state, "hash")
    return state


def decode_perps_ascending_account_cursor(
    cursor: str, *, kind: str, intervals: Collection[str]
) -> dict[str, Any]:
    state = decode_perps_cursor(cursor, kind=kind)
    _require_allowed_str(state, "interval", intervals)
    _require_non_negative_int(state, "start_timestamp")
    _require_non_negative_int(state, "end_timestamp")
    return state


def _require_non_negative_int(state: dict[str, Any], key: str) -> None:
    value = state.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _invalid_cursor()


def _allow_optional_non_negative_int(state: dict[str, Any], key: str) -> None:
    value = state.get(key)
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _invalid_cursor()


def _require_allowed_str(state: dict[str, Any], key: str, allowed_values: Collection[str]) -> None:
    value = state.get(key)
    if not isinstance(value, str) or value not in allowed_values:
        raise _invalid_cursor()


def _allow_optional_allowed_str(
    state: dict[str, Any], key: str, allowed_values: Collection[str]
) -> None:
    value = state.get(key)
    if value is None:
        return
    if not isinstance(value, str) or value not in allowed_values:
        raise _invalid_cursor()


def _allow_optional_str(state: dict[str, Any], key: str) -> None:
    value = state.get(key)
    if value is None:
        return
    if not isinstance(value, str):
        raise _invalid_cursor()


def _require_non_negative_int_list(state: dict[str, Any], key: str) -> None:
    value = state.get(key)
    if not isinstance(value, list):
        raise _invalid_cursor()
    items = cast("list[object]", value)
    if any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in items):
        raise _invalid_cursor()


def _require_str_list(state: dict[str, Any], key: str) -> None:
    value = state.get(key)
    if not isinstance(value, list):
        raise _invalid_cursor()
    items = cast("list[object]", value)
    if any(not isinstance(item, str) for item in items):
        raise _invalid_cursor()


def parse_data_envelope(payload: object) -> tuple[list[object], bool]:
    from polymarket.errors import UnexpectedResponseError

    envelope = as_json_dict(payload)
    if envelope is None:
        raise UnexpectedResponseError("Perps list response did not match expected shape")
    data = envelope.get("data")
    more = envelope.get("more")
    if not isinstance(data, list) or not isinstance(more, bool):
        raise UnexpectedResponseError("Perps list response did not match expected shape")
    return cast("list[object]", data), more


__all__ = [
    "NINETY_DAYS_MS",
    "ONE_DAY_MS",
    "as_json_dict",
    "decode_perps_ascending_account_cursor",
    "decode_perps_candles_cursor",
    "decode_perps_cursor",
    "decode_perps_descending_account_cursor",
    "decode_perps_funding_cursor",
    "decode_perps_trades_cursor",
    "encode_perps_cursor",
    "interval_ms",
    "parse_data_envelope",
    "to_epoch_ms",
]
