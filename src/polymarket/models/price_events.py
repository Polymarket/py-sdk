"""Authenticated price snapshots and updates."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal, TypeAlias

from pydantic import field_validator

from polymarket.models.base import BaseModel


class KnownPriceSource(StrEnum):
    """Known price sources; additional sources are preserved as plain strings."""

    PYTH = "pyth"
    CHAINLINK = "chainlink"
    MASSIVE = "massive"


PriceSource: TypeAlias = KnownPriceSource | str


def _parse_price_source(value: object) -> PriceSource:
    if not isinstance(value, str):
        raise ValueError("Price source must be a string")
    try:
        return KnownPriceSource(value)
    except ValueError:
        return value


class EquityMarketStatus(StrEnum):
    """State of the market of the instrument priced by an equity provider.

    UNKNOWN means the provider cannot determine the state. An omitted status
    means not stated, never open. Providers can price different instruments
    for the same symbol and report different states.
    """

    OPEN = "open"
    CLOSED = "closed"
    UNKNOWN = "unknown"


class RealtimeErrorCode(StrEnum):
    BAD_OP = "bad_op"
    BAD_CHANNEL = "bad_channel"
    BAD_FILTER = "bad_filter"
    SUBSCRIPTION_LIMIT = "sub_limit"
    RATE_LIMITED = "rate_limited"
    AUTH_REQUIRED = "auth_required"
    AUTH_UNAVAILABLE = "auth_unavailable"
    AUTH_EXPIRED = "auth_expired"
    AUTH_ATTEMPTS = "auth_attempts"
    AUTH_INVALID = "auth_invalid"


class RealtimePricePoint(BaseModel):
    """One exact price in the instrument's quote currency at a UTC instant."""

    timestamp: datetime
    value: Decimal


class RealtimePriceUpdate(RealtimePricePoint):
    """A symbol's latest price in its quote currency.

    Includes optional receipt and carry-forward metadata.
    """

    symbol: str
    source: PriceSource
    """Source that supplied this price."""
    received_at: datetime | None = None
    is_carried_forward: bool | None = None

    _parse_source = field_validator("source", mode="before")(_parse_price_source)


class RealtimePriceSnapshot(BaseModel):
    """A symbol's recent prices in its quote currency, in chronological order."""

    symbol: str
    source: PriceSource
    """Source for this history, including when ``data`` is empty."""
    data: tuple[RealtimePricePoint, ...]

    _parse_source = field_validator("source", mode="before")(_parse_price_source)


class RealtimeTwapUpdate(RealtimePricePoint):
    """A symbol's fixed 60-second time-weighted average price in its quote currency."""

    symbol: str
    source: PriceSource
    """Source that supplied this TWAP."""
    window_seconds: Literal[60] = 60

    _parse_source = field_validator("source", mode="before")(_parse_price_source)


class RealtimeTwapSnapshot(RealtimePriceSnapshot):
    """Recent history of a symbol's fixed 60-second TWAP in its quote currency."""

    window_seconds: Literal[60] = 60


class _EquityMarketState(BaseModel):
    market_status: EquityMarketStatus | None = None
    """Current status for this provider's instrument; None means not stated."""


class RealtimeEquityPriceUpdate(RealtimePriceUpdate, _EquityMarketState):
    """An equity price and current market status.

    A status-only update repeats the price timestamp with is_carried_forward
    true. Do not deduplicate updates by price timestamp alone.
    """


class RealtimeEquityPriceSnapshot(RealtimePriceSnapshot, _EquityMarketState):
    """Equity history with current status at batch level.

    While closed or unknown, history can include the closing price even when
    it is older than two minutes.
    """


class RealtimeEquityTwapUpdate(RealtimeTwapUpdate, _EquityMarketState):
    """An equity TWAP and market status, which changes only with a new price."""


class RealtimeEquityTwapSnapshot(RealtimeTwapSnapshot, _EquityMarketState):
    """Equity TWAP history and current status; may include an older closing price."""


class _PriceEventMetadata(BaseModel):
    """Event time and delivery metadata.

    ``seq`` is local to one channel on one connection and resets after reconnecting.
    A subscription with more than 64 filters can span connections, whose sequence
    values may interleave. ``dropped`` reports server-side losses, when supplied.
    """

    timestamp: datetime
    seq: int | None = None
    dropped: int | None = None


