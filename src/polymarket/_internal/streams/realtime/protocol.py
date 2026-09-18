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
    EquityPriceSnapshotEvent,
    EquityPriceUpdateEvent,
    PriceEvent,
    RealtimePricePoint,
    RealtimePriceSnapshot,
    RealtimePriceUpdate,
    RealtimeTwapSnapshot,
    RealtimeTwapUpdate,
)
from polymarket.streams._specs import EquityPriceSpec, PriceSpec

PriceTopic = Literal["prices.crypto", "prices.crypto.twap", "prices.equity"]
CHANNEL_TOPICS: dict[str, PriceTopic] = {
    "price.crypto": "prices.crypto",
    "price.crypto.twap": "prices.crypto.twap",
    "price.equity": "prices.equity",
}


@dataclass(frozen=True, slots=True)
class PriceKey:
    topic: PriceTopic
    symbol: str


def subscriptions_for(spec: PriceSpec) -> tuple[PriceKey, ...]:
    symbols = (spec.symbol,) if isinstance(spec, EquityPriceSpec) else spec.symbols
    return tuple(dict.fromkeys(PriceKey(spec.topic, symbol) for symbol in symbols))


def build_wire_subscription(key: PriceKey) -> dict[str, object]:
    price_filter: dict[str, object] = {"symbol": key.symbol}
    if key.topic == "prices.crypto.twap":
        price_filter["window_seconds"] = 60
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
        if not isinstance(symbol, str):
            return None
        # Shared keys always expose their canonical spelling.
        symbol = symbol.lower()
        if topic == "prices.crypto.twap" and (
            type(payload.get("window_seconds")) is not int or payload["window_seconds"] != 60
        ):
            return None
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
                    payload=RealtimeTwapSnapshot(symbol=symbol, data=points),
                )
            history = RealtimePriceSnapshot(symbol=symbol, data=points)
            if topic == "prices.crypto":
                return CryptoPriceSnapshotEvent(
                    timestamp=timestamp, seq=seq, dropped=dropped, payload=history
                )
            return EquityPriceSnapshotEvent(
                timestamp=timestamp, seq=seq, dropped=dropped, payload=history
            )
        point = _price_point(payload)
        if topic == "prices.crypto.twap":
            return CryptoTwapPriceUpdateEvent(
                timestamp=timestamp,
                seq=seq,
                dropped=dropped,
                payload=RealtimeTwapUpdate(
                    symbol=symbol, timestamp=point.timestamp, value=point.value
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
        update = RealtimePriceUpdate(
            symbol=symbol,
            timestamp=point.timestamp,
            value=point.value,
            received_at=received_at,
            is_carried_forward=cast(bool | None, carried),
        )
        if topic == "prices.crypto":
            return CryptoPriceUpdateEvent(
                timestamp=timestamp, seq=seq, dropped=dropped, payload=update
            )
        return EquityPriceUpdateEvent(timestamp=timestamp, seq=seq, dropped=dropped, payload=update)
    except (ValueError, TypeError, KeyError, ArithmeticError):
        return None


def refresh_snapshot(previous: PriceEvent | None, event: PriceEvent) -> PriceEvent | None:
    if event.type == "subscribe":
        return event
    history = previous.payload.data if previous is not None and previous.type == "subscribe" else ()
    timestamp = event.payload.timestamp
    if history and history[-1].timestamp > timestamp:
        return previous
    points = tuple(
        point for point in history if timestamp - timedelta(minutes=2) < point.timestamp < timestamp
    ) + (RealtimePricePoint(timestamp=timestamp, value=event.payload.value),)
    if event.topic == "prices.crypto.twap":
        return CryptoTwapPriceSnapshotEvent(
            timestamp=event.timestamp,
            seq=event.seq,
            dropped=event.dropped,
            payload=RealtimeTwapSnapshot(symbol=event.payload.symbol, data=points),
        )
    payload = RealtimePriceSnapshot(symbol=event.payload.symbol, data=points)
    if event.topic == "prices.crypto":
        return CryptoPriceSnapshotEvent(
            timestamp=event.timestamp, seq=event.seq, dropped=event.dropped, payload=payload
        )
    return EquityPriceSnapshotEvent(
        timestamp=event.timestamp, seq=event.seq, dropped=event.dropped, payload=payload
    )
