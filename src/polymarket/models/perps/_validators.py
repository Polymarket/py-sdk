from datetime import UTC, datetime
from decimal import Decimal


def _coerce_decimalish(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, bool):
        msg = f"expected decimal-ish value, got bool {value!r}"
        raise ValueError(msg)
    if isinstance(value, Decimal | str):
        return value
    if isinstance(value, int | float):
        return str(value)
    msg = f"expected decimal-ish value, got {type(value).__name__}"
    raise ValueError(msg)


def _parse_epoch_ms(value: object) -> object:
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, bool) or not isinstance(value, int):
        msg = f"expected epoch-ms timestamp, got {type(value).__name__}"
        raise ValueError(msg)
    try:
        return datetime.fromtimestamp(value / 1000, tz=UTC)
    except (OverflowError, OSError, ValueError) as error:
        msg = f"invalid epoch-ms timestamp: {value!r}"
        raise ValueError(msg) from error


def _require_epoch_ms(value: object) -> object:
    parsed = _parse_epoch_ms(value)
    if parsed is None:
        msg = "expected epoch-ms timestamp, got None"
        raise ValueError(msg)
    return parsed


def _parse_tx_hash(value: object) -> object:
    if value in ("", "0x"):
        return None
    return value


__all__ = [
    "_coerce_decimalish",
    "_parse_epoch_ms",
    "_parse_tx_hash",
    "_require_epoch_ms",
]
