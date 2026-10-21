import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal, cast

from polymarket.models.price_events import (
    CryptoPriceSnapshotEvent,
    CryptoPriceUpdateEvent,
    CryptoTwapPriceSnapshotEvent,
    CryptoTwapPriceUpdateEvent,
    EquityMarketStatus,
    EquityPriceSnapshotEvent,
    EquityPriceUpdateEvent,
    EquityTwapPriceSnapshotEvent,
    EquityTwapPriceUpdateEvent,
    PriceEvent,
    RealtimeEquityPriceSnapshot,
    RealtimeEquityPriceUpdate,
    RealtimeEquityTwapSnapshot,
    RealtimeEquityTwapUpdate,
    RealtimePricePoint,
    RealtimePriceSnapshot,
    RealtimePriceUpdate,
    RealtimeTwapSnapshot,
    RealtimeTwapUpdate,
)
from polymarket.streams._specs import (
    EquityPriceSpec,
    EquityTwapPriceSpec,
    PriceProviderInput,
    PriceSpec,
)

PriceTopic = Literal["prices.crypto", "prices.crypto.twap", "prices.equity", "prices.equity.twap"]
CHANNEL_TOPICS: dict[str, PriceTopic] = {
    "price.crypto": "prices.crypto",
    "price.crypto.twap": "prices.crypto.twap",
    "price.equity": "prices.equity",
    "price.equity.twap": "prices.equity.twap",
}


@dataclass(frozen=True, slots=True)
class PriceKey:
    topic: PriceTopic
    symbol: str
    provider: PriceProviderInput | None = None


def subscriptions_for(spec: PriceSpec) -> tuple[PriceKey, ...]:
    symbols = (
        (spec.symbol,) if isinstance(spec, EquityPriceSpec | EquityTwapPriceSpec) else spec.symbols
    )
    return tuple(dict.fromkeys(PriceKey(spec.topic, symbol, spec.provider) for symbol in symbols))


def build_wire_subscription(key: PriceKey) -> dict[str, object]:
    price_filter: dict[str, object] = {"symbol": key.symbol}
    if key.topic in ("prices.crypto.twap", "prices.equity.twap"):
        price_filter["window_seconds"] = 60
    if key.provider is not None:
        price_filter["provider"] = key.provider
    return {"channel": key.topic.replace("prices.", "price.", 1), "filter": price_filter}


def reconnect_delay(code: int, attempt: int) -> float:
    return random.random() * (10 if code == 4003 else min(2 ** min(attempt, 5), 30))


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("Expected an object")
    return cast(dict[str, object], value)


def _nonnegative_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("Expected a non-negative integer")
    return value


def datetime_from_epoch_milliseconds(value: object) -> datetime:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("Expected epoch milliseconds")
    return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=value)


def _price_point(value: object) -> RealtimePricePoint:
    point = _object(value)
    # Validate the wire's approximate value but never use it for exact prices.
    approximate = point["value"]
    if isinstance(approximate, bool) or not isinstance(approximate, int | float | str):
        raise ValueError("Invalid price")
    if not Decimal(str(approximate)).is_finite():
        raise ValueError("Invalid price")
    exact = point["full_accuracy_value"]
    if not isinstance(exact, str) or not Decimal(exact).is_finite():
        raise ValueError("Expected an exact decimal string")
    return RealtimePricePoint(
        timestamp=datetime_from_epoch_milliseconds(point["timestamp"]), value=Decimal(exact)
    )


