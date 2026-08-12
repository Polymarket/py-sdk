"""Perps realtime event models."""

import re
from datetime import datetime
from typing import Annotated, Any, Literal, cast

from pydantic import Field, TypeAdapter, ValidationError, field_validator

from polymarket.models.base import BaseModel
from polymarket.models.perps._validators import (
    _parse_epoch_ms,  # pyright: ignore[reportPrivateUsage]
    _require_epoch_ms,  # pyright: ignore[reportPrivateUsage]
)
from polymarket.models.perps.account import PerpsBalance, PerpsFundingPayment, PerpsPortfolio
from polymarket.models.perps.funds import PerpsDepositUpdate, PerpsWithdrawalUpdate
from polymarket.models.perps.market import (
    PerpsBbo,
    PerpsBookUpdate,
    PerpsCandleBatch,
    PerpsStatistic,
    PerpsTickerUpdate,
    PerpsTrade,
)
from polymarket.models.perps.notifications import PerpsNotification
from polymarket.models.perps.orders import PerpsFill, PerpsOrder
from polymarket.models.perps.types import PerpsOrderId, PerpsTpSlLifecycleStatus

_TRADES_CHANNEL = re.compile(r"^trades::(\d+)$")
_BBO_CHANNEL = re.compile(r"^bbo::(\d+)$")
_BOOK_CHANNEL = re.compile(r"^book::(\d+)$")
_TICKERS_CHANNEL = re.compile(r"^tickers::(all|\d+)$")
_STATISTICS_CHANNEL = re.compile(r"^statistics::(all|\d+)$")
_CANDLES_CHANNEL = re.compile(r"^klines::(\d+)::(1m|5m|15m|1h|4h|1d|1w)$")
_TPSL_CHANNEL = re.compile(r"^tpsl::\d+$")

_SESSION_CHANNEL_TYPES: dict[str, str] = {
    "balances": "balance",
    "portfolio": "portfolio",
    "orders": "order",
    "fills": "fill",
    "funding": "funding",
    "deposits": "deposit",
    "withdrawals": "withdrawal",
    "notifications": "notification",
}

_NOTIFICATIONS_CHANNEL = "notifications"


class _PerpsEventEnvelope(BaseModel):
    @field_validator("timestamp", mode="before", check_fields=False)
    @classmethod
    def _validate_timestamp(cls, value: object) -> object:
        return _require_epoch_ms(value)


class PerpsTradeEvent(_PerpsEventEnvelope):
    """Public trades printed in one update for a subscribed instrument."""

    topic: Literal["perps.trades"] = "perps.trades"
    type: Literal["trade"]
    channel: str
    timestamp: datetime
    sequence: int
    payload: list[PerpsTrade]


class PerpsBboEvent(_PerpsEventEnvelope):
    """A best bid/ask update for a subscribed instrument."""

    topic: Literal["perps.bbo"] = "perps.bbo"
    type: Literal["bbo"]
    channel: str
    timestamp: datetime
    sequence: int
    payload: PerpsBbo


class PerpsBookEvent(_PerpsEventEnvelope):
    """An order book delta for a subscribed instrument."""

    topic: Literal["perps.book"] = "perps.book"
    type: Literal["book"]
    channel: str
    timestamp: datetime
    sequence: int
    payload: PerpsBookUpdate


class PerpsTickerEvent(_PerpsEventEnvelope):
    """A ticker update for a subscribed instrument."""

    topic: Literal["perps.tickers"] = "perps.tickers"
    type: Literal["ticker"]
    channel: str
    timestamp: datetime
    sequence: int
    payload: PerpsTickerUpdate


class PerpsStatisticEvent(_PerpsEventEnvelope):
    """A trading statistics update for a subscribed instrument."""

    topic: Literal["perps.statistics"] = "perps.statistics"
    type: Literal["statistic"]
    channel: str
    timestamp: datetime
    sequence: int
    payload: PerpsStatistic


class PerpsCandleEvent(_PerpsEventEnvelope):
    """A candle batch for a subscribed instrument and interval."""

    topic: Literal["perps.candles"] = "perps.candles"
    type: Literal["candle"]
    channel: str
    timestamp: datetime
    sequence: int
    payload: PerpsCandleBatch


