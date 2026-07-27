from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Annotated

from pydantic import BeforeValidator

# Re-exported under the historical private name for the CLOB model modules.
from polymarket.models._validators import (  # noqa: F401
    DecimalFromString as _DecimalFromString,  # pyright: ignore[reportUnusedImport]
)


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


def _coerce_optional_decimalish(value: object) -> object:
    """Coerce a decimal-ish value, treating an empty string as absent.

    Streaming messages use ``""`` for optional decimal fields that have no
    value (for example ``fee_rate_bps`` on a trade with no fee), so an empty
    string maps to ``None`` instead of failing decimal parsing.
    """
    if value == "":
        return None
    return _coerce_decimalish(value)


def _parse_epoch_ms_timestamp(value: object) -> object:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        msg = f"expected epoch-ms timestamp string, got {type(value).__name__}"
        raise ValueError(msg)
    # Unsigned digits only; int() alone would accept "-1", "+1", " 1 ", etc.
    if not value.isdecimal():
        msg = f"invalid epoch-ms timestamp: {value!r}"
        raise ValueError(msg)
    ms = int(value)
    try:
        return datetime.fromtimestamp(ms / 1000, tz=UTC)
    except (OverflowError, OSError, ValueError) as error:
        msg = f"invalid epoch-ms timestamp: {value!r}"
        raise ValueError(msg) from error


