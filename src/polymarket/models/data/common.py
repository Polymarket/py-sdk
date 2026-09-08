"""Filter vocabularies and response parsers for portfolio and trading analytics."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

SortDirection = Literal["ASC", "DESC"]
TradeFilterType = Literal["CASH", "TOKENS"]
PositionFilterType = Literal["CASH", "TOKENS"]
ActivityTypeFilter = Literal[
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
TipSide = Literal["IN", "OUT"]
PositionStatus = Literal["OPEN", "REDEEMABLE", "CLOSED"]
PositionSortBy = Literal[
    "CURRENT_VALUE", "TOKENS", "UNREALIZED_PNL", "REALIZED_PNL", "TOTAL_PNL", "TIMESTAMP"
]
ComboPositionStatus = Literal[
    "OPEN", "REDEEMABLE", "PARTIAL", "RESOLVED_PARTIAL", "RESOLVED_WIN", "RESOLVED_LOSS"
]
ComboPositionSortBy = Literal["FIRST_ENTRY", "ENTRY_COST", "CURRENT_VALUE", "UPDATED"]
LeaderboardWindow = Literal["day", "week", "month", "all"]
TraderLeaderboardSort = Literal["PNL", "VOLUME"]
BuilderVolumeInterval = Literal["day", "week", "month", "all"]
"""Bucket interval; ``all`` yields calendar-year buckets."""
BiggestWinnerKind = Literal["market", "combo"]
PriceHistoryInterval = Literal["max", "all", "1m", "1w", "1d", "6h", "1h"]
UserPnlInterval = Literal["max", "all", "1m", "1w", "1d", "12h", "6h"]
UserPnlFidelity = Literal["1d", "18h", "12h", "3h", "1h"]
ResolutionStatus = Literal[
    "initialized",
    "posed",
    "proposed",
    "challenged",
    "reproposed",
    "disputed",
    "active",
    "arbitration",
    "resolved",
]
ResolutionMarketType = Literal["BINARY", "INCREMENTAL_NEGRISK", "ATOMIC_NEGRISK"]
ResolutionSource = Literal["reported", "derived"]
ResolutionReporter = Literal["UMA_OO", "CHAINLINK", "EOA"]


def decimal_from_number(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, str | int | float | Decimal):
        raise ValueError("Expected a decimal amount")
    return Decimal(str(value))


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


def datetime_from_epoch_or_iso(value: object) -> datetime:
    if isinstance(value, str) and not value.isdecimal():
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return datetime_from_epoch_seconds(value)


__all__ = [
    "ActivityTypeFilter",
    "BiggestWinnerKind",
    "BuilderVolumeInterval",
    "ComboPositionSortBy",
    "ComboPositionStatus",
    "LeaderboardWindow",
    "PositionFilterType",
    "PositionSortBy",
    "PositionStatus",
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
    "UserPnlInterval",
]