PerpsMarketEvent = Annotated[
    PerpsTradeEvent
    | PerpsBboEvent
    | PerpsBookEvent
    | PerpsTickerEvent
    | PerpsStatisticEvent
    | PerpsCandleEvent,
    Field(discriminator="type"),
]

_MARKET_EVENT_ADAPTER: TypeAdapter[PerpsMarketEvent] = TypeAdapter(PerpsMarketEvent)


class PerpsBalanceEvent(_PerpsEventEnvelope):
    """A balance update for the session account."""

    type: Literal["balance"]
    channel: str
    timestamp: datetime
    sequence: int
    payload: PerpsBalance


class PerpsPortfolioEvent(_PerpsEventEnvelope):
    """A portfolio snapshot update for the session account."""

    type: Literal["portfolio"]
    channel: str
    timestamp: datetime
    sequence: int
    payload: PerpsPortfolio


class PerpsOrderEvent(_PerpsEventEnvelope):
    """An order lifecycle update for the session account."""

    type: Literal["order"]
    channel: str
    timestamp: datetime
    sequence: int
    payload: PerpsOrder


class PerpsFillEvent(_PerpsEventEnvelope):
    """Fill updates in one frame for the session account."""

    type: Literal["fill"]
    channel: str
    timestamp: datetime
    sequence: int
    payload: list[PerpsFill]


class PerpsFundingEvent(_PerpsEventEnvelope):
    """A funding payment update for the session account."""

    type: Literal["funding"]
    channel: str
    timestamp: datetime
    sequence: int
    payload: PerpsFundingPayment


class PerpsDepositEvent(_PerpsEventEnvelope):
    """A deposit status update for the session account."""

    type: Literal["deposit"]
    channel: str
    timestamp: datetime
    sequence: int
    payload: PerpsDepositUpdate


class PerpsWithdrawalEvent(_PerpsEventEnvelope):
    """A withdrawal status update for the session account."""

    type: Literal["withdrawal"]
    channel: str
    timestamp: datetime
    sequence: int
    payload: PerpsWithdrawalUpdate


class PerpsTpSlUpdate(BaseModel):
    """Lifecycle state of one take-profit/stop-loss trigger order."""

    order_id: PerpsOrderId = Field(validation_alias="oid")
    status: PerpsTpSlLifecycleStatus = Field(validation_alias="st")
    reason: str | None = None


class PerpsTpSlEvent(_PerpsEventEnvelope):
    """A take-profit/stop-loss lifecycle update for the session account."""

    type: Literal["tpsl"]
    channel: str
    timestamp: datetime
    sequence: int
    payload: PerpsTpSlUpdate


class PerpsNotificationEvent(_PerpsEventEnvelope):
    """An account notification for the session account."""

    type: Literal["notification"]
    channel: str
    timestamp: datetime
    sequence: int
    payload: PerpsNotification


class PerpsResyncEvent(BaseModel):
    """A signal that session state should be refetched.

    Emitted after a reconnect, when a gap is detected in a channel's
    sequence numbers, and when the server reports dropped ``notifications``
    frames (``reason="server"``); a server resync's ``sequence`` is the
    highest engine sequence among the dropped notifications.
    """

    type: Literal["resync"] = "resync"
    reason: Literal["reconnect", "sequence_gap", "server"]
    channel: str | None = None
    previous_sequence: int | None = None
    sequence: int | None = None
    timestamp: datetime | None = None

    @field_validator("timestamp", mode="before")
    @classmethod
    def _validate_timestamp(cls, value: object) -> object:
        return _parse_epoch_ms(value)


PerpsSessionEvent = (
    PerpsBalanceEvent
    | PerpsPortfolioEvent
    | PerpsOrderEvent
    | PerpsFillEvent
    | PerpsFundingEvent
    | PerpsDepositEvent
    | PerpsWithdrawalEvent
    | PerpsNotificationEvent
    | PerpsTpSlEvent
    | PerpsResyncEvent
)

_SessionUpdateEvent = Annotated[
    PerpsBalanceEvent
    | PerpsPortfolioEvent
    | PerpsOrderEvent
    | PerpsFillEvent
    | PerpsFundingEvent
    | PerpsDepositEvent
    | PerpsWithdrawalEvent
    | PerpsNotificationEvent
    | PerpsTpSlEvent,
    Field(discriminator="type"),
]