def _parse_epoch_ms_or_iso_timestamp(value: object) -> object:
    """Permissive timestamp parser.

    Accepts ``int`` (epoch ms), digit-string (epoch ms), and ISO-8601 strings.
    Returns ``datetime`` (UTC-aware for epoch inputs; the string's own tz for
    ISO inputs). Empty string / None / boolean / unknown shapes all surface
    via ``ValueError``.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, bool):
        msg = f"expected timestamp, got bool {value!r}"
        raise ValueError(msg)
    if isinstance(value, int):
        try:
            return datetime.fromtimestamp(value / 1000, tz=UTC)
        except (OverflowError, OSError, ValueError) as error:
            msg = f"invalid epoch-ms timestamp: {value!r}"
            raise ValueError(msg) from error
    if isinstance(value, str):
        if value.isdecimal():
            ms = int(value)
            try:
                return datetime.fromtimestamp(ms / 1000, tz=UTC)
            except (OverflowError, OSError, ValueError) as error:
                msg = f"invalid epoch-ms timestamp: {value!r}"
                raise ValueError(msg) from error
        try:
            return datetime.fromisoformat(value)
        except ValueError as error:
            msg = f"invalid timestamp: {value!r}"
            raise ValueError(msg) from error
    msg = f"expected epoch-ms or ISO timestamp, got {type(value).__name__}"
    raise ValueError(msg)


_EPOCH_MS_THRESHOLD = 10**11


def _parse_epoch_seconds_or_ms_timestamp(value: object) -> object:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, bool):
        msg = f"expected epoch timestamp, got bool {value!r}"
        raise ValueError(msg)
    if isinstance(value, int):
        magnitude = value
    elif isinstance(value, str):
        if not value.isdecimal():
            msg = f"invalid epoch timestamp: {value!r}"
            raise ValueError(msg)
        magnitude = int(value)
    else:
        msg = f"expected epoch timestamp, got {type(value).__name__}"
        raise ValueError(msg)
    seconds = magnitude / 1000 if magnitude >= _EPOCH_MS_THRESHOLD else magnitude
    try:
        return datetime.fromtimestamp(seconds, tz=UTC)
    except (OverflowError, OSError, ValueError) as error:
        msg = f"invalid epoch timestamp: {value!r}"
        raise ValueError(msg) from error


def _parse_epoch_or_iso_timestamp(value: object) -> object:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, bool):
        msg = f"expected timestamp, got bool {value!r}"
        raise ValueError(msg)
    if isinstance(value, int):
        magnitude = value
    elif isinstance(value, str):
        if value.isdecimal():
            magnitude = int(value)
        else:
            try:
                parsed = datetime.fromisoformat(value)
            except ValueError as error:
                msg = f"invalid timestamp: {value!r}"
                raise ValueError(msg) from error
            # Assume a naive ISO timestamp is UTC, matching how epoch inputs are
            # parsed (tz=UTC) and the prior account-model behavior.
            return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    else:
        msg = f"expected epoch or ISO timestamp, got {type(value).__name__}"
        raise ValueError(msg)
    seconds = magnitude / 1000 if magnitude >= _EPOCH_MS_THRESHOLD else magnitude
    try:
        return datetime.fromtimestamp(seconds, tz=UTC)
    except (OverflowError, OSError, ValueError) as error:
        msg = f"invalid epoch timestamp: {value!r}"
        raise ValueError(msg) from error


def _require_epoch_or_iso_timestamp(value: object) -> object:
    parsed = _parse_epoch_or_iso_timestamp(value)
    if parsed is None:
        msg = f"expected timestamp, got {value!r}"
        raise ValueError(msg)
    return parsed


def _parse_epoch_seconds_timestamp(value: object) -> object:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, bool):
        msg = f"expected epoch-seconds timestamp, got bool {value!r}"
        raise ValueError(msg)
    if isinstance(value, int):
        seconds = value
    elif isinstance(value, str):
        if not value.isdecimal():
            msg = f"invalid epoch-seconds timestamp: {value!r}"
            raise ValueError(msg)
        seconds = int(value)
    else:
        msg = f"expected epoch-seconds timestamp, got {type(value).__name__}"
        raise ValueError(msg)
    try:
        return datetime.fromtimestamp(seconds, tz=UTC)
    except (OverflowError, OSError, ValueError) as error:
        msg = f"invalid epoch-seconds timestamp: {value!r}"
        raise ValueError(msg) from error


def _parse_expiration_timestamp(value: object) -> object:
    if value == 0 or value == "0":
        return None
    return _parse_epoch_seconds_timestamp(value)


if TYPE_CHECKING:
    _DecimalFromNumberOrString = Decimal
    _OptionalDecimalFromNumberOrString = Decimal | None
else:
    _DecimalFromNumberOrString = Annotated[Decimal, BeforeValidator(_coerce_decimalish)]
    # The validator must wrap the whole optional annotation: on a
    # ``Decimal | None`` union, a BeforeValidator attached only to the Decimal
    # member cannot map "" to None (the None branch still sees the original "").
    _OptionalDecimalFromNumberOrString = Annotated[
        Decimal | None, BeforeValidator(_coerce_optional_decimalish)
    ]

EpochMsTimestamp = Annotated[datetime | None, BeforeValidator(_parse_epoch_ms_timestamp)]
EpochMsOrIsoTimestamp = Annotated[
    datetime | None, BeforeValidator(_parse_epoch_ms_or_iso_timestamp)
]
EpochOrIsoTimestamp = Annotated[datetime | None, BeforeValidator(_parse_epoch_or_iso_timestamp)]
RequiredEpochOrIsoTimestamp = Annotated[datetime, BeforeValidator(_require_epoch_or_iso_timestamp)]
EpochSecondsTimestamp = Annotated[datetime | None, BeforeValidator(_parse_epoch_seconds_timestamp)]
EpochSecondsOrMsTimestamp = Annotated[
    datetime | None, BeforeValidator(_parse_epoch_seconds_or_ms_timestamp)
]
ExpirationTimestamp = Annotated[datetime | None, BeforeValidator(_parse_expiration_timestamp)]


__all__ = [
    "EpochMsOrIsoTimestamp",
    "EpochMsTimestamp",
    "EpochOrIsoTimestamp",
    "EpochSecondsOrMsTimestamp",
    "EpochSecondsTimestamp",
    "ExpirationTimestamp",
    "RequiredEpochOrIsoTimestamp",
]
