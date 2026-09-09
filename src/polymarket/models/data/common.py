"""Filter vocabularies and response parsers for portfolio and trading analytics."""

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Literal

SortDirection = Literal["ASC", "DESC"]
TradeFilterType = Literal["CASH", "TOKENS"]
PositionFilterType = Literal["CASH", "TOKENS"]


class ActivityType(StrEnum):
    """Kind of wallet activity row."""

    TRADE = "TRADE"
    SPLIT = "SPLIT"
    MERGE = "MERGE"
    REDEEM = "REDEEM"
    REWARD = "REWARD"
    CONVERSION = "CONVERSION"
    MIGRATION = "MIGRATION"
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    YIELD = "YIELD"
    MAKER_REBATE = "MAKER_REBATE"
    TAKER_REBATE = "TAKER_REBATE"
    REFERRAL_REWARD = "REFERRAL_REWARD"
    TIP = "TIP"


ActivityTypeFilter = (
    Literal[
        "TRADE",
        "SPLIT",
        "MERGE",
        "REDEEM",
        "REWARD",
        "CONVERSION",
        "MIGRATION",
        "DEPOSIT",
        "WITHDRAWAL",
        "YIELD",
        "MAKER_REBATE",
        "TAKER_REBATE",
        "REFERRAL_REWARD",
        "TIP",
    ]
    | ActivityType
)
"""Activity kinds accepted by activity filters, as plain strings or :class:`ActivityType`."""


class ComboActivityType(StrEnum):
    """Kind of combo lifecycle activity row."""

    SPLIT = "SPLIT"
    MERGE = "MERGE"
    CONVERT = "CONVERT"
    COMPRESS = "COMPRESS"
    WRAP = "WRAP"
    UNWRAP = "UNWRAP"
    REDEEM = "REDEEM"


class TipSide(StrEnum):
    """Direction of a tip from the wallet's perspective."""

    IN = "IN"
    OUT = "OUT"


class PositionStatus(StrEnum):
    """Lifecycle status of a position."""

    OPEN = "OPEN"
    REDEEMABLE = "REDEEMABLE"
    CLOSED = "CLOSED"


PositionStatusFilter = Literal["OPEN", "REDEEMABLE", "CLOSED"] | PositionStatus
"""Position statuses accepted by filters, as plain strings or :class:`PositionStatus`."""

PositionSortBy = Literal[
    "CURRENT_VALUE", "TOKENS", "UNREALIZED_PNL", "REALIZED_PNL", "TOTAL_PNL", "TIMESTAMP"
]


class ComboPositionStatus(StrEnum):
    """Lifecycle status of a combo position or leg."""

    OPEN = "OPEN"
    REDEEMABLE = "REDEEMABLE"
    PARTIAL = "PARTIAL"
    RESOLVED_PARTIAL = "RESOLVED_PARTIAL"
    RESOLVED_WIN = "RESOLVED_WIN"
    RESOLVED_LOSS = "RESOLVED_LOSS"


ComboPositionStatusFilter = (
    Literal["OPEN", "REDEEMABLE", "PARTIAL", "RESOLVED_PARTIAL", "RESOLVED_WIN", "RESOLVED_LOSS"]
    | ComboPositionStatus
)
"""Combo statuses accepted by filters, as plain strings or :class:`ComboPositionStatus`."""

ComboPositionSortBy = Literal["FIRST_ENTRY", "ENTRY_COST", "CURRENT_VALUE", "UPDATED"]
LeaderboardWindow = Literal["day", "week", "month", "all"]
TraderLeaderboardSort = Literal["PNL", "VOLUME"]
BuilderVolumeInterval = Literal["day", "week", "month", "all"]
"""Bucket interval; ``all`` yields calendar-year buckets."""


class BiggestWinnerKind(StrEnum):
    """Source of a winning position."""

    MARKET = "market"
    COMBO = "combo"


PriceHistoryInterval = Literal["max", "all", "1m", "1w", "1d", "6h", "1h"]


class UserPnlInterval(StrEnum):
    """Lookback window of a wallet PnL series."""

    MAX = "max"
    ALL = "all"
    ONE_MONTH = "1m"
    ONE_WEEK = "1w"
    ONE_DAY = "1d"
    TWELVE_HOURS = "12h"
    SIX_HOURS = "6h"


