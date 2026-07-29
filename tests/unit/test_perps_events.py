"""Perps realtime event parsing tests."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from polymarket.models.perps.events import (
    PerpsBookEvent,
    PerpsCandleEvent,
    PerpsDepositEvent,
    PerpsNotificationEvent,
    PerpsOrderEvent,
    PerpsResyncEvent,
    PerpsTickerEvent,
    PerpsTpSlEvent,
    parse_perps_market_event,
    parse_perps_market_events,
    parse_perps_session_event,
)
from polymarket.models.perps.notifications import (
    PerpsCrossLiquidationWarningNotification,
    PerpsIsolatedLiquidationWarningNotification,
    PerpsPositionChangeNotification,
    PerpsPositionClosedNotification,
    PerpsPositionLiquidatedNotification,
)
from polymarket.models.perps.orders import PerpsOrder


def _order_update(order_id: int = 5) -> dict[str, object]:
    return {
        "oid": order_id,
        "iid": 1,
        "buy": True,
        "p": "0.5",
        "qty": "10",
        "tif": "gtc",
        "po": False,
        "ro": True,
        "status": "open",
        "rest": "10",
        "fill": "0",
        "cts": 1751500000000,
        "uts": 1751500000001,
    }


def test_book_event_injects_instrument_id_from_channel() -> None:
    event = parse_perps_market_event(
        {
            "ch": "book::7",
            "ts": 1751500000000,
            "sq": 3,
            "data": {"b": [["0.5", "10"]], "a": [["0.6", "4"]]},
        }
    )
    assert isinstance(event, PerpsBookEvent)
    assert event.topic == "perps.book"
    assert event.payload.instrument_id == 7
    assert event.payload.bids[0].price == Decimal("0.5")
    assert event.sequence == 3


def test_candle_event_parses_interval_and_tuples() -> None:
    event = parse_perps_market_event(
        {
            "ch": "klines::7::5m",
            "ts": 1751500000000,
            "sq": 1,
            "data": [[1751500000000, "1", "2", "0.5", "1.5", "100", 3]],
        }
    )
    assert isinstance(event, PerpsCandleEvent)
    assert event.payload.interval == "5m"
    assert event.payload.candles[0].close == Decimal("1.5")
    assert event.payload.candles[0].trades == 3


def test_ticker_event_parses_compact_payload() -> None:
    event = parse_perps_market_event(
        {
            "ch": "tickers::all",
            "ts": 1751500000000,
            "sq": 2,
            "data": {
                "iid": 4,
                "idx": "100",
                "mark": "101",
                "last": "100.5",
                "mid": "100.6",
                "oi": "5000",
                "fr": "0.0001",
                "nxf": 1751503600000,
            },
        }
    )
    assert isinstance(event, PerpsTickerEvent)
    assert event.payload.instrument_id == 4
    assert event.payload.mark_price == Decimal("101")


def test_non_event_frames_are_ignored_not_dropped() -> None:
    events, dropped = parse_perps_market_events({"id": 0, "data": {"status": "ok"}})
    assert events == []
    assert dropped == 0


def test_malformed_channel_frames_count_as_dropped() -> None:
    events, dropped = parse_perps_market_events(
        {"ch": "book::7", "ts": 1751500000000, "sq": 1, "data": {"bogus": True}}
    )
    assert events == []
    assert dropped == 1


def test_session_order_event_normalizes_compact_order() -> None:
    event = parse_perps_session_event(
        {"ch": "orders", "ts": 1751500000000, "sq": 9, "data": _order_update()}
    )
    assert isinstance(event, PerpsOrderEvent)
    assert event.payload.id == 5
    assert event.payload.reduce_only is True
    assert event.payload.side == "BUY"
    assert event.payload.status == "open"


def test_order_model_normalizes_reduce_only_response_field() -> None:
    order = PerpsOrder.parse_response(
        {
            "order_id": 5,
            "instrument_id": 1,
            "buy": True,
            "price": "0.5",
            "quantity": "10",
            "tif": "gtc",
            "post_only": False,
            "ro": True,
            "status": "open",
            "resting_quantity": "10",
            "filled_quantity": "0",
            "created_timestamp": 1751500000000,
            "updated_timestamp": 1751500000001,
        }
    )

    assert order.reduce_only is True


def test_session_tpsl_event_parses_lifecycle_update() -> None:
    event = parse_perps_session_event(
        {
            "ch": "tpsl::12",
            "ts": 1751500000000,
            "sq": 1,
            "data": {"oid": 44, "st": "armed"},
        }
    )
    assert isinstance(event, PerpsTpSlEvent)
    assert event.payload.order_id == 44
    assert event.payload.status == "armed"


def test_session_deposit_event_normalizes_placeholder_hash() -> None:
    event = parse_perps_session_event(
        {
            "ch": "deposits",
            "ts": 1751500000000,
            "sq": 1,
            "data": {"hash": "0x", "asset": "USDC", "amount": "10", "status": "pending"},
        }
    )
    assert isinstance(event, PerpsDepositEvent)
    assert event.payload.hash is None
    assert event.payload.amount == Decimal("10")


@pytest.mark.parametrize(
    "frame",
    [
        {"id": 1, "data": [{"status": "ok", "oid": 2}]},
        {"ch": "unknown-channel", "ts": 1, "sq": 1, "data": {}},
        "not-a-dict",
    ],
)
def test_session_parser_returns_none_for_non_events(frame: object) -> None:
    assert parse_perps_session_event(frame) is None


def _notification_frame(notification: dict[str, object]) -> dict[str, object]:
    return {"ch": "notifications", "ts": 1751500000000, "sq": 42, "data": notification}


def test_session_notification_event_parses_position_change() -> None:
    event = parse_perps_session_event(
        _notification_frame(
            {
                "id": "5f4a3c2b-1d0e-49f8-a7b6-c5d4e3f2a1b0",
                "type": "position_increased",
                "instrument_id": 3,
                "side": "short",
                "size": "1.5",
                "avg_price": "99.5",
                "leverage": 4,
                "order_type": "stop_loss",
            }
        )
    )
    assert isinstance(event, PerpsNotificationEvent)
    assert event.sequence == 42
    assert isinstance(event.payload, PerpsPositionChangeNotification)
    assert event.payload.type == "position_increased"
    assert event.payload.size == Decimal("1.5")
    assert event.payload.order_type == "stop_loss"


def test_session_notification_event_parses_position_closed_without_order_type() -> None:
    event = parse_perps_session_event(
        _notification_frame(
            {
                "id": "5f4a3c2b-1d0e-49f8-a7b6-c5d4e3f2a1b0",
                "type": "position_closed",
                "instrument_id": 3,
                "side": "long",
                "size": "1.5",
                "avg_price": "99.5",
                "pnl": "-0.25",
            }
        )
    )
    assert isinstance(event, PerpsNotificationEvent)
    assert isinstance(event.payload, PerpsPositionClosedNotification)
    assert event.payload.pnl == Decimal("-0.25")
    assert event.payload.order_type is None


def test_session_notification_event_parses_liquidation_warning_variants() -> None:
    isolated = parse_perps_session_event(
        _notification_frame(
            {
                "id": "5f4a3c2b-1d0e-49f8-a7b6-c5d4e3f2a1b0",
                "type": "liquidation_warning",
                "margin_type": "isolated",
                "instrument_id": 3,
                "mark_price": "100",
                "liq_price": "95",
            }
        )
    )
    assert isinstance(isolated, PerpsNotificationEvent)
    assert isinstance(isolated.payload, PerpsIsolatedLiquidationWarningNotification)
    assert isolated.payload.liquidation_price == Decimal("95")

    cross = parse_perps_session_event(
        _notification_frame(
            {
                "id": "5f4a3c2b-1d0e-49f8-a7b6-c5d4e3f2a1b0",
                "type": "liquidation_warning",
                "margin_type": "cross",
                "instrument_id": None,
                "mark_price": "100",
                "affected_instruments": [3, 5],
            }
        )
    )
    assert isinstance(cross, PerpsNotificationEvent)
    assert isinstance(cross.payload, PerpsCrossLiquidationWarningNotification)
    assert cross.payload.affected_instruments == (3, 5)


def test_session_notification_event_parses_position_liquidated_with_null_pnl() -> None:
    event = parse_perps_session_event(
        _notification_frame(
            {
                "id": "5f4a3c2b-1d0e-49f8-a7b6-c5d4e3f2a1b0",
                "type": "position_liquidated",
                "instrument_id": 3,
                "side": "long",
                "size_closed": "1.5",
                "pnl": None,
                "margin_type": "cross",
                "via_backstop": True,
            }
        )
    )
    assert isinstance(event, PerpsNotificationEvent)
    assert isinstance(event.payload, PerpsPositionLiquidatedNotification)
    assert event.payload.pnl is None
    assert event.payload.via_backstop is True


def test_session_notification_with_unknown_type_fails_validation() -> None:
    with pytest.raises(ValidationError):
        parse_perps_session_event(
            _notification_frame(
                {"id": "5f4a3c2b-1d0e-49f8-a7b6-c5d4e3f2a1b0", "type": "new_notification_kind"}
            )
        )


def test_notifications_resync_frame_parses_as_server_resync_event() -> None:
    event = parse_perps_session_event(
        {"ch": "notifications", "ts": 1751500000000, "sq": 77, "type": "resync"}
    )
    assert isinstance(event, PerpsResyncEvent)
    assert event.reason == "server"
    assert event.channel == "notifications"
    assert event.sequence == 77
    assert event.timestamp is not None