def parse_price_event(message: object) -> PriceEvent | None:
    """Drop unknown or malformed frames without interrupting a subscription."""
    try:
        frame = _object(message)
        if type(frame.get("v")) is not int or frame["v"] != 1:
            return None
        topic = CHANNEL_TOPICS.get(str(frame.get("channel")))
        if topic is None:
            return None
        seq = _nonnegative_int(frame["seq"])
        dropped = _nonnegative_int(frame["dropped"]) if "dropped" in frame else None
        timestamp = datetime_from_epoch_milliseconds(frame["ts"])
        snapshot = frame.get("snapshot", False)
        if not isinstance(snapshot, bool):
            return None
        payload = _object(frame["payload"])
        symbol = payload["symbol"]
        source = payload["source"]
        if not isinstance(symbol, str) or not isinstance(source, str):
            return None
        # Shared keys always expose their canonical spelling.
        symbol = symbol.lower()
        if topic in ("prices.crypto.twap", "prices.equity.twap") and (
            type(payload.get("window_seconds")) is not int or payload["window_seconds"] != 60
        ):
            return None
        market_status = None
        if topic in ("prices.equity", "prices.equity.twap") and "market_status" in payload:
            raw_status = payload["market_status"]
            if not isinstance(raw_status, str):
                return None
            market_status = EquityMarketStatus(raw_status)
        if snapshot:
            raw_points = payload["data"]
            if not isinstance(raw_points, list):
                return None
            points = tuple(_price_point(point) for point in cast(list[object], raw_points))
            if topic == "prices.crypto.twap":
                return CryptoTwapPriceSnapshotEvent(
                    timestamp=timestamp,
                    seq=seq,
                    dropped=dropped,
                    payload=RealtimeTwapSnapshot(symbol=symbol, source=source, data=points),
                )
            if topic == "prices.equity.twap":
                return EquityTwapPriceSnapshotEvent(
                    timestamp=timestamp,
                    seq=seq,
                    dropped=dropped,
                    payload=RealtimeEquityTwapSnapshot(
                        symbol=symbol,
                        source=source,
                        data=points,
                        market_status=market_status,
                    ),
                )
            if topic == "prices.crypto":
                history = RealtimePriceSnapshot(symbol=symbol, source=source, data=points)
                return CryptoPriceSnapshotEvent(
                    timestamp=timestamp, seq=seq, dropped=dropped, payload=history
                )
            return EquityPriceSnapshotEvent(
                timestamp=timestamp,
                seq=seq,
                dropped=dropped,
                payload=RealtimeEquityPriceSnapshot(
                    symbol=symbol, source=source, data=points, market_status=market_status
                ),
            )
        point = _price_point(payload)
        if topic == "prices.crypto.twap":
            return CryptoTwapPriceUpdateEvent(
                timestamp=timestamp,
                seq=seq,
                dropped=dropped,
                payload=RealtimeTwapUpdate(
                    symbol=symbol,
                    source=source,
                    timestamp=point.timestamp,
                    value=point.value,
                ),
            )
        if topic == "prices.equity.twap":
            return EquityTwapPriceUpdateEvent(
                timestamp=timestamp,
                seq=seq,
                dropped=dropped,
                payload=RealtimeEquityTwapUpdate(
                    symbol=symbol,
                    source=source,
                    timestamp=point.timestamp,
                    value=point.value,
                    market_status=market_status,
                ),
            )
        received_at = (
            datetime_from_epoch_milliseconds(payload["received_at"])
            if "received_at" in payload
            else None
        )
        carried = payload.get("is_carried_forward")
        if "is_carried_forward" in payload and not isinstance(carried, bool):
            return None
        if topic == "prices.crypto":
            return CryptoPriceUpdateEvent(
                timestamp=timestamp,
                seq=seq,
                dropped=dropped,
                payload=RealtimePriceUpdate(
                    symbol=symbol,
                    source=source,
                    timestamp=point.timestamp,
                    value=point.value,
                    received_at=received_at,
                    is_carried_forward=cast(bool | None, carried),
                ),
            )
        return EquityPriceUpdateEvent(
            timestamp=timestamp,
            seq=seq,
            dropped=dropped,
            payload=RealtimeEquityPriceUpdate(
                symbol=symbol,
                source=source,
                timestamp=point.timestamp,
                value=point.value,
                received_at=received_at,
                is_carried_forward=cast(bool | None, carried),
                market_status=market_status,
            ),
        )
    except (ValueError, TypeError, KeyError, ArithmeticError):
        return None


def refresh_snapshot(previous: PriceEvent | None, event: PriceEvent) -> PriceEvent | None:
    if event.type == "subscribe":
        return event
    history = (
        previous.payload.data
        if previous is not None
        and previous.type == "subscribe"
        and previous.payload.source == event.payload.source
        else ()
    )
    timestamp = event.payload.timestamp
    if history and history[-1].timestamp > timestamp:
        # Equity spot clocks can deliver a status on a price older than history.
        if (
            previous is not None
            and previous.type == "subscribe"
            and previous.topic == "prices.equity"
            and event.topic == "prices.equity"
        ):
            return previous.model_copy(
                update={
                    "payload": previous.payload.model_copy(
                        update={
                            "market_status": event.payload.market_status,
                        }
                    ),
                }
            )
        return previous
    points = tuple(
        point for point in history if timestamp - timedelta(minutes=2) < point.timestamp < timestamp
    ) + (RealtimePricePoint(timestamp=timestamp, value=event.payload.value),)
    if event.topic == "prices.crypto.twap":
        return CryptoTwapPriceSnapshotEvent(
            timestamp=event.timestamp,
            seq=event.seq,
            dropped=event.dropped,
            payload=RealtimeTwapSnapshot(
                symbol=event.payload.symbol,
                source=event.payload.source,
                data=points,
            ),
        )
    if event.topic == "prices.equity.twap":
        return EquityTwapPriceSnapshotEvent(
            timestamp=event.timestamp,
            seq=event.seq,
            dropped=event.dropped,
            payload=RealtimeEquityTwapSnapshot(
                symbol=event.payload.symbol,
                source=event.payload.source,
                data=points,
                market_status=event.payload.market_status,
            ),
        )
    if event.topic == "prices.crypto":
        payload = RealtimePriceSnapshot(
            symbol=event.payload.symbol, source=event.payload.source, data=points
        )
        return CryptoPriceSnapshotEvent(
            timestamp=event.timestamp, seq=event.seq, dropped=event.dropped, payload=payload
        )
    return EquityPriceSnapshotEvent(
        timestamp=event.timestamp,
        seq=event.seq,
        dropped=event.dropped,
        payload=RealtimeEquityPriceSnapshot(
            symbol=event.payload.symbol,
            source=event.payload.source,
            data=points,
            market_status=event.payload.market_status,
        ),
    )