class CryptoPriceUpdateEvent(_PriceEventMetadata):
    """A cryptocurrency USD price update."""

    topic: Literal["prices.crypto"] = "prices.crypto"
    type: Literal["update"] = "update"
    payload: RealtimePriceUpdate


class CryptoPriceSnapshotEvent(_PriceEventMetadata):
    """Recent cryptocurrency USD prices on subscription or recovery."""

    topic: Literal["prices.crypto"] = "prices.crypto"
    type: Literal["subscribe"] = "subscribe"
    payload: RealtimePriceSnapshot


class CryptoTwapPriceUpdateEvent(_PriceEventMetadata):
    """A cryptocurrency 60-second USD TWAP update."""

    topic: Literal["prices.crypto.twap"] = "prices.crypto.twap"
    type: Literal["update"] = "update"
    payload: RealtimeTwapUpdate


class CryptoTwapPriceSnapshotEvent(_PriceEventMetadata):
    """Recent cryptocurrency 60-second USD TWAPs on subscription or recovery."""

    topic: Literal["prices.crypto.twap"] = "prices.crypto.twap"
    type: Literal["subscribe"] = "subscribe"
    payload: RealtimeTwapSnapshot


class EquityPriceUpdateEvent(_PriceEventMetadata):
    """A price update in the instrument's quote currency."""

    topic: Literal["prices.equity"] = "prices.equity"
    type: Literal["update"] = "update"
    payload: RealtimeEquityPriceUpdate


class EquityPriceSnapshotEvent(_PriceEventMetadata):
    """Recent prices in the instrument's quote currency on subscription or recovery."""

    topic: Literal["prices.equity"] = "prices.equity"
    type: Literal["subscribe"] = "subscribe"
    payload: RealtimeEquityPriceSnapshot


class EquityTwapPriceUpdateEvent(_PriceEventMetadata):
    """A 60-second TWAP update in the instrument's quote currency."""

    topic: Literal["prices.equity.twap"] = "prices.equity.twap"
    type: Literal["update"] = "update"
    payload: RealtimeEquityTwapUpdate


class EquityTwapPriceSnapshotEvent(_PriceEventMetadata):
    """Recent 60-second TWAPs in the quote currency on subscription or recovery."""

    topic: Literal["prices.equity.twap"] = "prices.equity.twap"
    type: Literal["subscribe"] = "subscribe"
    payload: RealtimeEquityTwapSnapshot


CryptoPriceEvent = CryptoPriceUpdateEvent | CryptoPriceSnapshotEvent
CryptoTwapPriceEvent = CryptoTwapPriceUpdateEvent | CryptoTwapPriceSnapshotEvent
EquityPriceEvent = EquityPriceUpdateEvent | EquityPriceSnapshotEvent
EquityTwapPriceEvent = EquityTwapPriceUpdateEvent | EquityTwapPriceSnapshotEvent
PriceEvent = CryptoPriceEvent | CryptoTwapPriceEvent | EquityPriceEvent | EquityTwapPriceEvent

__all__ = [
    "RealtimeEquityTwapSnapshot",
    "RealtimeEquityTwapUpdate",
    "RealtimeEquityPriceSnapshot",
    "RealtimeEquityPriceUpdate",
    "EquityMarketStatus",
    "CryptoPriceEvent",
    "CryptoPriceSnapshotEvent",
    "CryptoPriceUpdateEvent",
    "CryptoTwapPriceEvent",
    "CryptoTwapPriceSnapshotEvent",
    "CryptoTwapPriceUpdateEvent",
    "EquityPriceEvent",
    "EquityPriceSnapshotEvent",
    "EquityPriceUpdateEvent",
    "EquityTwapPriceEvent",
    "EquityTwapPriceSnapshotEvent",
    "EquityTwapPriceUpdateEvent",
    "KnownPriceSource",
    "PriceEvent",
    "PriceSource",
    "RealtimeErrorCode",
    "RealtimePricePoint",
    "RealtimePriceSnapshot",
    "RealtimePriceUpdate",
    "RealtimeTwapSnapshot",
    "RealtimeTwapUpdate",
]
