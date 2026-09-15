"""Authenticated price snapshots and updates."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from polymarket.models.base import BaseModel


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
    """One exact USD price at a UTC instant."""

    timestamp: datetime
    value: Decimal


class RealtimePriceUpdate(RealtimePricePoint):
    """A symbol's latest USD price, with optional receipt and carry-forward metadata."""

    symbol: str
    received_at: datetime | None = None
    is_carried_forward: bool | None = None


class RealtimePriceSnapshot(BaseModel):
    """A symbol's recent USD price history, in chronological order."""

    symbol: str
    data: tuple[RealtimePricePoint, ...]


class RealtimeTwapUpdate(RealtimePricePoint):
    """A symbol's fixed 60-second time-weighted average price in USD."""

    symbol: str
    window_seconds: Literal[60] = 60


class RealtimeTwapSnapshot(RealtimePriceSnapshot):
    """Recent history of a symbol's fixed 60-second USD TWAP."""

    window_seconds: Literal[60] = 60


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
    """An equity USD price update."""

    topic: Literal["prices.equity"] = "prices.equity"
    type: Literal["update"] = "update"
    payload: RealtimePriceUpdate


class EquityPriceSnapshotEvent(_PriceEventMetadata):
    """Recent equity USD prices on subscription or recovery."""

    topic: Literal["prices.equity"] = "prices.equity"
    type: Literal["subscribe"] = "subscribe"
    payload: RealtimePriceSnapshot


CryptoPriceEvent = CryptoPriceUpdateEvent | CryptoPriceSnapshotEvent
CryptoTwapPriceEvent = CryptoTwapPriceUpdateEvent | CryptoTwapPriceSnapshotEvent
EquityPriceEvent = EquityPriceUpdateEvent | EquityPriceSnapshotEvent
PriceEvent = CryptoPriceEvent | CryptoTwapPriceEvent | EquityPriceEvent

__all__ = [
    "CryptoPriceEvent",
    "CryptoPriceSnapshotEvent",
    "CryptoPriceUpdateEvent",
    "CryptoTwapPriceEvent",
    "CryptoTwapPriceSnapshotEvent",
    "CryptoTwapPriceUpdateEvent",
    "EquityPriceEvent",
    "EquityPriceSnapshotEvent",
    "EquityPriceUpdateEvent",
    "PriceEvent",
    "RealtimeErrorCode",
    "RealtimePricePoint",
    "RealtimePriceSnapshot",
    "RealtimePriceUpdate",
    "RealtimeTwapSnapshot",
    "RealtimeTwapUpdate",
]