UserPnlIntervalInput = Literal["max", "all", "1m", "1w", "1d", "12h", "6h"] | UserPnlInterval
"""Lookback windows accepted by PnL requests, as plain strings or :class:`UserPnlInterval`."""


class UserPnlFidelity(StrEnum):
    """Time step between points in a wallet PnL series."""

    ONE_DAY = "1d"
    EIGHTEEN_HOURS = "18h"
    TWELVE_HOURS = "12h"
    THREE_HOURS = "3h"
    ONE_HOUR = "1h"


UserPnlFidelityInput = Literal["1d", "18h", "12h", "3h", "1h"] | UserPnlFidelity
"""Time steps accepted by PnL requests, as plain strings or :class:`UserPnlFidelity`."""


class ResolutionStatus(StrEnum):
    """Lifecycle stage of a market resolution."""

    INITIALIZED = "initialized"
    POSED = "posed"
    PROPOSED = "proposed"
    CHALLENGED = "challenged"
    REPROPOSED = "reproposed"
    DISPUTED = "disputed"
    ACTIVE = "active"
    ARBITRATION = "arbitration"
    RESOLVED = "resolved"


class ResolutionMarketType(StrEnum):
    """Market structure of a resolved condition."""

    BINARY = "BINARY"
    INCREMENTAL_NEGRISK = "INCREMENTAL_NEGRISK"
    ATOMIC_NEGRISK = "ATOMIC_NEGRISK"


class ResolutionSource(StrEnum):
    """How a condition's final payout was obtained."""

    REPORTED = "reported"
    DERIVED = "derived"


class ResolutionReporter(StrEnum):
    """Reporter family that supplied a resolution."""

    UMA_OPTIMISTIC_ORACLE = "UMA_OO"
    CHAINLINK = "CHAINLINK"
    EOA = "EOA"


def decimal_from_number(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, str | int | float | Decimal):
        raise ValueError("Expected a decimal amount")
    try:
        return Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError("Expected a decimal amount") from error


def optional_decimal_from_number(value: object) -> Decimal | None:
    return None if value is None else decimal_from_number(value)


def optional_text(value: object) -> object:
    return None if value == "" else value


def optional_outcome_index(value: object) -> object:
    return None if value == 999 else value


def datetime_from_epoch_seconds(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise ValueError("Expected epoch seconds")
    try:
        return datetime.fromtimestamp(float(value), UTC)
    except (OverflowError, OSError) as error:
        raise ValueError("Epoch seconds are outside the supported datetime range") from error


def optional_datetime_from_epoch_seconds(value: object) -> datetime | None:
    return None if value in (None, 0, "0", "") else datetime_from_epoch_seconds(value)


def date_from_calendar_string(value: object) -> object:
    return None if value in (None, "", "1970-01-01") else value


def optional_event_id(value: object) -> object:
    return None if value in (None, "", "0", 0) else str(value)


def required_event_id(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, int | str):
        raise ValueError("Expected an event ID")
    text = str(value)
    if not text.isdecimal() or int(text) <= 0:
        raise ValueError("Expected a positive event ID")
    return text


def datetime_from_epoch_or_iso(value: object) -> datetime:
    if isinstance(value, str) and not value.isdecimal():
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    return datetime_from_epoch_seconds(value)


def optional_datetime_from_epoch_or_iso(value: object) -> datetime | None:
    return None if value in (None, "") else datetime_from_epoch_or_iso(value)


__all__ = [
    "ActivityType",
    "ActivityTypeFilter",
    "BiggestWinnerKind",
    "BuilderVolumeInterval",
    "ComboActivityType",
    "ComboPositionSortBy",
    "ComboPositionStatus",
    "ComboPositionStatusFilter",
    "LeaderboardWindow",
    "PositionFilterType",
    "PositionSortBy",
    "PositionStatus",
    "PositionStatusFilter",
    "PriceHistoryInterval",
    "ResolutionMarketType",
    "ResolutionReporter",
    "ResolutionSource",
    "ResolutionStatus",
    "SortDirection",
    "TipSide",
    "TradeFilterType",
    "TraderLeaderboardSort",
    "UserPnlFidelity",
    "UserPnlFidelityInput",
    "UserPnlInterval",
    "UserPnlIntervalInput",
]