_SESSION_EVENT_ADAPTER: TypeAdapter[_SessionUpdateEvent] = TypeAdapter(_SessionUpdateEvent)


def _market_envelope(raw: object) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    wire = cast(dict[str, Any], raw)
    channel = wire.get("ch")
    if not isinstance(channel, str) or "ts" not in wire or "sq" not in wire:
        return None
    envelope = {
        "channel": channel,
        "timestamp": wire.get("ts"),
        "sequence": wire.get("sq"),
    }
    data = wire.get("data")
    if _TRADES_CHANNEL.match(channel):
        return {**envelope, "type": "trade", "payload": data}
    if _BBO_CHANNEL.match(channel):
        return {**envelope, "type": "bbo", "payload": data}
    match = _BOOK_CHANNEL.match(channel)
    if match:
        payload: object = data
        if isinstance(data, dict):
            book = dict(cast("dict[str, Any]", data))
            book["instrument_id"] = int(match.group(1))
            payload = book
        return {**envelope, "type": "book", "payload": payload}
    if _TICKERS_CHANNEL.match(channel):
        return {**envelope, "type": "ticker", "payload": data}
    if _STATISTICS_CHANNEL.match(channel):
        return {**envelope, "type": "statistic", "payload": data}
    match = _CANDLES_CHANNEL.match(channel)
    if match:
        return {
            **envelope,
            "type": "candle",
            "payload": {
                "instrument_id": int(match.group(1)),
                "interval": match.group(2),
                "candles": data,
            },
        }
    return None


def parse_perps_market_event(raw: object) -> PerpsMarketEvent | None:
    """Parse one market data frame; returns None for non-event frames."""
    envelope = _market_envelope(raw)
    if envelope is None:
        return None
    return _MARKET_EVENT_ADAPTER.validate_python(envelope)


def parse_perps_session_event(raw: object) -> PerpsSessionEvent | None:
    """Parse one session update frame; returns None for non-event frames."""
    if not isinstance(raw, dict):
        return None
    wire = cast(dict[str, Any], raw)
    channel = wire.get("ch")
    if not isinstance(channel, str) or "ts" not in wire or "sq" not in wire:
        return None
    if channel == _NOTIFICATIONS_CHANNEL and wire.get("type") == "resync":
        return PerpsResyncEvent.model_validate(
            {
                "reason": "server",
                "channel": channel,
                "sequence": wire.get("sq"),
                "timestamp": wire.get("ts"),
            }
        )
    if _TPSL_CHANNEL.match(channel):
        event_type = "tpsl"
    else:
        mapped = _SESSION_CHANNEL_TYPES.get(channel)
        if mapped is None:
            return None
        event_type = mapped
    return _SESSION_EVENT_ADAPTER.validate_python(
        {
            "type": event_type,
            "channel": channel,
            "timestamp": wire.get("ts"),
            "sequence": wire.get("sq"),
            "payload": wire.get("data"),
        }
    )


def parse_perps_market_events(raw: object) -> tuple[list[PerpsMarketEvent], int]:
    """Parse a decoded frame into market events.

    Returns ``(events, dropped_count)``. Frames that are not channel updates
    (for example command acknowledgements) are ignored without counting as
    dropped; malformed channel updates are dropped.
    """
    items: list[object] = list(cast(list[object], raw)) if isinstance(raw, list) else [raw]
    parsed: list[PerpsMarketEvent] = []
    dropped = 0
    for item in items:
        try:
            event = parse_perps_market_event(item)
        except ValidationError:
            dropped += 1
            continue
        if event is not None:
            parsed.append(event)
    return parsed, dropped


__all__ = [
    "PerpsBalanceEvent",
    "PerpsBboEvent",
    "PerpsBookEvent",
    "PerpsCandleEvent",
    "PerpsDepositEvent",
    "PerpsFillEvent",
    "PerpsFundingEvent",
    "PerpsMarketEvent",
    "PerpsNotificationEvent",
    "PerpsOrderEvent",
    "PerpsPortfolioEvent",
    "PerpsResyncEvent",
    "PerpsSessionEvent",
    "PerpsStatisticEvent",
    "PerpsTickerEvent",
    "PerpsTpSlEvent",
    "PerpsTpSlUpdate",
    "PerpsTradeEvent",
    "PerpsWithdrawalEvent",
]
